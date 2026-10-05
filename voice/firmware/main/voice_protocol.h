#pragma once
#include <stddef.h>
#include <stdint.h>
#define VP_MAX_PAYLOAD 1024
#define VP_HEADER 16
#define VP_PCM 1
#define VP_COMMAND 2
#define VP_STATUS 3
#define VP_SAMPLES 320
#define VP_PCM_BYTES (VP_SAMPLES * 2)
typedef void (*vp_handler_t)(uint8_t type, uint32_t sequence, const uint8_t *data, size_t size,
                             void *ctx);
typedef struct {
    uint8_t buffer[VP_HEADER + VP_MAX_PAYLOAD];
    size_t used;
} vp_parser_t;
size_t vp_encode(uint8_t *out, uint8_t type, uint32_t sequence, const void *data, size_t size);
void vp_feed(vp_parser_t *parser, const void *data, size_t size, vp_handler_t handler, void *ctx);
size_t vp_discovery_reply(const uint8_t *data, size_t size, uint8_t *out, size_t capacity);
