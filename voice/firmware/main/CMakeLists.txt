idf_component_register(
    SRCS "main.c" "voice_hid.c" "voice_runtime.c" "voice_protocol.c" "voice_model.c"
    INCLUDE_DIRS "."
    REQUIRES bsp bt nvs_flash esp_wifi esp_netif esp_event esp_timer json esp_driver_usb_serial_jtag lwip
)
