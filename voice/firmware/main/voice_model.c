#include "voice_model.h"
bool voice_shortcut_valid(int modifiers, int key) {
    return modifiers >= 0 && modifiers <= 15 &&
           ((key >= 4 && key <= 29) || key == 0x28 || key == 0x29 ||
            key == 0x2b || key == 0x2c || (key >= 0x3a && key <= 0x45));
}

bool voice_json_depth_valid(const uint8_t *data, size_t size) {
    unsigned depth = 0;
    bool quoted = false, escaped = false;
    for (size_t i = 0; i < size; i++) {
        uint8_t ch = data[i];
        if (quoted) {
            if (escaped)
                escaped = false;
            else if (ch == '\\')
                escaped = true;
            else if (ch == '"')
                quoted = false;
        } else if (ch == '"')
            quoted = true;
        else if (ch == '{' || ch == '[') {
            if (++depth > 8)
                return false;
        } else if (ch == '}' || ch == ']') {
            if (!depth)
                return false;
            depth--;
        }
    }
    return depth == 0 && !quoted;
}
bool voice_password_valid(const char *password) {
    size_t size = 0;
    while (password[size])
        size++;
    if (size < 8 || size > 64)
        return false;
    if (size < 64)
        return true;
    for (size_t i = 0; i < size; i++) {
        char ch = password[i];
        if (!((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f') || (ch >= 'A' && ch <= 'F')))
            return false;
    }
    return true;
}

bool voice_ready_fresh(uint32_t now_ms, uint32_t last_ms) {
    return last_ms != 0 && (uint32_t)(now_ms - last_ms) < 3000;
}

bool voice_should_blank(int64_t now_us, int64_t last_input_us,
                        bool mic, bool audio, bool buttons_ok) {
    return buttons_ok && !mic && !audio && now_us >= last_input_us &&
           now_us - last_input_us >= INT64_C(30000000);
}

bool voice_should_idle_wifi(int64_t now_us, int64_t last_input_us,
                            bool mic, bool audio, bool buttons_ok) {
    return buttons_ok && !mic && !audio && now_us >= last_input_us &&
           now_us - last_input_us >= INT64_C(60000000);
}
