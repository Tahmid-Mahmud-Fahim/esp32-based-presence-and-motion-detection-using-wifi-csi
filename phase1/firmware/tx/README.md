# phase1/firmware/tx: transmitter

ESP-IDF project for the **transmitter / access point**.

**What it does**
- **Access point:** starts a WPA2 soft-AP on channel 6, 20 MHz (HT20), at `192.168.4.1`, for up to 8 stations.
- **Packets:** sends a 256-byte UDP packet to **both receivers** (`192.168.4.2` and `192.168.4.3`, port 3333) every **20 ms** (dual unicast). Unicast packets are sent as 802.11n frames, so every packet gives the receivers full 256-byte CSI.
- **Power save:** disables Wi-Fi power saving for steady timing.

A first version broadcast a packet every 5 ms. This gave only 128-number legacy CSI and overloaded the receivers' USB serial output, so it was replaced by the current design (see the main [README](../../../README.md#5-firmware)).

| File | Purpose |
| --- | --- |
| `CMakeLists.txt` | ESP-IDF project definition |
| `sdkconfig` | Project configuration (ESP32-S3 target, Wi-Fi settings) |
| [`main/`](main/) | Source code |

Build and flash from this folder:

```bash
idf.py build
idf.py -p COM6 flash       # use the port of this board
idf.py -p COM6 monitor     # exit with Ctrl+]
```

A healthy log shows `WiFi Access Point Started`, then `UDP Sender Started (Dual Unicast)` with `Targets: 192.168.4.2, 192.168.4.3 | Port: 3333 | Interval: 20 ms`.

> **Before flashing:** the network name and password are placeholders (`CSI_SENSOR_AP` / `change_this_password`). Set your own values and keep them identical on TX, RX1 and RX2. (`main/wifi_ap.c`)
