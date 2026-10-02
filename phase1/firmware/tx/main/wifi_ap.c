#include "wifi_ap.h"

#include <string.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"

/* Network name and password of the dedicated sensing network.
 * Change both before flashing and keep them identical on TX, RX1 and RX2.
 * WPA2 needs a password of at least 8 characters. */
#define WIFI_SSID      "CSI_SENSOR_AP"
#define WIFI_PASS      "change_this_password"

#define WIFI_CHANNEL   6

#define MAX_STA_CONN   8

static const char *TAG = "WIFI_AP";

void wifi_ap_init(void)
{
    ESP_LOGI(TAG, "Initializing network...");

    //---------------------------------------------
    // Initialize TCP/IP Stack
    //---------------------------------------------

    ESP_ERROR_CHECK(esp_netif_init());

    ESP_ERROR_CHECK(esp_event_loop_create_default());

    esp_netif_create_default_wifi_ap();

    //---------------------------------------------
    // Initialize WiFi Driver
    //---------------------------------------------

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();

    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    //---------------------------------------------
    // Configure Access Point
    //---------------------------------------------

    wifi_config_t wifi_config = {

        .ap = {

            .ssid = WIFI_SSID,

            .ssid_len = strlen(WIFI_SSID),

            .channel = WIFI_CHANNEL,

            .password = WIFI_PASS,

            .max_connection = MAX_STA_CONN,

            .authmode = WIFI_AUTH_WPA2_PSK

        }

    };

    if (strlen(WIFI_PASS) == 0)
    {
        wifi_config.ap.authmode = WIFI_AUTH_OPEN;
    }

    //---------------------------------------------
    // Start WiFi
    //---------------------------------------------

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));

    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &wifi_config));

    ESP_ERROR_CHECK(esp_wifi_start());

    //---------------------------------------------
    // Recommended for CSI
    //---------------------------------------------

    ESP_ERROR_CHECK(
        esp_wifi_set_bandwidth(
            WIFI_IF_AP,
            WIFI_BW_HT20));

    ESP_ERROR_CHECK(
        esp_wifi_set_ps(
            WIFI_PS_NONE));

    //---------------------------------------------
    // Information
    //---------------------------------------------

    ESP_LOGI(TAG, "====================================");

    ESP_LOGI(TAG, "WiFi Access Point Started");

    ESP_LOGI(TAG, "SSID     : %s", WIFI_SSID);

    ESP_LOGI(TAG, "Password : (hidden)");

    ESP_LOGI(TAG, "Channel  : %d", WIFI_CHANNEL);

    ESP_LOGI(TAG, "Max STA  : %d", MAX_STA_CONN);

    ESP_LOGI(TAG, "Bandwidth: 20 MHz");

    ESP_LOGI(TAG, "====================================");
}