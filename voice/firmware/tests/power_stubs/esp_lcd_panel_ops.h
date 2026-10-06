#pragma once
#include "esp_err.h"
#include "esp_lcd_types.h"
#include <stdbool.h>
esp_err_t esp_lcd_panel_disp_on_off(esp_lcd_panel_handle_t panel, bool on);
esp_err_t esp_lcd_panel_disp_sleep(esp_lcd_panel_handle_t panel, bool sleep);
