#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
bool voice_shortcut_valid(int modifiers, int key);
bool voice_json_depth_valid(const uint8_t *data, size_t size);
bool voice_password_valid(const char *password);
bool voice_ready_fresh(uint32_t now_ms, uint32_t last_ms, bool idle);
bool voice_should_blank(int64_t now_us, int64_t last_input_us,
                        bool mic, bool audio, bool buttons_ok);
bool voice_should_idle_wifi(int64_t now_us, int64_t last_input_us,
                            bool mic, bool audio, bool buttons_ok);
bool voice_button_event_acts(bool *waiting, bool screen_off, bool action_event);
int voice_battery_soc_value(int soc, int64_t elapsed_us);
