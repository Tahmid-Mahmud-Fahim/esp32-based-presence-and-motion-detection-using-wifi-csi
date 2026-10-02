#include "wifi_sta.h"
#include "csi_receiver.h"

void app_main(void)
{
    // Connect RX2 to the dedicated TX/AP first.
    wifi_sta_init();

    // Then enable CSI on the active Wi-Fi link.
    csi_init();
}
