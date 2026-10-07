#pragma once
#include "bsp_button.h"
#include <stdint.h>

/* Run in the application task. NULL means there is no new message. */
const char *voice_controls_input(bsp_btn_t button, bsp_btn_ev_t event, int64_t now_us);
const char *voice_controls_tick(int64_t now_us);
