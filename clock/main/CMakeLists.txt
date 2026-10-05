idf_component_register(
    SRCS "main.c" "clock_model.c"
    INCLUDE_DIRS "."
    REQUIRES bsp esp_timer nvs_flash
)
target_sources(${COMPONENT_LIB} PRIVATE
    "${CMAKE_CURRENT_LIST_DIR}/../assets/fonts/clock_font_16.c"
)
