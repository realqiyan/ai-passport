#pragma once
#include "esp_err.h"
#include <stdbool.h>
#include <stdint.h>
esp_err_t voice_hid_init(void);
bool voice_hid_ready(void);
esp_err_t voice_hid_shortcut(uint8_t modifiers, uint8_t key);
int voice_hid_pairing_code(void);
void voice_hid_confirm(bool accept);
void voice_hid_clear_bonds(void);
