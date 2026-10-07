#pragma once
#include "demo_test_stubs.h"
#define ESP_SLEEP_WAKEUP_ALL 0
#define ESP_SLEEP_WAKEUP_GPIO 7
#define ESP_GPIO_WAKEUP_GPIO_LOW 0
#define ESP_RST_DEEPSLEEP 8
int esp_reset_reason(void);
esp_err_t esp_deep_sleep_enable_gpio_wakeup(uint64_t mask, int mode);
esp_err_t esp_sleep_enable_wifi_wakeup(void);
esp_err_t adc_oneshot_channel_to_io(int unit, int channel, int *pin);
int bsp_button_read_mv(void);
