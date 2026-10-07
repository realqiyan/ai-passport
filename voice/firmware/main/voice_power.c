#include "voice_power.h"
#include "voice_runtime.h"
#include "bsp_audio.h"
#include "bsp_battery.h"
#include "bsp_button.h"
#include "bsp_display.h"
#include "bsp_i2c.h"
#include "bsp_pins.h"
#include "driver/gpio.h"
#include "driver/usb_serial_jtag.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_attr.h"
#include "esp_pm.h"
#include "esp_sleep.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "iot_button.h"

#define SLEEP_MAGIC UINT32_C(0x56505332)
static RTC_DATA_ATTR uint32_t sleep_magic, deep_wakes;
static RTC_DATA_ATTR int sleep_error;

static esp_err_t wake_pin(int *pin) {
    return adc_oneshot_channel_to_io(BSP_BTN_ADC_UNIT, BSP_BTN_ADC_CHANNEL, pin);
}
static esp_err_t pin_input(int pin) {
    const gpio_config_t cfg = {
        .pin_bit_mask = UINT64_C(1) << pin, .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE, .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    return gpio_config(&cfg);
}
bool voice_power_restore(void) {
    bool woke = sleep_magic == SLEEP_MAGIC && esp_reset_reason() == ESP_RST_DEEPSLEEP &&
                esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_GPIO;
    int pin;
    if (wake_pin(&pin) != ESP_OK)
        return false;
    /* IDF holds the wake pin during deep sleep. Release it even after a USB reset. */
    if (gpio_hold_dis(pin) != ESP_OK)
        return false;
    if (!woke) {
        sleep_magic = deep_wakes = 0;
        sleep_error = ESP_OK;
        return false;
    }
    deep_wakes++;
    if (pin_input(pin) == ESP_OK) {
        unsigned released = 0;
        while (released < 4) {
            vTaskDelay(pdMS_TO_TICKS(20));
            released = gpio_get_level(pin) ? released + 1 : 0;
        }
        (void)gpio_set_direction(pin, GPIO_MODE_DISABLE);
    }
    return true;
}
uint32_t voice_power_deep_wakes(void) { return deep_wakes; }
int voice_power_last_sleep_error(void) { return sleep_error; }
static void record_error(esp_err_t err) {
    if (sleep_error == ESP_OK)
        sleep_error = err;
}
esp_err_t voice_power_sleep(void) {
    if (usb_serial_jtag_is_connected() || !voice_wifi_mode || voice_mic || voice_audio ||
        !voice_screen_off || !voice_codec_asleep || bsp_button_read_mv() < 1900)
        return ESP_ERR_INVALID_STATE;
    int pin;
    esp_err_t err = wake_pin(&pin);
    if (err != ESP_OK)
        return err;
    esp_pm_lock_handle_t lock;
    err = esp_pm_lock_create(ESP_PM_NO_LIGHT_SLEEP, 0, "voice_sleep", &lock);
    if (err != ESP_OK)
        return err;
    err = esp_pm_lock_acquire(lock);
    if (err != ESP_OK) {
        (void)esp_pm_lock_delete(lock);
        return err;
    }
    bool locked = bsp_lvgl_lock(1000);
    bool paused = false, buttons_stopped = false, pin_changed = false, wake_cleared = false;
    if (!locked) {
        err = ESP_ERR_TIMEOUT;
        goto rollback;
    }
    err = voice_runtime_pause();
    if (err != ESP_OK)
        goto rollback;
    paused = true;
    err = iot_button_stop();
    if (err != ESP_OK)
        goto rollback;
    buttons_stopped = true;
    err = pin_input(pin);
    pin_changed = true;
    if (err != ESP_OK)
        goto rollback;
    /* A press or USB insertion during preparation cancels this attempt. */
    if (!gpio_get_level(pin) || usb_serial_jtag_is_connected()) {
        err = ESP_ERR_INVALID_STATE;
        goto rollback;
    }
    err = esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_ALL);
    if (err == ESP_OK) {
        wake_cleared = true;
        err = esp_deep_sleep_enable_gpio_wakeup(UINT64_C(1) << pin, ESP_GPIO_WAKEUP_GPIO_LOW);
    }
    if (err != ESP_OK)
        goto rollback;

    /* From here, BSP bus/pin shutdown is terminal. Continue even if a device
       fails to acknowledge standby. Only a reboot can restore these buses. */
    sleep_error = ESP_OK;
    record_error(bsp_battery_sleep());
    record_error(bsp_audio_sleep());
    record_error(bsp_audio_prepare_deep_sleep());
    record_error(bsp_i2c_prepare_deep_sleep());
    record_error(bsp_display_prepare_deep_sleep());
    sleep_magic = SLEEP_MAGIC;
    /* The NO_LIGHT_SLEEP lock prevents PM from adding a timer wake during
       peripheral delays. Deep sleep has only the button wake source. */
    esp_deep_sleep_start();
    esp_restart();
    return ESP_FAIL;

rollback:
    (void)esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_GPIO);
    /* Wi-Fi installs this source at init, not start. Restore it if clearing
       sources was followed by a failed GPIO setup. PM restores its own timer. */
    if (wake_cleared)
        (void)esp_sleep_enable_wifi_wakeup();
    if (pin_changed)
        (void)gpio_set_direction(pin, GPIO_MODE_DISABLE);
    if (buttons_stopped)
        (void)iot_button_resume();
    if (paused)
        voice_runtime_resume();
    if (locked)
        bsp_lvgl_unlock();
    (void)esp_pm_lock_release(lock);
    (void)esp_pm_lock_delete(lock);
    return err;
}
