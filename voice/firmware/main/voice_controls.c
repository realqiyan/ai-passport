#include "voice_controls.h"
#include "voice_runtime.h"
#include <stddef.h>

static bool trigger_pending;
static int64_t recording_started;

const char *voice_controls_input(bsp_btn_t button, bsp_btn_ev_t event, int64_t now_us) {
    if (event != BSP_BTN_CLICK && event != BSP_BTN_LONG)
        return NULL;
    if (button == BSP_BTN_OK && event == BSP_BTN_LONG) {
        if (voice_mic || voice_audio)
            return "Stop microphone first";
        voice_wifi_mode = !voice_wifi_mode;
        return "Transport changed";
    }
    if (button == BSP_BTN_UP && event == BSP_BTN_CLICK) {
        if (voice_recording) {
            bool sent = trigger_pending || voice_trigger(true);
            voice_mic = false;
            voice_recording = false;
            trigger_pending = false;
            return sent ? "Input stopped; OK: Enter" : "Mic off; shortcut failed";
        }
        if (!voice_bridge_ready())
            return "Bridge is not ready";
        voice_session = (voice_session + 1) & 0x7fffffffu;
        voice_recording = true;
        trigger_pending = true;
        recording_started = now_us;
        voice_mic = true;
        return "Starting voice input";
    }
    uint8_t key;
    const char *message;
    if (button == BSP_BTN_UP) {
        key = 0x52;
        message = "Up key queued";
    } else if (button == BSP_BTN_DOWN) {
        key = event == BSP_BTN_LONG ? 0x51 : 0x2a;
        message = event == BSP_BTN_LONG ? "Down key queued" : "Backspace queued";
    } else if (button == BSP_BTN_OK) {
        key = 0x28;
        message = "Enter queued";
    } else
        return NULL;
    if (!voice_bridge_ready())
        return "Bridge is not ready";
    return voice_send_key(key) ? message : "Key request failed";
}

const char *voice_controls_tick(int64_t now_us) {
    if (voice_recording && (!voice_mic || !voice_bridge_ready())) {
        voice_mic = false;
        voice_recording = false;
        trigger_pending = false;
        return "Voice input finished";
    }
    if (!trigger_pending)
        return NULL;
    if (voice_audio) {
        bool sent = voice_trigger(false);
        trigger_pending = false;
        if (!sent) {
            voice_mic = false;
            voice_recording = false;
        }
        return sent ? "Voice input active" : "Shortcut failed";
    }
    if (now_us - recording_started >= 3000000 || !voice_recording) {
        voice_mic = false;
        voice_recording = false;
        trigger_pending = false;
        return "Microphone start failed";
    }
    return NULL;
}
