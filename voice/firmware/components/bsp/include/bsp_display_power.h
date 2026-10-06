#pragma once
#include "esp_err.h"

/* Reversible panel sleep. Stop LVGL and hold its lock before calling.
   These calls retain the SPI bus and pin routing for the next wake. */
esp_err_t bsp_display_sleep(void);
esp_err_t bsp_display_wake(void);
