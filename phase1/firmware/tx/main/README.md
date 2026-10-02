# phase1/firmware/tx/main

Source code of the transmitter.

| File | Purpose |
| --- | --- |
| `main.c` | `app_main()`: initialises NVS and networking, starts the access point and the UDP sender |
| `wifi_ap.c`, `wifi_ap.h` | Soft-AP configuration: network name/password, channel 6, HT20, WPA2, max 8 stations, power save off |
| `udp_sender.c`, `udp_sender.h` | FreeRTOS task that sends a 256-byte UDP packet to each receiver every 20 ms |
| `CMakeLists.txt` | Registers the component sources |

The Wi-Fi name and password are defined at the top of `wifi_ap.c`. They are placeholders in this repository.
