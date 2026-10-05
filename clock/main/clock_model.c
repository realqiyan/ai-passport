#include "clock_model.h"

#define DAY_SECONDS INT64_C(86400)
#define LIMIT_SECONDS INT64_C(3155760000) /* 2000-01-01 through 2099-12-31. */

int clock_days_in_month(int year, int month)
{
    static const int days[] = {31,28,31,30,31,30,31,31,30,31,30,31};
    if (month < 1 || month > 12) return 0;
    bool leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
    return days[month - 1] + (month == 2 && leap);
}

bool clock_date_valid(clock_date_t d)
{
    return d.year >= 2000 && d.year <= 2099 && d.month >= 1 && d.month <= 12
        && d.day >= 1 && d.day <= clock_days_in_month(d.year, d.month)
        && d.hour >= 0 && d.hour < 24 && d.minute >= 0 && d.minute < 60
        && d.second >= 0 && d.second < 60;
}

int64_t clock_encode(clock_date_t d)
{
    if (!clock_date_valid(d)) return -1;
    int64_t days = 0;
    for (int y = 2000; y < d.year; y++) days += clock_days_in_month(y, 2) == 29 ? 366 : 365;
    for (int m = 1; m < d.month; m++) days += clock_days_in_month(d.year, m);
    return (days + d.day - 1) * DAY_SECONDS + d.hour * 3600 + d.minute * 60 + d.second;
}

clock_date_t clock_decode(int64_t seconds)
{
    if (seconds < 0) seconds = 0;
    seconds %= LIMIT_SECONDS;
    clock_date_t d = { .year = 2000, .month = 1, .day = 1 };
    int days = (int)(seconds / DAY_SECONDS);
    d.hour = (int)(seconds % DAY_SECONDS / 3600);
    d.minute = (int)(seconds % 3600 / 60);
    d.second = (int)(seconds % 60);
    for (;;) {
        int n = clock_days_in_month(d.year, 2) == 29 ? 366 : 365;
        if (days < n) break;
        days -= n;
        d.year++;
    }
    while (days >= clock_days_in_month(d.year, d.month)) days -= clock_days_in_month(d.year, d.month++);
    d.day += days;
    return d;
}

void clock_init(clock_model_t *c, int64_t seconds, int64_t now_us)
{
    *c = (clock_model_t){ .seconds = seconds >= 0 && seconds < LIMIT_SECONDS ? seconds : 0,
                         .anchor_us = now_us, .brightness = 80 };
}

void clock_tick(clock_model_t *c, int64_t now_us)
{
    if (now_us < c->anchor_us) { c->anchor_us = now_us; return; }
    int64_t elapsed = (now_us - c->anchor_us) / INT64_C(1000000);
    c->seconds = (c->seconds + elapsed) % LIMIT_SECONDS;
    c->anchor_us += elapsed * INT64_C(1000000);
}

void clock_edit_begin(clock_model_t *c)
{
    c->draft = clock_decode(c->seconds);
    c->draft.second = 0;
    c->field = CLOCK_YEAR;
    c->editing = true;
}

static int wrap(int value, int min, int max, int direction)
{
    if (direction > 0) return value == max ? min : value + 1;
    return value == min ? max : value - 1;
}

void clock_edit_adjust(clock_model_t *c, int direction)
{
    if (!c->editing || direction == 0) return;
    clock_date_t *d = &c->draft;
    switch (c->field) {
    case CLOCK_YEAR: d->year = wrap(d->year, 2000, 2099, direction); break;
    case CLOCK_MONTH: d->month = wrap(d->month, 1, 12, direction); break;
    case CLOCK_DAY: d->day = wrap(d->day, 1, clock_days_in_month(d->year, d->month), direction); break;
    case CLOCK_HOUR: d->hour = wrap(d->hour, 0, 23, direction); break;
    case CLOCK_MINUTE: d->minute = wrap(d->minute, 0, 59, direction); break;
    default: return;
    }
    int max_day = clock_days_in_month(d->year, d->month);
    if (d->day > max_day) d->day = max_day;
}

bool clock_edit_next(clock_model_t *c, int64_t now_us)
{
    if (!c->editing) return false;
    if (c->field < CLOCK_MINUTE) { c->field++; return false; }
    c->seconds = clock_encode(c->draft);
    c->anchor_us = now_us;
    c->editing = false;
    c->confirmed = true;
    return true;
}

void clock_edit_cancel(clock_model_t *c) { c->editing = false; }
int clock_display_hour(int hour, bool twelve_hour) { return twelve_hour ? (hour % 12 ? hour % 12 : 12) : hour; }
int clock_weekday(int64_t seconds) { return (int)((seconds / DAY_SECONDS + 6) % 7); }
