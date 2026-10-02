#include "nvs_flash.h"
#include "esp_err.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "wifi_ap.h"
#include "udp_sender.h"

void app_main(void)
{
    esp_err_t ret = nvs_flash_init();

    if (ret == ESP_ERR_NVS_NO_FREE_PAGES ||
        ret == ESP_ERR_NVS_NEW_VERSION_FOUND)
    {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    }

    wifi_ap_init();

    vTaskDelay(pdMS_TO_TICKS(3000));

    udp_sender_start();

    while (1)
    {
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}