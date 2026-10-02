# phase1/firmware

Three independent **ESP-IDF 5.5.5** projects for the ESP32-S3 (C, FreeRTOS). Build and flash each one onto its own board.

| Project | Board role | Network |
| --- | --- | --- |
| [`tx/`](tx/) | Access point and UDP packet source | `192.168.4.1`, WPA2, channel 6, 20 MHz |
| [`rx1/`](rx1/) | CSI receiver 1, streams CSI over USB | fixed IP `192.168.4.2` |
| [`rx2/`](rx2/) | CSI receiver 2 (same code as RX1) | fixed IP `192.168.4.3` |

**How it works**
- **TX:** sends a 256-byte UDP packet to RX1 and RX2 (port 3333) every **20 ms**, about 50 packets per second per receiver.
- **Receivers, capture:** each receiver keeps the CSI of 802.11n packets from the TX's MAC address. That is 256 bytes per packet: the LLTF and HT-LTF fields, 64 subcarrier slots each.
- **Receivers, export:** the CSI callback only copies each packet into a 128-slot queue, and a separate task prints one `CSI_DATA` line per packet at **921,600 baud**.

Build and flash (from inside `tx/`, `rx1/` or `rx2/`, in an ESP-IDF terminal):

```bash
idf.py build
idf.py -p COM6 flash       # use the port of this board
idf.py -p COM6 monitor     # exit with Ctrl+]
```

The included `sdkconfig` files select the ESP32-S3 target, enable Wi-Fi CSI (`CONFIG_ESP_WIFI_CSI_ENABLED=y`) and set the receivers' console to 921,600 baud. Build output (`build/`) is not stored in the repository.

> **Before flashing:** the network name and password are placeholders (`CSI_SENSOR_AP` / `change_this_password`). Set your own values and keep them identical on TX, RX1 and RX2.
