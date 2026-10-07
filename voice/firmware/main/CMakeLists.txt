idf_component_register(
    SRCS "main.c" "voice_runtime.c" "voice_protocol.c" "voice_model.c" "voice_power.c"
    INCLUDE_DIRS "."
    REQUIRES esp_pm esp_lvgl_port bsp nvs_flash esp_wifi esp_netif esp_event esp_timer json esp_driver_usb_serial_jtag lwip esp_adc esp_driver_gpio esp_hw_support button
)
