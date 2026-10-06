#include "bsp_display.h"
#include "bsp_display_power.h"
#include <assert.h>
#include <stdio.h>

enum { BACKLIGHT_OFF = 1, DISPLAY_OFF, SLEEP_IN, SLEEP_OUT, DISPLAY_ON };
static int token, present = 1, fail, count, calls[16];
static bool asleep, visible = true;

esp_lcd_panel_handle_t bsp_display_panel(void) { return present ? &token : NULL; }
void bsp_display_backlight(uint8_t percent) {
    assert(percent == 0);
    calls[count++] = BACKLIGHT_OFF;
}
esp_err_t esp_lcd_panel_disp_on_off(esp_lcd_panel_handle_t panel, bool on) {
    assert(panel == &token);
    int action = on ? DISPLAY_ON : DISPLAY_OFF;
    calls[count++] = action;
    if (action == fail) return ESP_FAIL;
    visible = on;
    return ESP_OK;
}
esp_err_t esp_lcd_panel_disp_sleep(esp_lcd_panel_handle_t panel, bool sleep) {
    assert(panel == &token);
    int action = sleep ? SLEEP_IN : SLEEP_OUT;
    calls[count++] = action;
    if (action == fail) return ESP_FAIL;
    asleep = sleep;
    return ESP_OK;
}
int main(void) {
    for (int i = 0; i < 16; i++) {
        count = 0;
        assert(bsp_display_sleep() == ESP_OK && asleep && !visible);
        assert(count == 3 && calls[0] == BACKLIGHT_OFF && calls[1] == DISPLAY_OFF && calls[2] == SLEEP_IN);
        assert(bsp_display_wake() == ESP_OK && !asleep && visible);
        assert(count == 5 && calls[3] == SLEEP_OUT && calls[4] == DISPLAY_ON);
    }
    /* A failed entry restores the panel; the caller resumes LVGL/backlight. */
    for (fail = DISPLAY_OFF; fail <= SLEEP_IN; fail++) {
        count = 0;
        assert(bsp_display_sleep() == ESP_FAIL && !asleep && visible);
        assert(calls[count - 2] == SLEEP_OUT && calls[count - 1] == DISPLAY_ON);
    }
    fail = 0;
    count = 0;
    assert(bsp_display_sleep() == ESP_OK);
    fail = SLEEP_OUT;
    count = 0;
    assert(bsp_display_wake() == ESP_FAIL && asleep && !visible);
    assert(count == 1); // Do not enable display after failed sleep-out.
    fail = 0;
    assert(bsp_display_wake() == ESP_OK && !asleep && visible);
    present = 0;
    count = 0;
    assert(bsp_display_sleep() == ESP_ERR_INVALID_STATE);
    assert(bsp_display_wake() == ESP_ERR_INVALID_STATE);
    assert(count == 0);
    puts("Voice display sleep, wake and rollback tests: PASS");
}
