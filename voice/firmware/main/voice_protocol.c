#include "voice_protocol.h"
#include <string.h>
/* Discovery exposes no configuration. TCP still requires the saved token. */
size_t vp_discovery_reply(const uint8_t *data, size_t size, uint8_t *out, size_t capacity) {
    const char request[] = "PASSPORT_VOICE_DISCOVER_V1 ";
    const char response[] = "PASSPORT_VOICE_V1 ";
    size_t prefix = sizeof(request) - 1, result_size = sizeof(response) - 1 + 32;
    if (size != prefix + 32 || capacity < result_size || memcmp(data, request, prefix))
        return 0;
    for (size_t i = prefix; i < size; i++)
        if (!((data[i] >= '0' && data[i] <= '9') || (data[i] >= 'a' && data[i] <= 'f')))
            return 0;
    memcpy(out, response, sizeof(response) - 1);
    memcpy(out + sizeof(response) - 1, data + prefix, 32);
    return result_size;
}
static uint32_t crc_step(uint32_t crc, const uint8_t *p, size_t n) {
    while (n--) {
        crc ^= *p++;
        for (int i = 0; i < 8; i++)
            crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1u)));
    }
    return crc;
}
static uint32_t get32(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static void put32(uint8_t *p, uint32_t v) {
    for (int i = 0; i < 4; i++)
        p[i] = (uint8_t)(v >> (8 * i));
}
size_t vp_encode(uint8_t *out, uint8_t type, uint32_t seq, const void *data, size_t n) {
    if (n > VP_MAX_PAYLOAD)
        return 0;
    memcpy(out, "VP01", 4);
    out[4] = type;
    out[5] = 0;
    out[6] = (uint8_t)n;
    out[7] = (uint8_t)(n >> 8);
    put32(out + 8, seq);
    if (n)
        memcpy(out + VP_HEADER, data, n);
    uint32_t crc = crc_step(0xffffffffu, out, 12);
    put32(out + 12, ~crc_step(crc, out + VP_HEADER, n));
    return VP_HEADER + n;
}
void vp_feed(vp_parser_t *p, const void *bytes, size_t size, vp_handler_t cb, void *ctx) {
    const uint8_t *in = bytes;
    while (size--) {
        p->buffer[p->used++] = *in++;
        for (;;) {
            if (p->used < 4)
                break;
            if (memcmp(p->buffer, "VP01", 4)) {
                memmove(p->buffer, p->buffer + 1, --p->used);
                continue;
            }
            if (p->used < VP_HEADER)
                break;
            size_t n = p->buffer[6] | (size_t)p->buffer[7] << 8;
            if (n > VP_MAX_PAYLOAD || p->buffer[5] != 0) {
                memmove(p->buffer, p->buffer + 1, --p->used);
                continue;
            }
            if (p->used < VP_HEADER + n)
                break;
            uint32_t crc =
                ~crc_step(crc_step(0xffffffffu, p->buffer, 12), p->buffer + VP_HEADER, n);
            if (crc != get32(p->buffer + 12)) {
                memmove(p->buffer, p->buffer + 1, --p->used);
                continue;
            }
            cb(p->buffer[4], get32(p->buffer + 8), p->buffer + VP_HEADER, n, ctx);
            size_t tail = p->used - VP_HEADER - n;
            memmove(p->buffer, p->buffer + VP_HEADER + n, tail);
            p->used = tail;
        }
    }
}
