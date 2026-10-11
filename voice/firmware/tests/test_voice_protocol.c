#include "voice_model.h"
#include "voice_protocol.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static int count;
static void accept(uint8_t type, uint32_t seq, const uint8_t *p, size_t n, void *ctx) {
    (void)ctx;
    assert(type == VP_PCM);
    assert(seq == 42);
    assert(n == 3);
    assert(!memcmp(p, "abc", 3));
    count++;
}
int main(void) {
    uint8_t frame[VP_HEADER + VP_MAX_PAYLOAD];
    vp_parser_t parser = {0};
    size_t n = vp_encode(frame, VP_PCM, 42, "abc", 3);
    assert(n == 19);
    /* Shared Python/C fixture. */
    const uint8_t expected[] = {0x56, 0x50, 0x30, 0x31, 1,    0,    3,    0,    42,  0,
                                0,    0,    0xf9, 0x72, 0xe5, 0x8d, 0x61, 0x62, 0x63};
    assert(!memcmp(frame, expected, sizeof(expected)));
    vp_feed(&parser, "boot log", 8, accept, NULL);
    for (size_t i = 0; i < n; i++)
        vp_feed(&parser, frame + i, 1, accept, NULL);
    assert(count == 1);
    frame[16] ^= 1;
    vp_feed(&parser, frame, n, accept, NULL);
    assert(count == 1);
    frame[16] ^= 1;
    vp_feed(&parser, frame, n, accept, NULL);
    assert(count == 2);
    frame[6] = 255;
    frame[7] = 255;
    vp_feed(&parser, frame, n, accept, NULL);
    n = vp_encode(frame, VP_PCM, 42, "abc", 3);
    vp_feed(&parser, frame, n, accept, NULL);
    assert(count == 3);
    assert(vp_encode(frame, 1, 0, "", VP_MAX_PAYLOAD + 1) == 0);
    assert(voice_shortcut_valid(5, 0x2c));
    assert(!voice_shortcut_valid(256, 4));
    assert(!voice_shortcut_valid(16, 4));
    assert(!voice_shortcut_valid(0, 30));
    assert(voice_shortcut_valid(15, 0x45));
    assert(!voice_shortcut_valid(0, 0x46));
    assert(!voice_shortcut_valid(0, 0));
    const uint8_t nested[] = "[[[[[[[[[0]]]]]]]]]";
    assert(!voice_json_depth_valid(nested, sizeof(nested) - 1));
    const uint8_t quoted[] = "{\"op\":\"{[test]}\"}";
    assert(voice_json_depth_valid(quoted, sizeof(quoted) - 1));
    assert(!voice_json_depth_valid((const uint8_t *)"}", 1));
    assert(voice_password_valid("test-pass"));
    assert(!voice_password_valid("short"));
    assert(
        voice_password_valid("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"));
    assert(
        !voice_password_valid("zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"));
    assert(voice_ready_fresh(14999, 1, true));
    assert(!voice_ready_fresh(15001, 1, true));
    assert(!voice_ready_fresh(1, 0, true));
    assert(voice_ready_fresh(5, 0xfffffff0u, true));
    assert(voice_ready_fresh(2999, 1, false));
    assert(!voice_ready_fresh(3001, 1, false));
    assert(!voice_ready_fresh(1, 0, false));
    assert(voice_ready_fresh(5, 0xfffffff0u, false));
    assert(!voice_should_blank(29999999, 0, false, false, true));
    assert(voice_should_blank(30000000, 0, false, false, true));
    assert(!voice_should_blank(30000000, 1, false, false, true));
    assert(!voice_should_blank(30000000, 0, true, false, true));
    assert(!voice_should_blank(30000000, 0, false, true, true));
    assert(!voice_should_blank(30000000, 0, false, false, false));
    assert(!voice_should_blank(0, 1, false, false, true));
    /* Stay online beyond the old one-minute limit, until 15 idle minutes. */
    assert(!voice_should_idle_wifi(60000000, 0, false, false, true));
    assert(!voice_should_idle_wifi(899999999, 0, false, false, true));
    assert(voice_should_idle_wifi(900000000, 0, false, false, true));
    assert(!voice_should_idle_wifi(900000000, 1, false, false, true));
    assert(!voice_should_idle_wifi(900000000, 0, true, false, true));
    assert(!voice_should_idle_wifi(900000000, 0, false, true, true));
    assert(!voice_should_idle_wifi(900000000, 0, false, false, false));
    assert(!voice_should_idle_wifi(0, 1, false, false, true));
    /* An input wake starts another full idle interval. */
    assert(!voice_should_idle_wifi(900000001, 900000000, false, false, true));
    assert(!voice_should_idle_wifi(1799999999, 900000000, false, false, true));
    assert(voice_should_idle_wifi(1800000000, 900000000, false, false, true));
    /* A restart zero remains unknown only during the settling window. */
    assert(voice_battery_soc_value(0, 0) == -1);
    assert(voice_battery_soc_value(0, 59999999) == -1);
    assert(voice_battery_soc_value(0, 60000000) == 0);
    assert(voice_battery_soc_value(0, 120000000) == 0);
    assert(voice_battery_soc_value(1, 1000000) == 1);
    assert(voice_battery_soc_value(75, 1000000) == 75);
    assert(voice_battery_soc_value(100, 1000000) == 100);
    assert(voice_battery_soc_value(-1, 120000000) == -1);
    assert(voice_battery_soc_value(101, 120000000) == -1);
    assert(voice_battery_soc_value(255, 0) == -1);
    assert(voice_battery_soc_value(75, -1) == -1);
    uint8_t discovery_request[] = "PASSPORT_VOICE_DISCOVER_V1 0123456789abcdef0123456789abcdef";
    const char discovery_expected[] = "PASSPORT_VOICE_V1 0123456789abcdef0123456789abcdef";
    uint8_t discovery_response[80];
    assert(vp_discovery_reply(discovery_request, sizeof(discovery_request) - 1,
                              discovery_response, sizeof(discovery_response)) == sizeof(discovery_expected) - 1);
    assert(!memcmp(discovery_response, discovery_expected, sizeof(discovery_expected) - 1));
    assert(!vp_discovery_reply(discovery_request, sizeof(discovery_request), discovery_response, 80));
    assert(!vp_discovery_reply(discovery_request, sizeof(discovery_request) - 1, discovery_response, 1));
    discovery_request[sizeof(discovery_request) - 2] = 'g';
    assert(!vp_discovery_reply(discovery_request, sizeof(discovery_request) - 1, discovery_response, 80));
    discovery_request[0] = '!';
    assert(!vp_discovery_reply(discovery_request, sizeof(discovery_request) - 1, discovery_response, 80));
    puts("Voice protocol, discovery, idle and battery tests: PASS");
}
