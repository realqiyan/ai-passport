#include "bsp_display_power.h"
#include "bsp_display.h"
#include "esp_lcd_panel_ops.h"

esp_err_t bsp_display_sleep(void) {
    esp_lcd_panel_handle_t panel = bsp_display_panel();
    if (!panel)
        return ESP_ERR_INVALID_STATE;
    bsp_display_backlight(0);
    esp_err_t err = esp_lcd_panel_disp_on_off(panel, false);
    if (err == ESP_OK)
        err = esp_lcd_panel_disp_sleep(panel, true);
    if (err != ESP_OK) {
        (void)esp_lcd_panel_disp_sleep(panel, false);
        (void)esp_lcd_panel_disp_on_off(panel, true);
    }
    return err;
}

esp_err_t bsp_display_wake(void) {
    esp_lcd_panel_handle_t panel = bsp_display_panel();
    if (!panel)
        return ESP_ERR_INVALID_STATE;
    esp_err_t err = esp_lcd_panel_disp_sleep(panel, false);
    if (err == ESP_OK)
        err = esp_lcd_panel_disp_on_off(panel, true);
    return err;
}
