#include "clock_model.h"
#include "bsp_battery.h"
#include "bsp_button.h"
#include "bsp_display.h"
#include "esp_log.h"
#include "esp_pm.h"
#include "esp_lvgl_port.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "lvgl.h"
#include "nvs.h"
#include "nvs_flash.h"
#include <stdio.h>
#include <stdarg.h>
#include <string.h>

#define BATTERY_INTERVAL_US INT64_C(30000000)

LV_FONT_DECLARE(clock_font_16);

static const char *TAG = "clock";
static QueueHandle_t input_queue;
static clock_model_t clock_state;
static nvs_handle_t settings;
static bool storage_ok;
static bool battery_ok;
static bool buttons_ok;
static esp_pm_lock_handle_t screen_lock;
static bool save_failed;
static lv_obj_t *time_label, *seconds_label, *date_label, *status_label;
static lv_obj_t *battery_label, *format_label, *edit_label, *help_label;
static lv_obj_t *second_bar;

typedef struct { bsp_btn_t button; bsp_btn_ev_t event; } input_t;

static lv_obj_t *label(lv_obj_t *parent, int y, const lv_font_t *font, uint32_t color)
{
    lv_obj_t *obj = lv_label_create(parent);
    lv_obj_set_width(obj, 216);
    lv_obj_set_style_text_font(obj, font, 0);
    lv_obj_set_style_text_color(obj, lv_color_hex(color), 0);
    lv_obj_set_style_text_align(obj, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(obj, LV_ALIGN_TOP_MID, 0, y);
    return obj;
}

static void build_ui(void)
{
    lv_obj_t *screen = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(screen, lv_color_hex(0x101923), 0);
    lv_obj_set_style_pad_all(screen, 0, 0);
    lv_obj_remove_flag(screen, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_t *title = label(screen, 20, &clock_font_16, 0x7DE2C6);
    lv_label_set_text(title, "时钟");
    lv_obj_set_width(title, 80);
    lv_obj_align(title, LV_ALIGN_TOP_LEFT, 18, 20);
    battery_label = label(screen, 20, &lv_font_montserrat_14, 0xB8C6D4);
    lv_obj_set_width(battery_label, 70);
    lv_obj_align(battery_label, LV_ALIGN_TOP_RIGHT, -18, 20);
    status_label = label(screen, 55, &clock_font_16, 0xFFCA72);
    time_label = label(screen, 89, &lv_font_montserrat_48, 0xF2F6FA);
    seconds_label = label(screen, 150, &lv_font_montserrat_20, 0x7DE2C6);
    format_label = label(screen, 179, &lv_font_montserrat_14, 0xB8C6D4);
    date_label = label(screen, 205, &lv_font_montserrat_20, 0xF2F6FA);
    edit_label = label(screen, 232, &clock_font_16, 0x7DE2C6);
    second_bar = lv_bar_create(screen);
    lv_obj_set_size(second_bar, 190, 3);
    lv_obj_align(second_bar, LV_ALIGN_TOP_MID, 0, 260);
    lv_bar_set_range(second_bar, 0, 59);
    lv_obj_set_style_bg_color(second_bar, lv_color_hex(0x283645), LV_PART_MAIN);
    lv_obj_set_style_bg_color(second_bar, lv_color_hex(0x7DE2C6), LV_PART_INDICATOR);
    help_label = label(screen, 274, &clock_font_16, 0xB8C6D4);
    lv_label_set_text(help_label, "长按确定设置时间");
    lv_screen_load(screen);
}

/* Call with the LVGL lock held. Unchanged labels do not invalidate the screen. */
static void set_text(lv_obj_t *obj, const char *fmt, ...)
{
    char text[128];
    va_list args;
    va_start(args, fmt);
    vsnprintf(text, sizeof(text), fmt, args);
    va_end(args);
    if (strcmp(lv_label_get_text(obj), text) != 0) lv_label_set_text(obj, text);
}

static void render(int battery)
{
    static const char *weekdays[] = {"SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"};
    static const char *fields[] = {"年", "月", "日", "时", "分"};
    clock_date_t d = clock_state.editing ? clock_state.draft : clock_decode(clock_state.seconds);
    set_text(time_label, "%02d:%02d", clock_display_hour(d.hour, clock_state.twelve_hour), d.minute);
    set_text(seconds_label, "%02d", d.second);
    set_text(date_label, "%04d-%02d-%02d", d.year, d.month, d.day);
    set_text(format_label, "%s  /  %s", weekdays[clock_weekday(clock_encode(d))],
        clock_state.twelve_hour ? (d.hour < 12 ? "AM" : "PM") : "24H");
    if (battery >= 0) set_text(battery_label, "%d%%", battery);
    else set_text(battery_label, "--%");
    set_text(status_label, save_failed ? "保存失败" :
        (!storage_ok ? "存储不可用" : (clock_state.confirmed ? "离线时钟" : "请设置时间")));
    if (clock_state.editing) {
        set_text(edit_label, "设置：%s", fields[clock_state.field]);
        set_text(help_label, "上加 下减 确定下一项\n长按确定取消");
    } else {
        set_text(edit_label, "亮度 %u%%", clock_state.brightness);
        set_text(help_label, "上键制式 下键亮度\n长按确定设置时间");
    }
    if (lv_bar_get_value(second_bar) != d.second) lv_bar_set_value(second_bar, d.second, LV_ANIM_OFF);
}

static void save_settings(void)
{
    if (!storage_ok) { save_failed = true; return; }
    esp_err_t err = nvs_set_u8(settings, "format", clock_state.twelve_hour);
    if (err == ESP_OK) err = nvs_set_u8(settings, "brightness", (uint8_t)clock_state.brightness);
    if (err == ESP_OK) err = nvs_commit(settings);
    save_failed = err != ESP_OK;
    if (save_failed) ESP_LOGE(TAG, "Settings save failed: %s", esp_err_to_name(err));
}

static void save_time(void)
{
    if (!storage_ok) { save_failed = true; return; }
    esp_err_t err = nvs_set_i64(settings, "time", clock_state.seconds);
    if (err == ESP_OK) err = nvs_commit(settings);
    save_failed = err != ESP_OK;
    if (save_failed) ESP_LOGE(TAG, "Time save failed: %s", esp_err_to_name(err));
}

static void process_input(input_t input, int64_t now_us)
{
    if (input.button == BSP_BTN_OK && input.event == BSP_BTN_LONG) {
        if (clock_state.editing) clock_edit_cancel(&clock_state);
        else clock_edit_begin(&clock_state);
        return;
    }
    if (input.event != BSP_BTN_CLICK) return;
    if (clock_state.editing) {
        if (input.button == BSP_BTN_UP) clock_edit_adjust(&clock_state, 1);
        else if (input.button == BSP_BTN_DOWN) clock_edit_adjust(&clock_state, -1);
        else if (clock_edit_next(&clock_state, now_us)) save_time();
    } else if (input.button == BSP_BTN_UP) {
        clock_state.twelve_hour = !clock_state.twelve_hour;
        save_settings();
    } else if (input.button == BSP_BTN_DOWN) {
        clock_state.brightness = clock_state.brightness == 80 ? 25 : clock_state.brightness == 25 ? 50 : 80;
        bsp_display_backlight((uint8_t)clock_state.brightness);
        save_settings();
    }
}

/* The shared button timer callback only queues bounded work. */
static void on_button(bsp_btn_t button, bsp_btn_ev_t event, void *user)
{
    (void)user;
    if (event != BSP_BTN_PRESS && event != BSP_BTN_CLICK && event != BSP_BTN_LONG) return;
    input_t input = {button, event};
    (void)xQueueSend(input_queue, &input, 0);
}

/* Keep Light-sleep disabled while PWM is visible. DFS remains enabled. */
static void power_init(void)
{
    esp_err_t err = esp_pm_lock_create(ESP_PM_NO_LIGHT_SLEEP, 0, "clock_screen", &screen_lock);
    if (err == ESP_OK) err = esp_pm_lock_acquire(screen_lock);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Screen power lock failed: %s", esp_err_to_name(err));
        if (screen_lock) { esp_pm_lock_delete(screen_lock); screen_lock = NULL; }
    }
    const esp_pm_config_t config = {
        .max_freq_mhz = 80,
        .min_freq_mhz = 40,
        .light_sleep_enable = screen_lock != NULL,
    };
    err = esp_pm_configure(&config);
    if (err != ESP_OK) ESP_LOGE(TAG, "Power configuration failed: %s", esp_err_to_name(err));
    else ESP_LOGI(TAG, "Power: 40-80 MHz; automatic Light-sleep %s", screen_lock ? "enabled when screen off" : "disabled");
}

/* Only the clock task owns screen and PM transitions; never call from callbacks. */
static bool screen_set_awake(bool awake, int battery)
{
    if (!bsp_lvgl_lock(100)) return false;
    esp_err_t err;
    if (awake) {
        if (screen_lock) ESP_ERROR_CHECK(esp_pm_lock_acquire(screen_lock));
        err = lvgl_port_resume();
        if (err == ESP_OK) {
            render(battery);
            (void)lvgl_port_task_wake(LVGL_PORT_EVENT_USER, NULL);
            bsp_display_backlight((uint8_t)clock_state.brightness);
        } else {
            (void)lvgl_port_stop();
            if (screen_lock) ESP_ERROR_CHECK(esp_pm_lock_release(screen_lock));
        }
    } else {
        bsp_display_backlight(0);
        err = lvgl_port_stop();
        if (err == ESP_OK) {
            if (screen_lock) ESP_ERROR_CHECK(esp_pm_lock_release(screen_lock));
        } else {
            (void)lvgl_port_resume();
            bsp_display_backlight((uint8_t)clock_state.brightness);
        }
    }
    bsp_lvgl_unlock();
    if (err != ESP_OK) ESP_LOGE(TAG, "Screen transition failed: %s", esp_err_to_name(err));
    else ESP_LOGI(TAG, "Screen %s", awake ? "on" : "off");
    return err == ESP_OK;
}

static void clock_task(void *arg)
{
    (void)arg;
    int battery = -1;
    int64_t battery_due = 0;
    for (;;) {
        int64_t now = esp_timer_get_time();
        if (!buttons_ok) clock_state.last_input_us = now;
        int64_t wait_us = clock_wait_us(&clock_state, now);
        if (battery_ok && battery_due - now < wait_us) wait_us = battery_due - now;
        uint32_t wait_ms = wait_us > 0 ? (uint32_t)((wait_us + 999) / 1000) : 1;
        TickType_t wait_ticks = pdMS_TO_TICKS(wait_ms);
        input_t input;
        bool received = xQueueReceive(input_queue, &input, wait_ticks ? wait_ticks : 1) == pdTRUE;
        now = esp_timer_get_time();
        clock_tick(&clock_state, now);
        if (received) {
            bool was_off = clock_state.screen_off;
            bool action = clock_input(&clock_state, (unsigned)input.button,
                                      input.event == BSP_BTN_PRESS, now);
            if (was_off && !screen_set_awake(true, battery)) clock_state.screen_off = true;
            if (action) process_input(input, now);
        }
        if (battery_ok && now >= battery_due) {
            battery = bsp_battery_soc();
            battery_due = now + BATTERY_INTERVAL_US;
        }
        if (buttons_ok && clock_should_blank(&clock_state, now)) {
            if (screen_set_awake(false, battery)) clock_state.screen_off = true;
            else clock_state.last_input_us = now; /* Retry later; avoid a busy loop. */
        }
        if (!clock_state.screen_off && bsp_lvgl_lock(100)) {
            render(battery);
            bsp_lvgl_unlock();
        }
    }
}

static bool check_font(void)
{
    /* Every fixed Chinese glyph must exist in the pinned font. */
    static const uint32_t glyphs[] = {
        0x65F6,0x949F,0x4FDD,0x5B58,0x5931,0x8D25,0x5B58,0x50A8,0x4E0D,0x53EF,0x7528,
        0x79BB,0x7EBF,0x8BF7,0x8BBE,0x7F6E,0x95F4,0x5E74,0x6708,0x65E5,0x5206,0xFF1A,
        0x4E0A,0x52A0,0x4E0B,0x51CF,0x786E,0x5B9A,0x4E00,0x9879,0x957F,0x6309,0x53D6,
        0x6D88,0x4EAE,0x5EA6,0x952E,0x5236,0x5F0F
    };
    for (size_t i = 0; i < sizeof(glyphs) / sizeof(glyphs[0]); i++) {
        lv_font_glyph_dsc_t glyph = {0};
        if (!lv_font_get_glyph_dsc(&clock_font_16, &glyph, glyphs[i], 0) || glyph.is_placeholder) {
            ESP_LOGE(TAG, "Missing Chinese glyph U+%04lx", (unsigned long)glyphs[i]);
            return false;
        }
    }
    return true;
}

void app_main(void)
{
    int64_t saved = clock_encode((clock_date_t){2026,1,1,0,0,0});
    esp_err_t err = nvs_flash_init();
    /* Preserve existing NVS on failure; do not erase another application's data. */
    if (err == ESP_OK) err = nvs_open("clock_v1", NVS_READWRITE, &settings);
    storage_ok = err == ESP_OK;
    if (!storage_ok) ESP_LOGW(TAG, "NVS unavailable: %s", esp_err_to_name(err));
    if (storage_ok) (void)nvs_get_i64(settings, "time", &saved);
    clock_init(&clock_state, saved, esp_timer_get_time());
    if (storage_ok) {
        uint8_t value;
        if (nvs_get_u8(settings, "format", &value) == ESP_OK && value <= 1) clock_state.twelve_hour = value;
        if (nvs_get_u8(settings, "brightness", &value) == ESP_OK && (value == 25 || value == 50 || value == 80)) clock_state.brightness = value;
    }
    power_init();
    battery_ok = bsp_battery_init() == ESP_OK;
    if (bsp_display_init() != ESP_OK || !bsp_lvgl_init()) {
        ESP_LOGE(TAG, "Display initialization failed");
        return;
    }
    if (!bsp_lvgl_lock(1000)) { ESP_LOGE(TAG, "LVGL lock failed"); return; }
    bool font_ok = check_font();
    if (font_ok) { build_ui(); render(-1); }
    bsp_lvgl_unlock();
    if (!font_ok) return;
    bsp_display_backlight((uint8_t)clock_state.brightness);
    input_queue = xQueueCreate(16, sizeof(input_t));
    if (!input_queue) { ESP_LOGE(TAG, "Input queue allocation failed"); return; }
    err = bsp_button_init(on_button, NULL);
    buttons_ok = err == ESP_OK;
    if (!buttons_ok) ESP_LOGE(TAG, "Buttons unavailable; idle screen-off disabled: %s", esp_err_to_name(err));
    if (xTaskCreate(clock_task, "clock", 4096, NULL, 4, NULL) != pdPASS) {
        ESP_LOGE(TAG, "Clock task allocation failed");
        return;
    }
    ESP_LOGI(TAG, "Clock ready; confirm time after every restart");
}
