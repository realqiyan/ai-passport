#pragma once
#include <stdbool.h>
#include <stdint.h>

#define CLOCK_IDLE_US INT64_C(30000000)

typedef struct { int year, month, day, hour, minute, second; } clock_date_t;
typedef enum { CLOCK_YEAR, CLOCK_MONTH, CLOCK_DAY, CLOCK_HOUR, CLOCK_MINUTE, CLOCK_FIELD_COUNT } clock_field_t;
typedef struct {
    int64_t seconds;
    int64_t anchor_us;
    clock_date_t draft;
    clock_field_t field;
    bool editing;
    bool confirmed;
    bool twelve_hour;
    unsigned brightness;
    int64_t last_input_us;
    bool screen_off;
    unsigned suppressed_buttons;
} clock_model_t;

int clock_days_in_month(int year, int month);
bool clock_date_valid(clock_date_t date);
int64_t clock_encode(clock_date_t date);
clock_date_t clock_decode(int64_t seconds);
void clock_init(clock_model_t *clock, int64_t seconds, int64_t now_us);
void clock_tick(clock_model_t *clock, int64_t now_us);
void clock_edit_begin(clock_model_t *clock);
void clock_edit_adjust(clock_model_t *clock, int direction);
/* Return true when the final field commits a new time. */
bool clock_edit_next(clock_model_t *clock, int64_t now_us);
void clock_edit_cancel(clock_model_t *clock);
int clock_display_hour(int hour, bool twelve_hour);
int clock_weekday(int64_t seconds); /* Sunday = 0. */

/* Press wakes the screen. Consume all actions from that press until the next press. */
bool clock_input(clock_model_t *clock, unsigned button, bool press, int64_t now_us);
bool clock_should_blank(const clock_model_t *clock, int64_t now_us);
int64_t clock_wait_us(const clock_model_t *clock, int64_t now_us);
