# phase1/firmware/rx2: CSI receiver 2

ESP-IDF project for **receiver 2**. It is identical to [`rx1`](../rx1/) except for its fixed IP address (`192.168.4.3`).

**What it does**
- **Connection:** joins the TX network as a station with a fixed IP (`192.168.4.3`, gateway `192.168.4.1`), with Wi-Fi power saving disabled and automatic reconnection.
- **CSI capture:** enables CSI with LLTF + HT-LTF, STBC HT-LTF2, LTF merging and channel filtering, and learns the TX's MAC address automatically.
- **Filtering:** keeps CSI only from 802.11n packets (`sig_mode == 1`) sent by the TX, so every line has the same 256-byte layout.
- **Export:** copies each CSI packet into a 128-slot queue inside the callback (never blocking Wi-Fi). A printer task writes one line per packet to the USB serial console at **921,600 baud**:

```text
CSI_DATA,seq,timestamp_us,rssi,noise_floor,channel,secondary_channel,sig_mode,mcs,cwb,stbc,len,first_word_invalid,dropped,"[256 numbers]"
```

| File | Purpose |
| --- | --- |
| `CMakeLists.txt` | ESP-IDF project definition |
| `sdkconfig` | Configuration: ESP32-S3, Wi-Fi CSI enabled, console at 921,600 baud |
| [`main/`](main/) | Source code |

Build and flash from this folder:

```bash
idf.py build
idf.py -p COM6 flash       # use the port of this board
idf.py -p COM6 monitor     # exit with Ctrl+]
```

A healthy log shows `Connected Successfully`, `IP Address : 192.168.4.3`, `CSI enabled successfully` and then a stream of `CSI_DATA` lines. Close the monitor before running the Python capture scripts, because only one program can open the serial port.

> **Before flashing:** the network name and password are placeholders (`CSI_SENSOR_AP` / `change_this_password`). Set your own values and keep them identical on TX, RX1 and RX2. (`main/wifi_sta.c`)
