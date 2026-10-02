#include "csi_receiver.h"

#include <stdio.h>
#include <string.h>
#include <inttypes.h>

#include "esp_wifi.h"
#include "esp_log.h"
#include "esp_err.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#define CSI_MAX_LEN      384
#define CSI_QUEUE_LEN    128
#define CSI_LINE_MAX     2400

static const char *TAG = "CSI";

static QueueHandle_t csi_queue = NULL;
static uint32_t seq = 0;
static uint32_t dropped_packets = 0;
static uint8_t tx_bssid[6] = {0};

typedef struct {
    uint32_t seq;
    uint32_t timestamp_us;
    uint32_t dropped;

    int8_t   rssi;
    int8_t   noise_floor;

    uint8_t  channel;
    uint8_t  secondary_channel;
    uint8_t  sig_mode;
    uint8_t  mcs;
    uint8_t  cwb;
    uint8_t  stbc;
    uint8_t  first_word_invalid;

    uint16_t len;
    int8_t   buf[CSI_MAX_LEN];
} csi_packet_t;

static void wifi_csi_cb(void *ctx, wifi_csi_info_t *info)
{
    if (info == NULL || info->buf == NULL) {
        return;
    }

    const uint8_t *expected_bssid = (const uint8_t *)ctx;

    // Keep only CSI frames originating from our dedicated TX/AP.
    if (expected_bssid != NULL && memcmp(info->mac, expected_bssid, 6) != 0) {
        return;
    }

    // Keep only HT / 802.11n CSI packets from our dedicated UDP stream.
    // sig_mode = 0 -> legacy / non-HT (typically AP beacons, often len=128)
    // sig_mode = 1 -> HT / 802.11n (our desired sensing packets, currently len=256)
    if (info->rx_ctrl.sig_mode != 1) {
        return;
    }

    // For our fixed ESP32-S3 HT20 setup, 384 bytes is a safe maximum.
    // Never silently truncate an unexpected CSI frame.
    if (info->len > CSI_MAX_LEN) {
        dropped_packets++;
        return;
    }

    csi_packet_t pkt = {0};

    pkt.seq                = seq++;
    pkt.timestamp_us       = info->rx_ctrl.timestamp;
    pkt.rssi               = info->rx_ctrl.rssi;
    pkt.noise_floor        = info->rx_ctrl.noise_floor;
    pkt.channel            = info->rx_ctrl.channel;
    pkt.secondary_channel  = info->rx_ctrl.secondary_channel;
    pkt.sig_mode           = info->rx_ctrl.sig_mode;
    pkt.mcs                = info->rx_ctrl.mcs;
    pkt.cwb                = info->rx_ctrl.cwb;
    pkt.stbc               = info->rx_ctrl.stbc;
    pkt.first_word_invalid = info->first_word_invalid ? 1 : 0;
    pkt.len                = info->len;
    pkt.dropped            = dropped_packets;

    memcpy(pkt.buf, info->buf, pkt.len);

    // Never block the Wi-Fi task.
    if (xQueueSend(csi_queue, &pkt, 0) != pdTRUE) {
        dropped_packets++;
    }
}

static void csi_print_task(void *arg)
{
    csi_packet_t pkt;
    static char line[CSI_LINE_MAX];

    while (1) {
        if (xQueueReceive(csi_queue, &pkt, portMAX_DELAY) == pdTRUE) {

            int pos = snprintf(
                line,
                sizeof(line),
                "CSI_DATA,%" PRIu32 ",%" PRIu32 ",%d,%d,%u,%u,%u,%u,%u,%u,%u,%u,%" PRIu32 ",\"[",
                pkt.seq,
                pkt.timestamp_us,
                pkt.rssi,
                pkt.noise_floor,
                (unsigned)pkt.channel,
                (unsigned)pkt.secondary_channel,
                (unsigned)pkt.sig_mode,
                (unsigned)pkt.mcs,
                (unsigned)pkt.cwb,
                (unsigned)pkt.stbc,
                (unsigned)pkt.len,
                (unsigned)pkt.first_word_invalid,
                pkt.dropped);

            if (pos < 0 || pos >= (int)sizeof(line)) {
                continue;
            }

            for (int i = 0; i < pkt.len; i++) {
                int written = snprintf(
                    line + pos,
                    sizeof(line) - pos,
                    "%d%s",
                    pkt.buf[i],
                    (i < pkt.len - 1) ? "," : "");

                if (written < 0 || written >= (int)(sizeof(line) - pos)) {
                    pos = -1;
                    break;
                }

                pos += written;
            }

            if (pos < 0) {
                continue;
            }

            snprintf(line + pos, sizeof(line) - pos, "]\"\n");
            fputs(line, stdout);
        }
    }
}

void csi_init(void)
{
    // ESP32-S3 / ESP-IDF 5.5.x CSI configuration.
    // This matches Espressif's standard legacy/HT CSI configuration.
    wifi_csi_config_t config = {
        .lltf_en = true,
        .htltf_en = true,
        .stbc_htltf2_en = true,
        .ltf_merge_en = true,
        .channel_filter_en = true,
        .manu_scale = false,
        .shift = false,
    };

    // Learn the currently connected AP/TX BSSID automatically.
    wifi_ap_record_t ap_info = {0};
    ESP_ERROR_CHECK(esp_wifi_sta_get_ap_info(&ap_info));
    memcpy(tx_bssid, ap_info.bssid, sizeof(tx_bssid));

    ESP_LOGI(TAG,
             "TX/AP BSSID: %02x:%02x:%02x:%02x:%02x:%02x",
             tx_bssid[0], tx_bssid[1], tx_bssid[2],
             tx_bssid[3], tx_bssid[4], tx_bssid[5]);

    csi_queue = xQueueCreate(CSI_QUEUE_LEN, sizeof(csi_packet_t));
    if (csi_queue == NULL) {
        ESP_LOGE(TAG, "Failed to create CSI queue");
        return;
    }

    // Do not use ESP_ERROR_CHECK here while debugging: log exact failure.
    esp_err_t err = esp_wifi_set_csi_config(&config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG,
                 "esp_wifi_set_csi_config failed: %s (0x%x)",
                 esp_err_to_name(err),
                 (unsigned)err);
        return;
    }
    ESP_LOGI(TAG, "CSI configuration accepted");

    err = esp_wifi_set_csi_rx_cb(wifi_csi_cb, tx_bssid);
    if (err != ESP_OK) {
        ESP_LOGE(TAG,
                 "esp_wifi_set_csi_rx_cb failed: %s (0x%x)",
                 esp_err_to_name(err),
                 (unsigned)err);
        return;
    }

    err = esp_wifi_set_csi(true);
    if (err != ESP_OK) {
        ESP_LOGE(TAG,
                 "esp_wifi_set_csi(true) failed: %s (0x%x)",
                 esp_err_to_name(err),
                 (unsigned)err);
        return;
    }

    BaseType_t ok = xTaskCreate(
        csi_print_task,
        "csi_print",
        4096,
        NULL,
        3,
        NULL);

    if (ok != pdPASS) {
        ESP_LOGE(TAG, "Failed to create CSI print task");
        return;
    }

    ESP_LOGI(TAG, "CSI enabled successfully");
}
