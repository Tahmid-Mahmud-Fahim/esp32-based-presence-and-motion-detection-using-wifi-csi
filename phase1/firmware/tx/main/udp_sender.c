#include "udp_sender.h"

#include <string.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define UDP_PORT            3333
#define PACKET_SIZE         256
#define SEND_INTERVAL_MS    20

static const char *TAG = "UDP_TX";

static void udp_sender_task(void *pvParameters)
{
    char packet[PACKET_SIZE];
    memset(packet, 'A', sizeof(packet));

    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    if (sock < 0) {
        ESP_LOGE(TAG, "Cannot create socket");
        vTaskDelete(NULL);
    }

    // Define BOTH RX targets
    const char *target_ips[] = {"192.168.4.2", "192.168.4.3"};
    int num_targets = 2;
    struct sockaddr_in dest_addr[2];

    for(int i=0; i<num_targets; i++) {
        dest_addr[i].sin_addr.s_addr = inet_addr(target_ips[i]);
        dest_addr[i].sin_family = AF_INET;
        dest_addr[i].sin_port = htons(UDP_PORT);
    }

    ESP_LOGI(TAG, "UDP Sender Started (Dual Unicast)");
    ESP_LOGI(TAG, "Targets: %s, %s | Port: %d | Interval: %d ms", target_ips[0], target_ips[1], UDP_PORT, SEND_INTERVAL_MS);

    while (1) {
        // Send the same packet to both RX boards instantly
        for(int i=0; i<num_targets; i++) {
            sendto(sock, packet, sizeof(packet), 0,
                   (struct sockaddr *)&dest_addr[i], sizeof(dest_addr[i]));
        }
        vTaskDelay(pdMS_TO_TICKS(SEND_INTERVAL_MS));
    }
}

void udp_sender_start(void)
{
    xTaskCreate(udp_sender_task, "udp_sender_task", 4096, NULL, 5, NULL);
}