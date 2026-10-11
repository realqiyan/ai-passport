#include "voice_controls.h"
#include "voice_runtime.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

_Atomic bool voice_mic, voice_audio, voice_wifi_mode, voice_recording;
_Atomic bool voice_transport_auto;
_Atomic uint32_t voice_session;
static bool ready = true, shortcut_ok = true, key_ok = true;
static unsigned starts, ends, keys;
static uint8_t last_key;

bool voice_bridge_ready(void) { return ready; }
bool voice_trigger(bool ending) {
    if (ending)
        ends++;
    else
        starts++;
    return shortcut_ok;
}
bool voice_send_key(uint8_t key) {
    keys++;
    last_key = key;
    return key_ok;
}

static void start(int64_t now) {
    assert(voice_controls_input(BSP_BTN_UP, BSP_BTN_CLICK, now));
    assert(voice_mic && voice_recording);
}

int main(void) {
    assert(!voice_mic && !voice_recording);
    /* Keyboard keys work while the microphone stays off. */
    const bsp_btn_t buttons[] = {BSP_BTN_OK, BSP_BTN_DOWN, BSP_BTN_UP, BSP_BTN_DOWN};
    const bsp_btn_ev_t events[] = {BSP_BTN_CLICK, BSP_BTN_CLICK, BSP_BTN_LONG, BSP_BTN_LONG};
    const uint8_t codes[] = {0x28, 0x2a, 0x52, 0x51};
    for (unsigned i = 0; i < 4; i++) {
        assert(voice_controls_input(buttons[i], events[i], 0));
        assert(last_key == codes[i] && keys == i + 1);
        assert(!voice_mic && !voice_recording && !voice_wifi_mode);
    }
    assert(!starts && !ends);
    /* A long press must not also perform the short action. */
    voice_transport_auto = true;
    assert(voice_controls_input(BSP_BTN_OK, BSP_BTN_LONG, 0));
    assert(voice_wifi_mode && keys == 4 && !voice_transport_auto);
    assert(!voice_controls_input(BSP_BTN_UP, BSP_BTN_PRESS, 0));
    assert(!voice_controls_input(BSP_BTN_DOWN, BSP_BTN_DOUBLE, 0));
    assert(!voice_mic && keys == 4);
    /* Start only after audio is ready; stop sends the same recording shortcut. */
    start(100);
    assert(voice_session == 1 && !starts);
    assert(!voice_controls_tick(200));
    voice_audio = true;
    assert(voice_controls_tick(300));
    assert(starts == 1);
    assert(!voice_controls_tick(400));
    assert(!strcmp(voice_controls_input(BSP_BTN_OK, BSP_BTN_LONG, 500), "Stop microphone first"));
    assert(voice_wifi_mode);
    for (unsigned i = 0; i < 4; i++) {
        assert(voice_controls_input(buttons[i], events[i], 600));
        assert(voice_mic && voice_recording);
    }
    assert(starts == 1 && !ends);
    assert(voice_controls_input(BSP_BTN_UP, BSP_BTN_CLICK, 700));
    assert(!voice_mic && !voice_recording && ends == 1);
    assert(!strcmp(voice_controls_input(BSP_BTN_OK, BSP_BTN_LONG, 800), "Stop microphone first"));
    voice_audio = false;
    assert(voice_controls_input(BSP_BTN_OK, BSP_BTN_LONG, 900));
    assert(!voice_wifi_mode);
    /* Cancelling before audio is ready must not start dictation later. */
    start(1000);
    assert(voice_controls_input(BSP_BTN_UP, BSP_BTN_CLICK, 1100));
    voice_audio = true;
    assert(!voice_controls_tick(1200));
    assert(!voice_mic && starts == 1 && ends == 1);
    voice_audio = false;
    /* Audio startup timeout closes the microphone at the boundary. */
    start(2000);
    assert(!voice_controls_tick(3001999));
    assert(voice_controls_tick(3002000));
    assert(!voice_mic && !voice_recording);
    /* A failed start or end request leaves the microphone off. */
    shortcut_ok = false;
    start(4000000);
    voice_audio = true;
    assert(voice_controls_tick(4000001));
    assert(!voice_mic && !voice_recording);
    shortcut_ok = true;
    start(5000000);
    assert(voice_controls_tick(5000001));
    shortcut_ok = false;
    assert(voice_controls_input(BSP_BTN_UP, BSP_BTN_CLICK, 5000002));
    assert(!voice_mic && !voice_recording);
    voice_audio = false;
    /* A disconnect closes recording and blocks all host keys. */
    start(6000000);
    ready = false;
    assert(voice_controls_tick(6000001));
    assert(!voice_mic && !voice_recording);
    unsigned previous_keys = keys;
    for (unsigned i = 0; i < 4; i++)
        assert(!strcmp(voice_controls_input(buttons[i], events[i], 6000002), "Bridge is not ready"));
    assert(keys == previous_keys);
    assert(voice_controls_input(BSP_BTN_UP, BSP_BTN_CLICK, 6000003));
    assert(!voice_mic);
    /* Transport selection stays available without a bridge. */
    assert(voice_controls_input(BSP_BTN_OK, BSP_BTN_LONG, 6000004));
    assert(voice_wifi_mode);
    ready = true;
    key_ok = false;
    assert(!strcmp(voice_controls_input(BSP_BTN_OK, BSP_BTN_CLICK, 6000005), "Key request failed"));
    assert(!voice_mic);
    puts("Voice controls and microphone lifecycle tests: PASS");
}
