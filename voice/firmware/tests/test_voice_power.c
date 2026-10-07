#include "voice_sleep_test_stubs.h"
#include "driver/gpio.h"
#include "esp_pm.h"
#include "voice_power.h"
#include "voice_runtime.h"
#include <assert.h>
#include <setjmp.h>
#include <stdio.h>
#include <string.h>

_Atomic bool voice_mic, voice_audio, voice_wifi_mode, voice_screen_off, voice_codec_asleep;
enum { MAP = 1, CREATE, ACQUIRE, LVGL, PAUSE, STOP_BUTTONS, PIN_INPUT,
       WAKE_CLEAR, WAKE_GPIO, BATTERY, CODEC, I2S, I2C, DISPLAY, DEEP };
static int fail, count, calls[64], usb_checks, usb_on_check, mv = 3300, level = 1;
static int resumed, buttons_resumed, unlocked, released_lock, deleted_lock, analog_restored;
static int reset_reason, wake_cause, gpio_reads, delay_count, delay_total;
static bool bounce;
static bool light_sleep_blocked;
static unsigned wake_sources, wifi_wake_restored;
static jmp_buf sleeping;
static int action(int step) {
    assert(count < 64);
    calls[count++] = step;
    return step == fail ? ESP_FAIL : ESP_OK;
}
static void reset_test(void) {
    fail = count = usb_checks = usb_on_check = 0;
    resumed = buttons_resumed = unlocked = released_lock = deleted_lock = analog_restored = 0;
    gpio_reads = delay_count = delay_total = 0;
    mv = 3300; level = 1; bounce = false;
    light_sleep_blocked = false; wake_sources = 1u << 3; wifi_wake_restored = 0;
    voice_wifi_mode = voice_screen_off = voice_codec_asleep = true;
    voice_mic = voice_audio = false;
}
esp_err_t adc_oneshot_channel_to_io(int unit, int channel, int *pin) {
    assert(unit == 0 && channel == 0); *pin = 0; return action(MAP);
}
esp_err_t gpio_hold_dis(int pin) { assert(pin == 0); return ESP_OK; }
esp_err_t gpio_config(const gpio_config_t *cfg) {
    assert(cfg->pin_bit_mask == 1 && cfg->mode == GPIO_MODE_INPUT);
    assert(cfg->pull_up_en == GPIO_PULLUP_DISABLE && cfg->pull_down_en == GPIO_PULLDOWN_DISABLE);
    return action(PIN_INPUT);
}
esp_err_t gpio_set_direction(int pin, int mode) {
    assert(pin == 0 && mode == GPIO_MODE_DISABLE); analog_restored++; return ESP_OK;
}
int gpio_get_level(int pin) {
    assert(pin == 0);
    const int samples[] = {0, 0, 1, 1, 0, 1, 1, 1, 1};
    if (bounce && gpio_reads < 9) return samples[gpio_reads++];
    gpio_reads++; return level;
}
bool usb_serial_jtag_is_connected(void) { return ++usb_checks == usb_on_check; }
int bsp_button_read_mv(void) { return mv; }
esp_err_t esp_pm_lock_create(int type, int arg, const char *name, esp_pm_lock_handle_t *lock) {
    assert(type == ESP_PM_NO_LIGHT_SLEEP && arg == 0 && !strcmp(name, "voice_sleep"));
    *lock = &fail; return action(CREATE);
}
esp_err_t esp_pm_lock_acquire(esp_pm_lock_handle_t lock) {
    assert(lock == &fail); int err = action(ACQUIRE); light_sleep_blocked = err == ESP_OK; return err;
}
esp_err_t esp_pm_lock_release(esp_pm_lock_handle_t lock) {
    assert(lock == &fail); light_sleep_blocked = false; released_lock++; return ESP_OK;
}
esp_err_t esp_pm_lock_delete(esp_pm_lock_handle_t lock) { assert(lock == &fail); deleted_lock++; return ESP_OK; }
bool bsp_lvgl_lock(int timeout) { assert(timeout == 1000); return action(LVGL) == ESP_OK; }
void bsp_lvgl_unlock(void) { unlocked++; }
esp_err_t voice_runtime_pause(void) { return action(PAUSE); }
void voice_runtime_resume(void) { resumed++; }
esp_err_t iot_button_stop(void) { return action(STOP_BUTTONS); }
esp_err_t iot_button_resume(void) { buttons_resumed++; return ESP_OK; }
esp_err_t esp_sleep_disable_wakeup_source(int source) {
    if (source == ESP_SLEEP_WAKEUP_GPIO) { wake_sources &= ~(1u << 7); return ESP_OK; }
    assert(source == ESP_SLEEP_WAKEUP_ALL);
    int err = action(WAKE_CLEAR); if (err == ESP_OK) wake_sources = 0; return err;
}
esp_err_t esp_deep_sleep_enable_gpio_wakeup(uint64_t mask, int mode) {
    assert(mask == 1 && mode == ESP_GPIO_WAKEUP_GPIO_LOW);
    int err = action(WAKE_GPIO); if (err == ESP_OK) wake_sources |= 1u << 7; return err;
}
esp_err_t esp_sleep_enable_wifi_wakeup(void) { wake_sources |= 1u << 3; wifi_wake_restored++; return ESP_OK; }
esp_err_t bsp_battery_sleep(void) { assert(light_sleep_blocked); vTaskDelay(5); return action(BATTERY); }
esp_err_t bsp_audio_sleep(void) { return action(CODEC); }
esp_err_t bsp_audio_prepare_deep_sleep(void) { return action(I2S); }
esp_err_t bsp_i2c_prepare_deep_sleep(void) { return action(I2C); }
esp_err_t bsp_display_prepare_deep_sleep(void) { assert(light_sleep_blocked); vTaskDelay(100); return action(DISPLAY); }
void esp_deep_sleep_start(void) {
    assert(light_sleep_blocked && wake_sources == (1u << 7)); action(DEEP); longjmp(sleeping, 1);
}
void esp_restart(void) { assert(!"unexpected restart"); }
int esp_reset_reason(void) { return reset_reason; }
int esp_sleep_get_wakeup_cause(void) { return wake_cause; }
void vTaskDelay(unsigned ticks) {
    if (!light_sleep_blocked) wake_sources |= 1u << ESP_SLEEP_WAKEUP_TIMER;
    delay_count++; delay_total += ticks;
}

int main(void) {
    reset_test();
    /* A normal boot never restores a stale mode. */
    assert(!voice_power_restore() && voice_power_deep_wakes() == 0);
    for (int guard = 0; guard < 8; guard++) {
        reset_test();
        switch (guard) {
            case 0: usb_on_check = 1; break;
            case 1: voice_wifi_mode = false; break;
            case 2: voice_mic = true; break;
            case 3: voice_audio = true; break;
            case 4: voice_screen_off = false; break;
            case 5: voice_codec_asleep = false; break;
            case 6: mv = -1; break;
            case 7: mv = 1899; break;
        }
        assert(voice_power_sleep() == ESP_ERR_INVALID_STATE && count == 0);
    }
    /* Reversible failures cannot leave workers or the button timer stopped. */
    for (int step = MAP; step <= WAKE_GPIO; step++) {
        reset_test(); fail = step;
        int expected = step == LVGL ? ESP_ERR_TIMEOUT : ESP_FAIL;
        assert(voice_power_sleep() == expected);
        assert(calls[count - 1] == step);
        assert(deleted_lock == (step > CREATE));
        assert(released_lock == (step > ACQUIRE));
        assert(unlocked == (step > LVGL));
        assert(resumed == (step > PAUSE));
        assert(buttons_resumed == (step > STOP_BUTTONS));
        assert(analog_restored == (step >= PIN_INPUT));
        assert(wifi_wake_restored == (step == WAKE_GPIO));
    }
    for (int late = 0; late < 2; late++) {
        reset_test();
        if (late) usb_on_check = 2; else level = 0;
        assert(voice_power_sleep() == ESP_ERR_INVALID_STATE);
        assert(resumed == 1 && buttons_resumed == 1 && unlocked == 1 && released_lock == 1);
        assert(calls[count - 1] == PIN_INPUT);
    }
    /* Once a bus is released, every remaining shutdown step must run. */
    for (int step = 0; step <= DISPLAY; step++) {
        if (step && step < BATTERY) continue;
        reset_test(); fail = step;
        if (!setjmp(sleeping)) {
            (void)voice_power_sleep();
            assert(!"sleep entry returned");
        }
        assert(count == DEEP);
        for (int i = 0; i < count; i++) assert(calls[i] == i + 1);
        assert(!resumed && !buttons_resumed && !unlocked && !released_lock);
        assert(voice_power_last_sleep_error() == (step ? ESP_FAIL : ESP_OK));
        reset_reason = ESP_RST_DEEPSLEEP; wake_cause = ESP_SLEEP_WAKEUP_GPIO;
        count = gpio_reads = delay_count = delay_total = 0; bounce = true;
        assert(voice_power_restore());
        assert(gpio_reads == 9 && delay_count == 9 && delay_total == 180);
        assert(voice_power_deep_wakes() == (uint32_t)(step ? step - BATTERY + 2 : 1));
    }
    reset_reason = 0; count = 0;
    assert(!voice_power_restore() && voice_power_deep_wakes() == 0 && voice_power_last_sleep_error() == ESP_OK);
    puts("Voice deep sleep guards, shutdown, rollback and wake release tests: PASS");
}
