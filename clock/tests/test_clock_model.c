#include "clock_model.h"
#include <assert.h>
#include <stdio.h>

static void test_calendar_roundtrip(void)
{
    for (int y = 2000; y <= 2099; y++) {
        for (int m = 1; m <= 12; m++) {
            for (int day = 1; day <= clock_days_in_month(y, m); day++) {
                clock_date_t d = {y,m,day,23,59,59};
                clock_date_t decoded = clock_decode(clock_encode(d));
                assert(decoded.year == y && decoded.month == m && decoded.day == day);
                assert(decoded.hour == 23 && decoded.minute == 59 && decoded.second == 59);
            }
        }
    }
    assert(clock_days_in_month(2000, 2) == 29);
    assert(clock_days_in_month(2100, 2) == 28);
    assert(clock_encode((clock_date_t){2025,2,29,0,0,0}) == -1);
    assert(clock_encode((clock_date_t){2026,1,1,24,0,0}) == -1);
    assert(clock_weekday(0) == 6);
}

static void test_elapsed_and_rollover(void)
{
    clock_model_t c;
    clock_init(&c, clock_encode((clock_date_t){2024,2,28,23,59,59}), 100);
    clock_tick(&c, 1000100);
    clock_date_t d = clock_decode(c.seconds);
    assert(d.month == 2 && d.day == 29 && d.hour == 0 && d.second == 0);
    clock_tick(&c, 1500100);
    assert(c.anchor_us == 1000100);
    clock_tick(&c, 2000100);
    assert(clock_decode(c.seconds).second == 1);
    clock_tick(&c, 100);
    assert(clock_decode(c.seconds).second == 1 && c.anchor_us == 100);
    clock_init(&c, clock_encode((clock_date_t){2099,12,31,23,59,59}), 0);
    clock_tick(&c, 1000000);
    assert(c.seconds == 0);
}

static void test_edit_commit_and_cancel(void)
{
    clock_model_t c;
    clock_init(&c, clock_encode((clock_date_t){2024,1,31,23,59,45}), 0);
    assert(!c.confirmed);
    clock_edit_begin(&c);
    assert(!clock_edit_next(&c, 0));
    clock_edit_adjust(&c, 1);
    assert(c.draft.month == 2 && c.draft.day == 29);
    c.field = CLOCK_YEAR;
    clock_edit_adjust(&c, 1);
    assert(c.draft.year == 2025 && c.draft.day == 28);
    clock_tick(&c, 2000000);
    clock_edit_cancel(&c);
    assert(clock_decode(c.seconds).second == 47 && !c.confirmed);
    clock_edit_begin(&c);
    c.field = CLOCK_MINUTE;
    clock_edit_adjust(&c, 1);
    assert(c.draft.minute == 0);
    assert(clock_edit_next(&c, 2500000));
    assert(c.confirmed && !c.editing && c.anchor_us == 2500000);
    assert(clock_decode(c.seconds).second == 0);
    clock_tick(&c, 3499999);
    assert(clock_decode(c.seconds).second == 0);
    assert(!clock_edit_next(&c, 3500000));
    assert(clock_display_hour(0, true) == 12);
    assert(clock_display_hour(12, true) == 12);
    assert(clock_display_hour(23, true) == 11);
    assert(clock_display_hour(23, false) == 23);
}

static void test_idle_and_button_wake(void)
{
    clock_model_t c;
    clock_init(&c, 0, 100);
    assert(c.brightness == 25);
    assert(!clock_should_blank(&c, CLOCK_IDLE_US + 99));
    assert(clock_should_blank(&c, CLOCK_IDLE_US + 100));
    clock_edit_begin(&c);
    assert(!clock_should_blank(&c, CLOCK_IDLE_US * 2));
    clock_edit_cancel(&c);
    assert(clock_should_blank(&c, CLOCK_IDLE_US * 2));
    c.screen_off = true;
    assert(!clock_should_blank(&c, CLOCK_IDLE_US * 2));
    /* Wake on each of the three keys; consume both short and long actions. */
    for (unsigned key = 0; key < 3; key++) {
        c.screen_off = true;
        assert(!clock_input(&c, key, true, CLOCK_IDLE_US * 2));
        assert(!c.screen_off);
        assert(!clock_input(&c, key, false, CLOCK_IDLE_US * 2 + 100));
        assert(!clock_input(&c, key, false, CLOCK_IDLE_US * 2 + 200));
        assert(!clock_input(&c, key, true, CLOCK_IDLE_US * 2 + 300));
        assert(clock_input(&c, key, false, CLOCK_IDLE_US * 2 + 400));
    }
    /* An overlapping press on another key must not unsuppress the wake key. */
    c.screen_off = true;
    assert(!clock_input(&c, 0, true, 90000000));
    assert(!clock_input(&c, 1, true, 90000001));
    assert(clock_input(&c, 1, false, 90000002));
    assert(!clock_input(&c, 0, false, 90000003));
    assert(!clock_should_blank(&c, 120000002));
    assert(clock_should_blank(&c, 120000003));
    assert(!clock_input(&c, 3, true, 120000004));
    assert(c.last_input_us == 90000003);
}

static void test_sleep_elapsed_and_deadlines(void)
{
    clock_model_t c;
    int64_t start = clock_encode((clock_date_t){2026,12,31,23,59,40});
    clock_init(&c, start, 100);
    assert(clock_wait_us(&c, 100) == 1000000);
    assert(clock_wait_us(&c, 1000100) == 1000000);
    clock_tick(&c, 1500100);
    assert(clock_wait_us(&c, 1500100) == 500000);
    assert(clock_wait_us(&c, CLOCK_IDLE_US + 99) == 1);
    c.screen_off = true;
    assert(clock_wait_us(&c, CLOCK_IDLE_US * 60 + 123) == CLOCK_IDLE_US);
    /* A long timer gap represents Light-sleep; no restart and no lost remainder. */
    clock_tick(&c, CLOCK_IDLE_US * 60 + 500100);
    clock_date_t d = clock_decode(c.seconds);
    assert(d.year == 2027 && d.month == 1 && d.day == 1);
    assert(d.hour == 0 && d.minute == 29 && d.second == 40);
    assert(!clock_input(&c, 2, true, CLOCK_IDLE_US * 60 + 500100));
    assert(clock_wait_us(&c, CLOCK_IDLE_US * 60 + 500100) == 500000);
    assert(c.seconds == start + 1800);
}

int main(void)
{
    test_calendar_roundtrip();
    test_elapsed_and_rollover();
    test_edit_commit_and_cancel();
    test_idle_and_button_wake();
    test_sleep_elapsed_and_deadlines();
    puts("Clock model tests: PASS");
}
