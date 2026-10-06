#pragma once
#include "esp_err.h"
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
extern _Atomic bool voice_mic, voice_audio, voice_wifi_mode;
extern _Atomic bool voice_temporary;
extern _Atomic bool voice_wifi_idle, voice_screen_off, voice_codec_asleep;
extern _Atomic int voice_battery_percent, voice_battery_mv;
extern _Atomic uint32_t voice_session;
extern _Atomic int voice_error;
bool voice_bridge_ready(void);
bool voice_trigger(bool ending);
uint8_t voice_modifier(void);
uint8_t voice_key(void);
void voice_ip(char *out, unsigned size);
esp_err_t voice_runtime_init(void);
