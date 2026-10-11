#include "voice_runtime.h"
#include "bsp_audio.h"
#include "bsp_battery.h"
#include "cJSON.h"
#include "driver/usb_serial_jtag.h"
#include "esp_event.h"
#include "esp_attr.h"
#include "esp_system.h"
#include "esp_log.h"
#include "esp_pm.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "lwip/inet.h"
#include "lwip/sockets.h"
#include "nvs.h"
#include "voice_model.h"
#include "voice_protocol.h"
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#define VOICE_PORT 8765
_Atomic bool voice_mic, voice_audio, voice_wifi_mode;
_Atomic bool voice_transport_auto = true;
_Atomic bool voice_recording;
_Atomic bool voice_wifi_idle, voice_screen_off, voice_codec_asleep;
_Atomic int voice_battery_percent = -1, voice_battery_mv = -1;
_Atomic uint32_t voice_session;
_Atomic uint32_t voice_deep_wakes;
_Atomic int voice_sleep_error;
_Atomic int voice_error;
static _Atomic uint32_t ready_usb, ready_wifi;
static _Atomic uint32_t ip_address;
static _Atomic uint8_t shortcut_mod = 3, shortcut_key = 0x19;
static _Atomic bool wifi_got_ip, wifi_wanted;
typedef struct {
    uint32_t version;
    char ssid[33], password[65], token[65];
    uint8_t modifiers, key;
} configuration_t;
static configuration_t config = {.version = 1, .modifiers = 3, .key = 0x19};
static nvs_handle_t nvs;
static bool storage_available;
typedef struct {
    uint32_t sequence;
    int64_t captured_at;
    bool wifi;
    uint8_t pcm[VP_PCM_BYTES];
} audio_chunk_t;
static QueueHandle_t pcm_queue, shortcut_queue;
static esp_pm_lock_handle_t audio_power_lock;
static TaskHandle_t transport_worker, audio_worker, battery_worker;
static _Atomic bool sleep_requested, transport_paused, audio_paused, battery_paused;
static _Atomic int transport_sleep_error;
typedef struct {
    int64_t requested_at;
    bool wifi, ending, keyboard;
    uint32_t session;
    uint8_t modifiers, key;
} shortcut_request_t;
static uint32_t audio_sequence;
static uint32_t drops;
static int listener = -1, client = -1;
static int discovery = -1;
static bool authenticated;
static vp_parser_t usb_parser, wifi_parser;
static char result[64] = "boot";
static uint32_t ack_sequence;
static bool wifi_started;
static bool config_changed;
static int64_t last_status_sent;
/* Only a scan-order hint. IDF searches other channels if this one misses.
   Keep it across deep sleep without writing flash or locking a BSSID. */
static RTC_DATA_ATTR _Atomic uint32_t last_wifi_channel;
static _Atomic uint32_t wifi_start_ms, wifi_associated_ms, wifi_ip_ms, wifi_ready_ms;
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
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_CONNECTED && wifi_wanted) {
        const wifi_event_sta_connected_t *event = data;
        last_wifi_channel = event->channel;
        wifi_associated_ms = (uint32_t)(esp_timer_get_time() / 1000);
    }
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        wifi_got_ip = false;
        ip_address = 0;
        ready_wifi = 0;
        wifi_associated_ms = wifi_ip_ms = wifi_ready_ms = 0;
        if (wifi_wanted)
            (void)esp_wifi_connect();
    }
    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP && wifi_wanted) {
        ip_event_got_ip_t *event = data;
        ip_address = event->ip_info.ip.addr;
        wifi_ip_ms = (uint32_t)(esp_timer_get_time() / 1000);
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
static esp_err_t stop_wifi(void) {
    wifi_wanted = false;
    close_client();
    if (listener >= 0) {
        close(listener);
        listener = -1;
    }
    if (discovery >= 0) {
        close(discovery);
        discovery = -1;
    }
    if (wifi_started) {
        esp_err_t err = esp_wifi_stop();
        if (err != ESP_OK)
            return err;
        wifi_started = false;
    }
    wifi_got_ip = false;
    ip_address = 0;
    wifi_associated_ms = wifi_ip_ms = wifi_ready_ms = 0;
    return ESP_OK;
}
static void update_wifi(void) {
    /* The bridge selects USB only after opening it. Removing USB falls back
       to configured Wi-Fi after recording has safely stopped. */
    if (voice_transport_auto && !voice_wifi_mode && !usb_serial_jtag_is_connected() &&
        !voice_mic && !voice_audio && !voice_recording && config.ssid[0] && config.token[0])
        voice_wifi_mode = true;
    bool wanted = voice_wifi_mode && !voice_wifi_idle && config.ssid[0] && config.token[0];
    if (config_changed || !wanted) {
        esp_err_t err = stop_wifi();
        if (err != ESP_OK) {
            voice_error = err;
            return;
        }
        config_changed = false;
    }
    if (wanted && !wifi_started) {
        wifi_config_t sta = {0};
        memcpy(sta.sta.ssid, config.ssid, strlen(config.ssid));
        memcpy(sta.sta.password, config.password, strlen(config.password));
        sta.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
        sta.sta.pmf_cfg.capable = true;
        uint32_t channel = last_wifi_channel;
        sta.sta.channel = channel <= 14 ? channel : 0;
        sta.sta.scan_method = WIFI_FAST_SCAN;
        wifi_start_ms = (uint32_t)(esp_timer_get_time() / 1000);
        wifi_associated_ms = wifi_ip_ms = wifi_ready_ms = 0;
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
    if (!wifi_got_ip && discovery >= 0) {
        close(discovery);
        discovery = -1;
    }
    if (wifi_got_ip && discovery < 0) {
        discovery = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        if (discovery >= 0) {
            struct sockaddr_in addr = {.sin_family = AF_INET,
                                       .sin_port = htons(VOICE_PORT),
                                       .sin_addr.s_addr = htonl(INADDR_ANY)};
            if (bind(discovery, (struct sockaddr *)&addr, sizeof(addr)) < 0 ||
                fcntl(discovery, F_SETFL, O_NONBLOCK) < 0) {
                close(discovery);
                discovery = -1;
            }
        }
    }
}
static void answer_discovery(void) {
    static int64_t last_reply;
    if (discovery < 0)
        return;
    uint8_t request[80], response[80];
    struct sockaddr_in peer;
    socklen_t size = sizeof(peer);
    int n = recvfrom(discovery, request, sizeof(request), 0, (struct sockaddr *)&peer, &size);
    if (n <= 0)
        return;
    size_t length = vp_discovery_reply(request, (size_t)n, response, sizeof(response));
    int64_t now = esp_timer_get_time();
    if (length && now - last_reply >= 100000) {
        last_reply = now;
        (void)sendto(discovery, response, length, 0, (struct sockaddr *)&peer, size);
    }
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
    char json[1024], ip[32];
    voice_ip(ip, sizeof(ip));
    int n = snprintf(json, sizeof(json),
                     "{\"ack\":%lu,\"result\":\"%s\",\"mic\":%s,\"audio\":%s,\"bridge\":%s,"
                     "\"recording\":%s,\"session\":%lu,\"transport\":\"%s\",\"ip\":\"%s\",\"error\":%d,\"drops\":%lu,"
                     "\"modifiers\":%u,\"key\":%u,\"rate\":16000,\"channels\":1,\"bits\":16,"
                     "\"auto_transport\":%s,\"power_profile\":\"idle-v3\",\"battery_pct\":%d,\"battery_mv\":%d,"
                     "\"uptime_s\":%lu,\"screen_off\":%s,\"codec_asleep\":%s,\"wifi_idle\":%s,"
                     "\"usb_host\":%s,\"deep_wakes\":%lu,\"sleep_error\":%d,"
                     "\"wifi_start_ms\":%lu,\"wifi_associated_ms\":%lu,\"wifi_ip_ms\":%lu,\"wifi_ready_ms\":%lu}",
                     (unsigned long)ack_sequence, result, voice_mic ? "true" : "false",
                     voice_audio ? "true" : "false", voice_bridge_ready() ? "true" : "false",
                     voice_recording ? "true" : "false", (unsigned long)voice_session,
                     voice_wifi_mode ? "wifi" : "usb", ip,
                     voice_error, (unsigned long)drops, voice_modifier(), voice_key(),
                     voice_transport_auto ? "true" : "false", voice_battery_percent, voice_battery_mv,
                     (unsigned long)(esp_timer_get_time() / 1000000),
                     voice_screen_off ? "true" : "false", voice_codec_asleep ? "true" : "false",
                     voice_wifi_idle ? "true" : "false",
                     usb_serial_jtag_is_connected() ? "true" : "false",
                     (unsigned long)voice_deep_wakes, voice_sleep_error,
                     (unsigned long)wifi_start_ms, (unsigned long)wifi_associated_ms,
                     (unsigned long)wifi_ip_ms, (unsigned long)wifi_ready_ms);
    if (n > 0 && n < (int)sizeof(json)) {
        if (write_frame(wifi, VP_STATUS, 0, json, (size_t)n))
            last_status_sent = esp_timer_get_time();
        else if (wifi)
            close_client();
        else
            ready_usb = 0;
    }
}
/* Ask the bridge to press the saved shortcut on the host.
   The event frame carries no acknowledgement field, so it can never be
   mistaken for the reply to a command. */
bool voice_trigger(bool ending) {
    if (!voice_bridge_ready() || !shortcut_queue)
        return false;
    shortcut_request_t request = {.requested_at = esp_timer_get_time(),
                                  .wifi = voice_wifi_mode,
                                  .ending = ending,
                                  .session = voice_session,
                                  .modifiers = voice_modifier(), .key = voice_key()};
    return xQueueSend(shortcut_queue, &request, 0) == pdTRUE;
}
bool voice_send_key(uint8_t key) {
    if (!voice_bridge_ready() || !shortcut_queue ||
        !(key == 0x28 || key == 0x2a || key == 0x51 || key == 0x52))
        return false;
    shortcut_request_t request = {.requested_at = esp_timer_get_time(),
                                  .wifi = voice_wifi_mode, .keyboard = true,
                                  .key = key};
    return xQueueSend(shortcut_queue, &request, 0) == pdTRUE;
}
/* Only the transport task writes frames and owns the TCP client. */
static void send_shortcut(void) {
    shortcut_request_t request;
    if (xQueueReceive(shortcut_queue, &request, 0) != pdTRUE)
        return;
    if (request.wifi != voice_wifi_mode || !voice_bridge_ready() ||
        (!request.keyboard && request.session != voice_session) ||
        (!request.keyboard && !request.ending && (!voice_mic || !voice_audio)) ||
        esp_timer_get_time() - request.requested_at > 500000)
        return;
    char json[160];
    int n;
    if (request.keyboard)
        n = snprintf(json, sizeof(json),
                     "{\"event\":\"key\",\"modifiers\":0,\"key\":%u}", request.key);
    else
        n = snprintf(json, sizeof(json),
                     "{\"event\":\"recording\",\"modifiers\":%u,\"key\":%u,"
                     "\"ending\":%s,\"session\":%lu}",
                     request.modifiers, request.key,
                     request.ending ? "true" : "false", (unsigned long)request.session);
    if (n > 0 && n < (int)sizeof(json) &&
        !write_frame(request.wifi, VP_STATUS, 0, json, (size_t)n)) {
        if (request.wifi)
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
            if (wifi) {
                ready_wifi = now;
                if (now && !wifi_ready_ms)
                    wifi_ready_ms = now;
            } else
                ready_usb = now;
            snprintf(result, sizeof(result), "ok");
        }
    } else if (op && !strcmp(op, "transport")) {
        const char *mode = str(obj, "mode");
        cJSON *automatic = cJSON_GetObjectItemCaseSensitive(obj, "automatic");
        /* Only the connected, authenticated link may claim itself. Never
           switch a live recording or accept an unverified remote USB claim. */
        if (mode && cJSON_IsBool(automatic) && !strcmp(mode, wifi ? "wifi" : "usb")) {
            if (voice_mic || voice_audio || voice_recording)
                snprintf(result, sizeof(result), "transport busy");
            else {
                voice_transport_auto = cJSON_IsTrue(automatic);
                voice_wifi_mode = wifi;
                snprintf(result, sizeof(result), "ok");
            }
        }
    } else if (op && !strcmp(op, "stop")) {
        cJSON *session = cJSON_GetObjectItemCaseSensitive(obj, "session");
        if (cJSON_IsNumber(session) && session->valuedouble == session->valueint &&
            session->valueint >= 0) {
            if (voice_recording && (uint32_t)session->valueint == voice_session) {
                voice_mic = false;
                voice_recording = false;
            }
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
                if (config_changed)
                    last_wifi_channel = 0;
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
static void pause_for_sleep(_Atomic bool *paused) {
    *paused = true;
    while (sleep_requested)
        (void)ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    *paused = false;
}
void voice_runtime_resume(void) {
    sleep_requested = false;
    if (transport_worker)
        xTaskNotifyGive(transport_worker);
    if (audio_worker)
        xTaskNotifyGive(audio_worker);
    if (battery_worker)
        xTaskNotifyGive(battery_worker);
}
esp_err_t voice_runtime_pause(void) {
    if (!transport_worker || !audio_worker || !battery_worker || voice_mic || voice_audio)
        return ESP_ERR_INVALID_STATE;
    transport_sleep_error = ESP_OK;
    sleep_requested = true;
    xTaskNotifyGive(battery_worker);
    int64_t deadline = esp_timer_get_time() + 1500000;
    while ((!transport_paused || !audio_paused || !battery_paused) && esp_timer_get_time() < deadline)
        vTaskDelay(pdMS_TO_TICKS(10));
    bool paused = transport_paused && audio_paused && battery_paused;
    esp_err_t err = paused ? transport_sleep_error : ESP_ERR_TIMEOUT;
    if (err == ESP_OK && (voice_mic || voice_audio || !voice_codec_asleep))
        err = ESP_ERR_INVALID_STATE;
    if (err != ESP_OK)
        voice_runtime_resume();
    return err;
}
static void transport_task(void *arg) {
    (void)arg;
    uint8_t input[256];
    audio_chunk_t chunk;
    int64_t accepted_at = 0;
    for (;;) {
        if (sleep_requested) {
            transport_sleep_error = stop_wifi();
            pause_for_sleep(&transport_paused);
            continue;
        }
        int n = usb_serial_jtag_read_bytes(input, sizeof(input), 0);
        if (n > 0)
            vp_feed(&usb_parser, input, n, command, NULL);
        update_wifi();
        answer_discovery();
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
        send_shortcut();
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
        if (now - last_status_sent >= (voice_mic ? 500000 : 1500000)) {
            if (ready_usb > 0)
                status(false);
            if (client >= 0 && authenticated)
                status(true);
        }
        unsigned interval = voice_mic ? 2 : (voice_screen_off || voice_wifi_idle ? 100 : 20);
        vTaskDelay(pdMS_TO_TICKS(interval));
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
                voice_codec_asleep = e == ESP_OK;
                (void)esp_pm_lock_release(audio_power_lock);
                opened = false;
            }
            if (sleep_requested) {
                pause_for_sleep(&audio_paused);
                continue;
            }
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        if (!opened) {
            /* sleep() leaves the codec in low power; without wake() the format
               call below fails with ESP_ERR_INVALID_STATE and the microphone
               cannot be enabled a second time. */
            esp_err_t err = esp_pm_lock_acquire(audio_power_lock);
            if (err != ESP_OK) {
                voice_error = err;
                voice_mic = false;
                continue;
            }
            err = bsp_audio_wake();
            if (err == ESP_OK)
                err = bsp_audio_init();
            if (err == ESP_OK)
                err = bsp_audio_set_format(16000, 16, 1);
            if (err != ESP_OK) {
                (void)bsp_audio_sleep();
                (void)esp_pm_lock_release(audio_power_lock);
                voice_error = err;
                voice_mic = false;
                continue;
            }
            opened = true;
            voice_codec_asleep = false;
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
static void battery_task(void *arg) {
    (void)arg;
    bool initialized = false;
    int64_t initialized_at = 0;
    for (;;) {
        if (sleep_requested) {
            pause_for_sleep(&battery_paused);
            continue;
        }
        if (!initialized) {
            initialized = bsp_battery_init() == ESP_OK;
            initialized_at = esp_timer_get_time();
        }
        int64_t elapsed = esp_timer_get_time() - initialized_at;
        int soc = initialized ? bsp_battery_soc() : -1;
        int mv = initialized ? bsp_battery_mv() : -1;
        voice_battery_percent = voice_battery_soc_value(soc, elapsed);
        voice_battery_mv = mv > 0 ? mv : -1;
        /* Never block networking or buttons on the fuel gauge. Notify wakes
           this task before deep sleep so it cannot access a closed I2C bus. */
        unsigned interval = initialized && elapsed < INT64_C(60000000) ? 1000 : 30000;
        (void)ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(interval));
    }
}
esp_err_t voice_runtime_init(void) {
    if (esp_reset_reason() != ESP_RST_DEEPSLEEP)
        last_wifi_channel = 0;
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
    /* USB commands are always serviced. Start configured Wi-Fi so the Mac
       can connect without a manual mode selection, including on battery. */
    voice_wifi_mode = config.ssid[0] && config.token[0];
    /* Set a known codec standby state even before the first recording. */
    esp_err_t err = bsp_audio_init();
    if (err == ESP_OK)
        err = bsp_audio_sleep();
    if (err != ESP_OK)
        return err;
    voice_codec_asleep = true;
    usb_serial_jtag_driver_config_t usb = {.tx_buffer_size = 2048, .rx_buffer_size = 2048};
    err = usb_serial_jtag_driver_install(&usb);
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
    err = esp_wifi_set_ps(WIFI_PS_MIN_MODEM);
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
    err = esp_pm_lock_create(ESP_PM_CPU_FREQ_MAX, 0, "voice_audio", &audio_power_lock);
    if (err != ESP_OK)
        return err;
    pcm_queue = xQueueCreate(4, sizeof(audio_chunk_t));
    shortcut_queue = xQueueCreate(4, sizeof(shortcut_request_t));
    if (!pcm_queue || !shortcut_queue)
        return ESP_ERR_NO_MEM;
    if (xTaskCreate(transport_task, "voice_link", 6144, NULL, 3, &transport_worker) != pdPASS)
        return ESP_ERR_NO_MEM;
    if (xTaskCreate(audio_task, "voice_audio", 4096, NULL, 3, &audio_worker) != pdPASS)
        return ESP_ERR_NO_MEM;
    if (xTaskCreate(battery_task, "voice_battery", 3072, NULL, 2, &battery_worker) != pdPASS)
        return ESP_ERR_NO_MEM;
    return ESP_OK;
}
