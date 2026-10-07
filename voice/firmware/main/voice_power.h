#pragma once
#include "esp_err.h"
#include <stdbool.h>
#include <stdint.h>

/* Call before creating buttons. A sleep wake restores Wi-Fi and consumes the
   held wake key by waiting for release before ADC polling starts. */
bool voice_power_restore(void);
uint32_t voice_power_deep_wakes(void);
int voice_power_last_sleep_error(void);
/* Only call while idle, with the screen and codec asleep. Success does not
   return. Failures before peripheral shutdown restore the running tasks. */
esp_err_t voice_power_sleep(void);
