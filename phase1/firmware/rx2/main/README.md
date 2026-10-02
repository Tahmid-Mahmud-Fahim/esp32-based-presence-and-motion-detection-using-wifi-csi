# phase1/firmware/rx2/main

Source code of receiver 2.

| File | Purpose |
| --- | --- |
| `main.c` | `app_main()`: initialises NVS and networking, connects to the TX, starts CSI capture |
| `wifi_sta.c`, `wifi_sta.h` | Station mode: network name/password, fixed IP `192.168.4.3`, power save off, reconnect on disconnect |
| `csi_receiver.c`, `csi_receiver.h` | CSI configuration, callback with TX-MAC and packet-format filtering, 128-slot queue and the printer task that streams `CSI_DATA` lines |
| `CMakeLists.txt` | Registers the component sources |

The Wi-Fi name and password are defined at the top of `wifi_sta.c`. They are placeholders in this repository.
