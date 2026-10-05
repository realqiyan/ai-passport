#include "voice_hid.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "host/ble_gap.h"
#include "host/ble_hs.h"
#include "host/ble_sm.h"
#include "host/util/util.h"
#include "nimble/nimble_port.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include "store/config/ble_store_config.h"
#include <stdatomic.h>
#include <string.h>
void ble_store_config_init(void);
static _Atomic uint16_t connection = BLE_HS_CONN_HANDLE_NONE;
static _Atomic bool subscribed, encrypted, suspended;
static _Atomic int pairing = -1;
static uint16_t report_handle;
static uint8_t own_type;
static const uint8_t map[] = {
    0x05, 0x01, 0x09, 0x06, 0xa1, 0x01, 0x85, 0x01, 0x05, 0x07, 0x19, 0xe0, 0x29, 0xe7, 0x15, 0x00,
    0x25, 0x01, 0x75, 0x01, 0x95, 0x08, 0x81, 0x02, 0x95, 0x01, 0x75, 0x08, 0x81, 0x01, 0x95, 0x06,
    0x75, 0x08, 0x15, 0x00, 0x25, 0x73, 0x05, 0x07, 0x19, 0x00, 0x29, 0x73, 0x81, 0x00, 0xc0};
static int access(uint16_t conn, uint16_t attr, struct ble_gatt_access_ctxt *ctxt, void *arg) {
    (void)conn;
    (void)attr;
    const uint16_t id = (uint16_t)(uintptr_t)arg;
    if (ctxt->op == BLE_GATT_ACCESS_OP_WRITE_CHR) {
        uint8_t value;
        if (OS_MBUF_PKTLEN(ctxt->om) != 1 || os_mbuf_copydata(ctxt->om, 0, 1, &value) != 0 ||
            value > 1)
            return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
        if (id == 0x2a4c)
            suspended = value == 0;
        return 0;
    }
    const uint8_t info[] = {0x11, 0x01, 0x00, 0x02}, reference[] = {1, 1}, zeros[8] = {0}, mode = 1;
    const void *data = zeros;
    size_t n = sizeof(zeros);
    if (id == 0x2a4b) {
        data = map;
        n = sizeof(map);
    }
    if (id == 0x2a4a) {
        data = info;
        n = sizeof(info);
    }
    if (id == 0x2908) {
        data = reference;
        n = sizeof(reference);
    }
    if (id == 0x2a4e) {
        data = &mode;
        n = 1;
    }
    return os_mbuf_append(ctxt->om, data, n) == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
}
#define CHARACTERISTIC(id, fl)                                                                     \
    {.uuid = BLE_UUID16_DECLARE(id),                                                               \
     .access_cb = access,                                                                          \
     .arg = (void *)(uintptr_t)(id),                                                               \
     .flags = (fl)}
static const struct ble_gatt_svc_def services[] = {
    {.type = BLE_GATT_SVC_TYPE_PRIMARY,
     .uuid = BLE_UUID16_DECLARE(0x1812),
     .characteristics =
         (struct ble_gatt_chr_def[]){
             CHARACTERISTIC(0x2a4a, BLE_GATT_CHR_F_READ),
             CHARACTERISTIC(0x2a4b, BLE_GATT_CHR_F_READ),
             {.uuid = BLE_UUID16_DECLARE(0x2a4d),
              .access_cb = access,
              .arg = (void *)0x2a4d,
              .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_NOTIFY | BLE_GATT_CHR_F_READ_ENC,
              .val_handle = &report_handle,
              .descriptors = (struct ble_gatt_dsc_def[]){{.uuid = BLE_UUID16_DECLARE(0x2908),
                                                          .att_flags = BLE_ATT_F_READ,
                                                          .access_cb = access,
                                                          .arg = (void *)0x2908},
                                                         {0}}},
             CHARACTERISTIC(0x2a4c, BLE_GATT_CHR_F_WRITE_NO_RSP),
             {0}}},
    {0}};
static int gap(struct ble_gap_event *event, void *arg);
static void advertise(void) {
    struct ble_hs_adv_fields fields = {0};
    fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    fields.name = (uint8_t *)"Passport Voice";
    fields.name_len = strlen((char *)fields.name);
    fields.name_is_complete = 1;
    fields.appearance = 0x03c1;
    fields.appearance_is_present = 1;
    ble_uuid16_t uuid = BLE_UUID16_INIT(0x1812);
    fields.uuids16 = &uuid;
    fields.num_uuids16 = 1;
    fields.uuids16_is_complete = 1;
    if (ble_gap_adv_set_fields(&fields))
        return;
    struct ble_gap_adv_params params = {0};
    params.conn_mode = BLE_GAP_CONN_MODE_UND;
    params.disc_mode = BLE_GAP_DISC_MODE_GEN;
    (void)ble_gap_adv_start(own_type, NULL, BLE_HS_FOREVER, &params, gap, NULL);
}
static int gap(struct ble_gap_event *e, void *arg) {
    (void)arg;
    switch (e->type) {
    case BLE_GAP_EVENT_CONNECT:
        if (e->connect.status == 0) {
            connection = e->connect.conn_handle;
            (void)ble_gap_security_initiate(connection);
        } else
            advertise();
        break;
    case BLE_GAP_EVENT_DISCONNECT:
        connection = BLE_HS_CONN_HANDLE_NONE;
        subscribed = false;
        encrypted = false;
        suspended = false;
        pairing = -1;
        advertise();
        break;
    case BLE_GAP_EVENT_ADV_COMPLETE:
        advertise();
        break;
    case BLE_GAP_EVENT_SUBSCRIBE:
        if (e->subscribe.attr_handle == report_handle)
            subscribed = e->subscribe.cur_notify;
        break;
    case BLE_GAP_EVENT_ENC_CHANGE: {
        struct ble_gap_conn_desc desc;
        encrypted = e->enc_change.status == 0 &&
                    ble_gap_conn_find(e->enc_change.conn_handle, &desc) == 0 &&
                    desc.sec_state.encrypted && desc.sec_state.authenticated;
        break;
    }
    case BLE_GAP_EVENT_PASSKEY_ACTION:
        if (e->passkey.params.action == BLE_SM_IOACT_NUMCMP)
            pairing = (int)e->passkey.params.numcmp;
        else
            (void)ble_gap_terminate(e->passkey.conn_handle, BLE_ERR_REM_USER_CONN_TERM);
        break;
    case BLE_GAP_EVENT_REPEAT_PAIRING:
        return BLE_GAP_REPEAT_PAIRING_IGNORE;
    default:
        break;
    }
    return 0;
}
static void synced(void) {
    if (ble_hs_util_ensure_addr(0) == 0 && ble_hs_id_infer_auto(0, &own_type) == 0)
        advertise();
}
static void reset(int reason) {
    (void)reason;
    connection = BLE_HS_CONN_HANDLE_NONE;
    subscribed = false;
    encrypted = false;
    suspended = false;
    pairing = -1;
}
static void host_task(void *arg) {
    (void)arg;
    nimble_port_run();
    vTaskDelete(NULL);
}
esp_err_t voice_hid_init(void) {
    esp_err_t err = nimble_port_init();
    if (err != ESP_OK)
        return err;
    ble_hs_cfg.sync_cb = synced;
    ble_hs_cfg.reset_cb = reset;
    ble_hs_cfg.sm_io_cap = BLE_HS_IO_DISPLAY_YESNO;
    ble_hs_cfg.sm_bonding = 1;
    ble_hs_cfg.sm_mitm = 1;
    ble_hs_cfg.sm_sc = 1;
    ble_hs_cfg.sm_our_key_dist = BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID;
    ble_hs_cfg.sm_their_key_dist = BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID;
    ble_hs_cfg.store_status_cb = ble_store_util_status_rr;
    ble_svc_gap_init();
    ble_svc_gatt_init();
    ble_svc_gap_device_name_set("Passport Voice");
    ble_svc_gap_device_appearance_set(0x03c1);
    ble_store_config_init();
    if (ble_gatts_count_cfg(services) != 0 || ble_gatts_add_svcs(services) != 0)
        return ESP_FAIL;
    return xTaskCreate(host_task, "voice_ble", 4096, NULL, 3, NULL) == pdPASS ? ESP_OK
                                                                              : ESP_ERR_NO_MEM;
}
bool voice_hid_ready(void) {
    return connection != BLE_HS_CONN_HANDLE_NONE && subscribed && encrypted && !suspended;
}
static esp_err_t notify(uint16_t conn, const uint8_t *report) {
    struct os_mbuf *om = ble_hs_mbuf_from_flat(report, 8);
    if (!om)
        return ESP_ERR_NO_MEM;
    return ble_gatts_notify_custom(conn, report_handle, om) == 0 ? ESP_OK : ESP_FAIL;
}
esp_err_t voice_hid_shortcut(uint8_t modifiers, uint8_t key) {
    if (!voice_hid_ready())
        return ESP_ERR_INVALID_STATE;
    uint16_t conn = connection;
    uint8_t report[8] = {modifiers, 0, key, 0, 0, 0, 0, 0};
    esp_err_t press = notify(conn, report);
    vTaskDelay(pdMS_TO_TICKS(40));
    memset(report, 0, sizeof(report));
    esp_err_t release = ESP_FAIL;
    for (int i = 0; i < 3 && connection == conn; i++) {
        release = notify(conn, report);
        if (release == ESP_OK)
            break;
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    if (release != ESP_OK && connection == conn)
        (void)ble_gap_terminate(conn, BLE_ERR_REM_USER_CONN_TERM);
    return press == ESP_OK ? release : press;
}
int voice_hid_pairing_code(void) {
    return pairing;
}
void voice_hid_confirm(bool accept) {
    if (pairing < 0)
        return;
    struct ble_sm_io io = {.action = BLE_SM_IOACT_NUMCMP, .numcmp_accept = accept};
    (void)ble_sm_inject_io(connection, &io);
    pairing = -1;
}
void voice_hid_clear_bonds(void) {
    voice_hid_confirm(false);
    if (connection != BLE_HS_CONN_HANDLE_NONE)
        (void)ble_gap_terminate(connection, BLE_ERR_REM_USER_CONN_TERM);
    (void)ble_store_clear();
}
