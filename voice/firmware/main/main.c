#include "bsp_battery.h"
#include "bsp_button.h"
#include "bsp_display.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "lvgl.h"
#include "nvs_flash.h"
#include "voice_hid.h"
#include "voice_model.h"
#include "voice_runtime.h"
#include <stdio.h>
#include <string.h>
typedef struct {
    bsp_btn_t button;
    bsp_btn_ev_t event;
} input_t;
static QueueHandle_t inputs;
static lv_obj_t *battery_label, *mic_label, *link_label, *hid_label, *message_label, *address_label;
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
    hid_label = label(screen, 137, &lv_font_montserrat_14, 0xbac8d6);
    address_label = label(screen, 165, &lv_font_montserrat_14, 0x78ddbe);
    message_label = label(screen, 198, &lv_font_montserrat_14, 0xffcb75);
    lv_obj_t *help = label(screen, 246, &lv_font_montserrat_14, 0xbac8d6);
    lv_label_set_text(help, "UP: microphone\nOK: shortcut\nDOWN: USB / Wi-Fi");
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
    if (err == ESP_OK)
        err = voice_hid_init();
    if (err != ESP_OK) {
        voice_error = err;
        message = "Startup failed";
    }
    bool buttons_ok = bsp_button_init(button, NULL) == ESP_OK;
    if (!buttons_ok)
        message = "Buttons unavailable";
    int battery = -1;
    int64_t battery_at = -30000000;
    for (;;) {
        input_t input;
        if (xQueueReceive(inputs, &input, pdMS_TO_TICKS(50)) == pdTRUE && err == ESP_OK) {
            int pairing = voice_hid_pairing_code();
            if (pairing >= 0) {
                if (input.event == BSP_BTN_CLICK && input.button == BSP_BTN_OK)
                    voice_hid_confirm(true);
                if (input.event == BSP_BTN_CLICK && input.button == BSP_BTN_DOWN)
                    voice_hid_confirm(false);
            } else if (input.event == BSP_BTN_CLICK) {
                if (input.button == BSP_BTN_UP) {
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
                    if (!voice_can_trigger(voice_mic && voice_audio, voice_bridge_ready(),
                                           voice_hid_ready()))
                        show_message("Need mic, bridge, BLE");
                    else
                        show_message(voice_hid_shortcut(voice_modifier(), voice_key()) == ESP_OK
                                         ? "Shortcut sent"
                                         : "Shortcut failed");
                }
            } else if (input.event == BSP_BTN_LONG && input.button == BSP_BTN_OK && !voice_mic) {
                voice_hid_clear_bonds();
                show_message("Pairing cleared");
            }
        }
        int64_t now = esp_timer_get_time();
        if (now - battery_at >= 30000000) {
            battery = battery_ok ? bsp_battery_soc() : -1;
            battery_at = now;
        }
        if (!bsp_lvgl_lock(100))
            continue;
        char text[128], ip[32];
        if (battery < 0)
            snprintf(text, sizeof(text), "--%%");
        else
            snprintf(text, sizeof(text), "%d%%", battery);
        set_text(battery_label, text);
        set_text(mic_label, voice_audio ? "MIC STREAMING" : voice_mic ? "MIC WAITING" : "MIC OFF");
        snprintf(text, sizeof(text), "%s | Bridge %s", voice_wifi_mode ? "Wi-Fi" : "USB",
                 voice_bridge_ready() ? "ready" : "offline");
        set_text(link_label, text);
        set_text(hid_label, voice_hid_ready() ? "Bluetooth keyboard ready" : "Pair Passport Voice");
        if (voice_wifi_mode) {
            voice_ip(ip, sizeof(ip));
            snprintf(text, sizeof(text), "%s", ip);
        } else
            snprintf(text, sizeof(text), "USB audio bridge");
        set_text(address_label, text);
        int pairing = voice_hid_pairing_code();
        if (pairing >= 0)
            snprintf(text, sizeof(text), "Compare %06d\nOK: yes / DOWN: no", pairing);
        else if (voice_error)
            snprintf(text, sizeof(text), "Error: 0x%x", voice_error);
        else
            snprintf(text, sizeof(text), "%s",
                     now < message_until || !message_until ? message : "OK sends shortcut");
        set_text(message_label, text);
        bsp_lvgl_unlock();
    }
}
