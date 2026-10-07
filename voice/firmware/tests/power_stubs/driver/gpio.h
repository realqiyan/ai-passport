#pragma once
#include "voice_sleep_test_stubs.h"
typedef struct { uint64_t pin_bit_mask; int mode, pull_up_en, pull_down_en, intr_type; } gpio_config_t;
#define GPIO_MODE_INPUT 1
#define GPIO_MODE_DISABLE 0
#define GPIO_PULLUP_DISABLE 0
#define GPIO_PULLDOWN_DISABLE 0
#define GPIO_INTR_DISABLE 0
esp_err_t gpio_config(const gpio_config_t *config);
esp_err_t gpio_hold_dis(int pin);
esp_err_t gpio_set_direction(int pin, int mode);
int gpio_get_level(int pin);
