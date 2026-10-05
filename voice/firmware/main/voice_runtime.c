#include "voice_runtime.h"
#include "bsp_audio.h"
#include "cJSON.h"
#include "driver/usb_serial_jtag.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "lwip/inet.h"
#include "lwip/sockets.h"
#include "nvs.h"
#include "voice_hid.h"
#include "voice_model.h"
#include "voice_protocol.h"
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#define VOICE_PORT 8765
_Atomic bool voice_mic, voice_audio, voice_wifi_mode;
_Atomic int voice_error;
static _Atomic uint32_t ready_usb, ready_wifi;
static _Atomic uint32_t ip_address;
static _Atomic uint8_t shortcut_mod = 5, shortcut_key = 0x2c;
static _Atomic bool wifi_got_ip, wifi_wanted;
typedef struct {
    uint32_t version;
    char ssid[33], password[65], token[65];
    uint8_t modifiers, key;
} configuration_t;
static configuration_t config = {.version = 1, .modifiers = 5, .key = 0x2c};
static nvs_handle_t nvs;
static bool storage_available;
typedef struct {
    uint32_t sequence;
    int64_t captured_at;
    bool wifi;
    uint8_t pcm[VP_PCM_BYTES];
} audio_chunk_t;
static QueueHandle_t pcm_queue;
static uint32_t audio_sequence;
static uint32_t drops;
static int listener = -1, client = -1;
static bool authenticated;
static vp_parser_t usb_parser, wifi_parser;
static char result[64] = "boot";
static uint32_t ack_sequence;
static bool wifi_started;
static bool config_changed;
bool voice_bridge_ready(void) {
    uint32_t last = voice_wifi_mode ? ready_wifi : ready_usb;
    uint32_t now = (uint32_t)(esp_timer_get_time() / 1000);
    return voice_ready_fresh(now, last);
}
uint8_t voice_modifier(void) {
    return shortcut_mod;
}
uint8_t voice_key(void) {
    return shortcut_key;
}
void voice_ip(char *out, unsigned size) {
    struct in_addr addr = {.s_addr = ip_address};
    if (!addr.s_addr)
        snprintf(out, size, "Not connected");
    else
        (void)inet_ntop(AF_INET, &addr, out, size);
}
static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data) {
    (void)arg;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START && wifi_wanted)
        (void)esp_wifi_connect();
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        wifi_got_ip = false;
        ip_address = 0;
        ready_wifi = 0;
        if (wifi_wanted)
            (void)esp_wifi_connect();
    }
    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = data;
        ip_address = event->ip_info.ip.addr;
        wifi_got_ip = true;
    }
}
static void close_client(void) {
    ready_wifi = 0;
    authenticated = false;
    wifi_parser.used = 0;
    if (client >= 0) {
        close(client);
        client = -1;
    }
}
static void update_wifi(void) {
    bool wanted = voice_wifi_mode && config.ssid[0] && config.token[0];
    if (config_changed || !wanted) {
        wifi_wanted = false;
        close_client();
        if (listener >= 0) {
            close(listener);
            listener = -1;
        }
        if (wifi_started) {
            (void)esp_wifi_stop();
            wifi_started = false;
        }
        wifi_got_ip = false;
        ip_address = 0;
        config_changed = false;
    }
    if (wanted && !wifi_started) {
        wifi_config_t sta = {0};
        memcpy(sta.sta.ssid, config.ssid, strlen(config.ssid));
        memcpy(sta.sta.password, config.password, strlen(config.password));
        sta.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
        sta.sta.pmf_cfg.capable = true;
        wifi_wanted = true;
        esp_err_t err = esp_wifi_set_config(WIFI_IF_STA, &sta);
        if (err == ESP_OK)
            err = esp_wifi_start();
        wifi_started = err == ESP_OK;
        if (err != ESP_OK) {
            voice_error = err;
            wifi_wanted = false;
        }
    }
    if (wifi_got_ip && listener < 0) {
        listener = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
        if (listener < 0)
            return;
        int one = 1;
        setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
        struct sockaddr_in addr = {.sin_family = AF_INET,
                                   .sin_port = htons(VOICE_PORT),
                                   .sin_addr.s_addr = htonl(INADDR_ANY)};
        if (bind(listener, (struct sockaddr *)&addr, sizeof(addr)) < 0 || listen(listener, 1) < 0) {
            close(listener);
            listener = -1;
            return;
        }
        fcntl(listener, F_SETFL, O_NONBLOCK);
    }
    if (!wifi_got_ip && client >= 0)
        close_client();
}
static bool write_frame(bool wifi, uint8_t type, uint32_t seq, const void *data, size_t size) {
    uint8_t packet[VP_HEADER + VP_MAX_PAYLOAD];
    size_t n = vp_encode(packet, type, seq, data, size), done = 0;
    int64_t deadline = esp_timer_get_time() + 100000;
    while (done < n && esp_timer_get_time() < deadline) {
        int sent;
        if (wifi) {
            if (client < 0)
                return false;
            sent = send(client, packet + done, n - done, 0);
            if (sent < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
                vTaskDelay(pdMS_TO_TICKS(2));
                continue;
            }
        } else {
            size_t chunk = n - done;
            if (chunk > 512)
                chunk = 512;
            sent = usb_serial_jtag_write_bytes(packet + done, chunk, pdMS_TO_TICKS(20));
        }
        if (sent <= 0)
            return false;
        done += (size_t)sent;
    }
    return done == n;
}
static void status(bool wifi) {
    char json[512], ip[32];
    voice_ip(ip, sizeof(ip));
    int n = snprintf(json, sizeof(json),
                     "{\"ack\":%lu,\"result\":\"%s\",\"mic\":%s,\"audio\":%s,\"bridge\":%s,\"hid\":"
                     "%s,\"transport\":\"%s\",\"ip\":\"%s\",\"error\":%d,\"drops\":%lu,"
                     "\"modifiers\":%u,\"key\":%u,\"rate\":16000,\"channels\":1,\"bits\":16}",
                     (unsigned long)ack_sequence, result, voice_mic ? "true" : "false",
                     voice_audio ? "true" : "false", voice_bridge_ready() ? "true" : "false",
                     voice_hid_ready() ? "true" : "false", voice_wifi_mode ? "wifi" : "usb", ip,
                     voice_error, (unsigned long)drops, voice_modifier(), voice_key());
    if (n > 0 && n < (int)sizeof(json) && !write_frame(wifi, VP_STATUS, 0, json, (size_t)n)) {
        if (wifi)
            close_client();
        else
            ready_usb = 0;
    }
}
static const char *str(cJSON *obj, const char *name) {
    cJSON *item = cJSON_GetObjectItemCaseSensitive(obj, name);
    return cJSON_IsString(item) ? item->valuestring : NULL;
}
static bool copy_field(char *out, size_t cap, const char *value) {
    if (!value || strlen(value) >= cap)
        return false;
    memset(out, 0, cap);
    memcpy(out, value, strlen(value));
    return true;
}
static void command(uint8_t type, uint32_t sequence, const uint8_t *data, size_t n, void *ctx) {
    bool wifi = (uintptr_t)ctx != 0;
    if (type != VP_COMMAND || !n || n >= VP_MAX_PAYLOAD || memchr(data, 0, n) ||
        !voice_json_depth_valid(data, n))
        return;
    char json[VP_MAX_PAYLOAD];
    memcpy(json, data, n);
    json[n] = 0;
    cJSON *obj = cJSON_ParseWithOpts(json, NULL, true);
    if (!obj)
        return;
    const char *op = str(obj, "op");
    ack_sequence = sequence;
    snprintf(result, sizeof(result), "invalid command");
    if (op && !strcmp(op, "hello")) {
        const char *token = str(obj, "token");
        if (wifi)
            authenticated = token && config.token[0] && !strcmp(token, config.token);
        snprintf(result, sizeof(result), "%s",
                 !wifi || authenticated ? "ok" : "authentication failed");
    } else if (wifi && !authenticated) {
        cJSON_Delete(obj);
        return;
    } else if (op && !strcmp(op, "ready")) {
        cJSON *active = cJSON_GetObjectItemCaseSensitive(obj, "active");
        if (cJSON_IsBool(active)) {
            uint32_t now = cJSON_IsTrue(active) ? (uint32_t)(esp_timer_get_time() / 1000) : 0;
            if (wifi)
                ready_wifi = now;
            else
                ready_usb = now;
            snprintf(result, sizeof(result), "ok");
        }
    } else if (op && !strcmp(op, "configure") && !wifi && !voice_mic) {
        configuration_t next = config;
        bool valid = true;
        const char *ssid = str(obj, "ssid"), *password = str(obj, "password"),
                   *token = str(obj, "token");
        if (cJSON_HasObjectItem(obj, "ssid"))
            valid &= copy_field(next.ssid, sizeof(next.ssid), ssid);
        if (cJSON_HasObjectItem(obj, "password"))
            valid &= copy_field(next.password, sizeof(next.password), password);
        if (cJSON_HasObjectItem(obj, "token"))
            valid &=
                token && strlen(token) == 64 && copy_field(next.token, sizeof(next.token), token);
        cJSON *mod = cJSON_GetObjectItemCaseSensitive(obj, "modifiers"),
              *key = cJSON_GetObjectItemCaseSensitive(obj, "key");
        if (mod || key) {
            valid &= cJSON_IsNumber(mod) && cJSON_IsNumber(key) &&
                     mod->valuedouble == mod->valueint && key->valuedouble == key->valueint &&
                     voice_shortcut_valid(mod->valueint, key->valueint);
            if (valid) {
                next.modifiers = mod->valueint;
                next.key = key->valueint;
            }
        }
        if (next.ssid[0])
            valid &= voice_password_valid(next.password) && next.token[0];
        if (valid && storage_available) {
            esp_err_t err = ESP_OK;
            if (memcmp(&next, &config, sizeof(next))) {
                err = nvs_set_blob(nvs, "config", &next, sizeof(next));
                if (err == ESP_OK)
                    err = nvs_commit(nvs);
            }
            if (err == ESP_OK) {
                config_changed = strcmp(config.ssid, next.ssid) ||
                                 strcmp(config.password, next.password) ||
                                 strcmp(config.token, next.token);
                config = next;
                shortcut_mod = config.modifiers;
                shortcut_key = config.key;
            }
            snprintf(result, sizeof(result), "%s", err == ESP_OK ? "ok" : "storage failed");
        } else
            snprintf(result, sizeof(result), "invalid configuration");
    } else if (op && !strcmp(op, "status"))
        snprintf(result, sizeof(result), "ok");
    if (!wifi || authenticated)
        status(wifi);
    /* Return a failed authentication response without status/credentials. */
    else if (op && !strcmp(op, "hello")) {
        const char *denied = "{\"result\":\"authentication failed\"}";
        (void)write_frame(true, VP_STATUS, 0, denied, strlen(denied));
        close_client();
    }
    cJSON_Delete(obj);
}
static void transport_task(void *arg) {
    (void)arg;
    uint8_t input[256];
    audio_chunk_t chunk;
    int64_t last_status = 0, accepted_at = 0;
    for (;;) {
        int n = usb_serial_jtag_read_bytes(input, sizeof(input), 0);
        if (n > 0)
            vp_feed(&usb_parser, input, n, command, NULL);
        update_wifi();
        if (listener >= 0 && client < 0) {
            client = accept(listener, NULL, NULL);
            if (client >= 0) {
                fcntl(client, F_SETFL, O_NONBLOCK);
                accepted_at = esp_timer_get_time();
                authenticated = false;
                wifi_parser.used = 0;
            }
        }
        if (client >= 0) {
            n = recv(client, input, sizeof(input), 0);
            if (n > 0)
                vp_feed(&wifi_parser, input, n, command, (void *)1);
            else if (n == 0 || (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK))
                close_client();
            if (client >= 0 && !authenticated && esp_timer_get_time() - accepted_at > 3000000)
                close_client();
        }
        if (xQueueReceive(pcm_queue, &chunk, 0) == pdTRUE) {
            if (voice_mic && voice_bridge_ready() && chunk.wifi == voice_wifi_mode &&
                esp_timer_get_time() - chunk.captured_at < 100000) {
                bool wifi = voice_wifi_mode;
                if (!write_frame(wifi, VP_PCM, chunk.sequence, chunk.pcm, sizeof(chunk.pcm))) {
                    drops++;
                    if (wifi)
                        close_client();
                    else
                        ready_usb = 0;
                }
            }
        }
        int64_t now = esp_timer_get_time();
        if (now - last_status >= 500000) {
            if (ready_usb > 0)
                status(false);
            if (client >= 0 && authenticated)
                status(true);
            last_status = now;
        }
        vTaskDelay(pdMS_TO_TICKS(2));
    }
}
static void audio_task(void *arg) {
    (void)arg;
    bool opened = false;
    audio_chunk_t chunk;
    for (;;) {
        if (!voice_mic || !voice_bridge_ready()) {
            voice_audio = false;
            if (opened) {
                esp_err_t e = bsp_audio_sleep();
                if (e != ESP_OK)
                    voice_error = e;
                opened = false;
            }
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }
        if (!opened) {
            esp_err_t err = bsp_audio_init();
            if (err == ESP_OK)
                err = bsp_audio_set_format(16000, 16, 1);
            if (err != ESP_OK) {
                voice_error = err;
                voice_mic = false;
                continue;
            }
            opened = true;
            voice_error = 0;
        }
        esp_err_t err = bsp_audio_read(chunk.pcm, sizeof(chunk.pcm));
        if (err != ESP_OK) {
            voice_error = err;
            voice_mic = false;
            voice_audio = false;
            continue;
        }
        chunk.sequence = audio_sequence++;
        chunk.captured_at = esp_timer_get_time();
        chunk.wifi = voice_wifi_mode;
        voice_audio = true;
        if (xQueueSend(pcm_queue, &chunk, 0) != pdTRUE) { /* Drop oldest audio to bound latency. */
            audio_chunk_t old;
            (void)xQueueReceive(pcm_queue, &old, 0);
            (void)xQueueSend(pcm_queue, &chunk, 0);
        }
    }
}
esp_err_t voice_runtime_init(void) {
    storage_available = nvs_open("voice_v1", NVS_READWRITE, &nvs) == ESP_OK;
    if (storage_available) {
        configuration_t saved = {0};
        size_t size = sizeof(saved);
        if (nvs_get_blob(nvs, "config", &saved, &size) == ESP_OK && size == sizeof(saved) &&
            saved.version == 1 && memchr(saved.ssid, 0, sizeof(saved.ssid)) &&
            memchr(saved.password, 0, sizeof(saved.password)) &&
            memchr(saved.token, 0, sizeof(saved.token)) &&
            voice_shortcut_valid(saved.modifiers, saved.key))
            config = saved;
    }
    shortcut_mod = config.modifiers;
    shortcut_key = config.key;
    usb_serial_jtag_driver_config_t usb = {.tx_buffer_size = 2048, .rx_buffer_size = 2048};
    esp_err_t err = usb_serial_jtag_driver_install(&usb);
    if (err != ESP_OK)
        return err;
    err = esp_netif_init();
    if (err != ESP_OK)
        return err;
    err = esp_event_loop_create_default();
    if (err != ESP_OK)
        return err;
    if (!esp_netif_create_default_wifi_sta())
        return ESP_ERR_NO_MEM;
    wifi_init_config_t wifi = WIFI_INIT_CONFIG_DEFAULT();
    err = esp_wifi_init(&wifi);
    if (err != ESP_OK)
        return err;
    err = esp_wifi_set_storage(WIFI_STORAGE_RAM);
    if (err != ESP_OK)
        return err;
    err = esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL);
    if (err != ESP_OK)
        return err;
    err = esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL);
    if (err != ESP_OK)
        return err;
    err = esp_wifi_set_mode(WIFI_MODE_STA);
    if (err != ESP_OK)
        return err;
    pcm_queue = xQueueCreate(4, sizeof(audio_chunk_t));
    if (!pcm_queue)
        return ESP_ERR_NO_MEM;
    if (xTaskCreate(transport_task, "voice_link", 6144, NULL, 3, NULL) != pdPASS)
        return ESP_ERR_NO_MEM;
    if (xTaskCreate(audio_task, "voice_audio", 4096, NULL, 3, NULL) != pdPASS)
        return ESP_ERR_NO_MEM;
    return ESP_OK;
}
