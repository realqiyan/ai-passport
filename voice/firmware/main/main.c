#include "bsp_battery.h"
#include "bsp_button.h"
#include "bsp_display.h"
#include "bsp_display_power.h"
#include "esp_log.h"
#include "esp_pm.h"
#include "esp_lvgl_port.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "lvgl.h"
#include "nvs_flash.h"
#include "voice_model.h"
#include "voice_power.h"
#include "voice_runtime.h"
#include "driver/usb_serial_jtag.h"
#include <stdio.h>
#include <string.h>
typedef struct {
    bsp_btn_t button;
    bsp_btn_ev_t event;
} input_t;
static QueueHandle_t inputs;
static lv_obj_t *battery_label, *mic_label, *link_label, *message_label, *address_label;
static const char *message = "Start the Mac bridge";
static int64_t message_until;
static lv_obj_t *label(lv_obj_t *screen, int y, const lv_font_t *font, uint32_t color) {
    lv_obj_t *obj = lv_label_create(screen);
    lv_obj_set_width(obj, 208);
    lv_obj_set_style_text_font(obj, font, 0);
    lv_obj_set_style_text_color(obj, lv_color_hex(color), 0);
    lv_obj_set_style_text_align(obj, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(obj, LV_ALIGN_TOP_MID, 0, y);
    return obj;
}
static void ui_create(void) {
    lv_obj_t *screen = lv_obj_create(NULL);
    lv_obj_remove_flag(screen, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(screen, lv_color_hex(0x111820), 0);
    lv_obj_set_style_pad_all(screen, 0, 0);
    lv_obj_t *title = label(screen, 22, &lv_font_montserrat_20, 0x78ddbe);
    lv_label_set_text(title, "VOICE");
    lv_obj_set_width(title, 100);
    lv_obj_align(title, LV_ALIGN_TOP_LEFT, 16, 22);
    battery_label = label(screen, 24, &lv_font_montserrat_14, 0xbac8d6);
    lv_obj_set_width(battery_label, 60);
    lv_obj_align(battery_label, LV_ALIGN_TOP_RIGHT, -16, 24);
    mic_label = label(screen, 75, &lv_font_montserrat_20, 0xf4f7fb);
    link_label = label(screen, 112, &lv_font_montserrat_14, 0xbac8d6);
    address_label = label(screen, 137, &lv_font_montserrat_14, 0x78ddbe);
    message_label = label(screen, 172, &lv_font_montserrat_14, 0xffcb75);
    lv_obj_t *help = label(screen, 246, &lv_font_montserrat_14, 0xbac8d6);
    lv_label_set_text(help, "UP: microphone\nOK: temporary / stop\nDOWN: USB / Wi-Fi");
    lv_screen_load(screen);
}
static void set_text(lv_obj_t *obj, const char *text) {
    if (strcmp(lv_label_get_text(obj), text))
        lv_label_set_text(obj, text);
}
static void button(bsp_btn_t btn, bsp_btn_ev_t event, void *user) {
    (void)user;
    input_t item = {btn, event};
    (void)xQueueSend(inputs, &item, 0);
}
static void show_message(const char *text) {
    message = text;
    message_until = esp_timer_get_time() + 3000000;
}
void app_main(void) {
    /* USB is a framed binary link. Keep ESP logs out of its byte stream. */
    esp_log_level_set("*", ESP_LOG_NONE);
    /* IDF prevents automatic sleep while a USB host is connected. */
    const esp_pm_config_t power = {
        .max_freq_mhz = 160, .min_freq_mhz = 40, .light_sleep_enable = true,
    };
    if (esp_pm_configure(&power) != ESP_OK)
        return;
    if (voice_power_restore()) {
        voice_wifi_mode = true;
        message = "Reconnecting; press OK when ready";
    }
    voice_deep_wakes = voice_power_deep_wakes();
    voice_sleep_error = voice_power_last_sleep_error();
    inputs = xQueueCreate(12, sizeof(input_t));
    if (!inputs)
        return;
    if (bsp_display_init() != ESP_OK || !bsp_lvgl_init())
        return;
    if (!bsp_lvgl_lock(1000))
        return;
    ui_create();
    bsp_lvgl_unlock();
    bsp_display_backlight(25);
    bool battery_ok = bsp_battery_init() == ESP_OK;
    esp_err_t err = nvs_flash_init(); /* Never erase NVS to hide an error. */
    if (err == ESP_OK)
        err = voice_runtime_init();
    if (err != ESP_OK) {
        voice_error = err;
        message = "Startup failed";
    }
    bool buttons_ok = bsp_button_init(button, NULL) == ESP_OK;
    if (!buttons_ok)
        message = "Buttons unavailable";
    int battery = -1;
    int64_t battery_at = -30000000;
    int64_t last_input = esp_timer_get_time();
    bool screen_off = false;
    bool wake_only = false;
    bool sleep_attempted = false;
    bool trigger_pending = false;
    int64_t temporary_started = 0;
    for (;;) {
        input_t input;
        bool received = xQueueReceive(inputs, &input, pdMS_TO_TICKS(screen_off ? 500 : 100)) == pdTRUE;
        if (received) {
            last_input = esp_timer_get_time();
            sleep_attempted = false;
        }
        if (received && voice_wifi_idle) {
            voice_wifi_idle = false;
            wake_only = true;
            show_message("Reconnecting; press OK when ready");
        }
        if (received && wake_only) {
            if (input.event == BSP_BTN_CLICK || input.event == BSP_BTN_DOUBLE || input.event == BSP_BTN_LONG)
                wake_only = false;
        } else if (received && err == ESP_OK && input.event == BSP_BTN_CLICK) {
            if (input.button == BSP_BTN_UP) {
                voice_temporary = false;
                trigger_pending = false;
                if (voice_mic) {
                    voice_mic = false;
                    show_message("Microphone off");
                } else if (!voice_bridge_ready())
                    show_message("Bridge is not ready");
                else {
                    voice_mic = true;
                    show_message("Microphone enabled");
                }
            } else if (input.button == BSP_BTN_DOWN) {
                if (voice_mic)
                    show_message("Stop microphone first");
                else {
                    voice_wifi_mode = !voice_wifi_mode;
                    show_message("Transport changed");
                }
            } else if (input.button == BSP_BTN_OK) {
                if (voice_temporary) {
                    bool sent = trigger_pending || voice_trigger(true);
                    voice_mic = false;
                    voice_temporary = false;
                    trigger_pending = false;
                    show_message(sent ? "Temporary input stopped" : "Mic off; shortcut failed");
                } else if (!voice_bridge_ready())
                    show_message("Bridge is not ready");
                else if (!voice_mic) {
                    voice_session = (voice_session + 1) & 0x7fffffffu;
                    voice_temporary = true;
                    trigger_pending = true;
                    temporary_started = esp_timer_get_time();
                    voice_mic = true;
                    show_message("Starting temporary input");
                } else if (!voice_audio)
                    show_message("Microphone is starting");
                else
                    show_message(voice_trigger(false) ? "Shortcut sent" : "Shortcut failed");
            }
        }
        int64_t now = esp_timer_get_time();
        if (voice_mic || voice_audio)
            last_input = now;
        voice_wifi_idle = voice_wifi_mode &&
            voice_should_idle_wifi(now, last_input, voice_mic, voice_audio, buttons_ok);
        if (voice_wifi_idle && screen_off && voice_codec_asleep && err == ESP_OK &&
            !usb_serial_jtag_is_connected() && !sleep_attempted) {
            sleep_attempted = true;
            esp_err_t sleep_err = voice_power_sleep();
            /* A held key or late USB insertion is a normal cancelled attempt. */
            if (sleep_err != ESP_ERR_INVALID_STATE)
                voice_error = sleep_err;
        }
        if (voice_temporary && (!voice_mic || !voice_bridge_ready())) {
            voice_mic = false;
            voice_temporary = false;
            trigger_pending = false;
            show_message("Temporary input finished");
        }
        if (trigger_pending) {
            if (voice_audio) {
                bool sent = voice_trigger(false);
                trigger_pending = false;
                if (!sent) {
                    voice_mic = false;
                    voice_temporary = false;
                }
                show_message(sent ? "Temporary input active" : "Shortcut failed");
            } else if (now - temporary_started >= 3000000 || !voice_temporary) {
                voice_mic = false;
                voice_temporary = false;
                trigger_pending = false;
                show_message("Microphone start failed");
            }
        }
        if (now - battery_at >= 30000000) {
            battery = battery_ok ? bsp_battery_soc() : -1;
            voice_battery_percent = battery;
            voice_battery_mv = battery_ok ? bsp_battery_mv() : -1;
            battery_at = now;
        }
        if (!bsp_lvgl_lock(100))
            continue;
        bool blank = voice_should_blank(now, last_input, voice_mic, voice_audio, buttons_ok);
        if (blank && !screen_off) {
            if (lvgl_port_stop() == ESP_OK && bsp_display_sleep() == ESP_OK)
                screen_off = true;
            else {
                (void)lvgl_port_resume();
                bsp_display_backlight(25);
            }
        } else if (!blank && screen_off) {
            if (bsp_display_wake() == ESP_OK && lvgl_port_resume() == ESP_OK) {
                screen_off = false;
                bsp_display_backlight(25);
                (void)lvgl_port_task_wake(LVGL_PORT_EVENT_USER, NULL);
            }
        }
        voice_screen_off = screen_off;
        if (screen_off) {
            bsp_lvgl_unlock();
            continue;
        }
        char text[128], ip[32];
        if (battery < 0)
            snprintf(text, sizeof(text), "--%%");
        else
            snprintf(text, sizeof(text), "%d%%", battery);
        set_text(battery_label, text);
        set_text(mic_label, voice_temporary ? "MIC TEMPORARY" : voice_audio ? "MIC STREAMING" : voice_mic ? "MIC WAITING" : "MIC OFF");
        snprintf(text, sizeof(text), "%s | Bridge %s", voice_wifi_mode ? "Wi-Fi" : "USB",
                 voice_bridge_ready() ? "ready" : "offline");
        set_text(link_label, text);
        if (voice_wifi_mode) {
            voice_ip(ip, sizeof(ip));
            snprintf(text, sizeof(text), "%s", ip);
        } else
            snprintf(text, sizeof(text), "USB audio bridge");
        set_text(address_label, text);
        if (voice_error)
            snprintf(text, sizeof(text), "Error: 0x%x", voice_error);
        else
            snprintf(text, sizeof(text), "%s",
                     now < message_until || !message_until ? message : "OK: temporary input");
        set_text(message_label, text);
        bsp_lvgl_unlock();
    }
}
