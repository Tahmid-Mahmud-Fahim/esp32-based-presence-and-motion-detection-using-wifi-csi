# phase1/data/raw

Raw CSI recordings of the Phase 1 dataset: **60 CSV files** = 30 sessions × 2 receivers, each about 60 s at about 50 packets per second.

- **Naming:** `<session>_RX1.csv` / `<session>_RX2.csv`, for example `S02_stand_right_RX1.csv` = subject S02, standing on the right marker, receiver 1.
- **Sessions:** `empty_01` … `empty_09` (nobody in the room), and for each subject S01–S03: `stand_center`, `stand_left`, `stand_right`, `sit_center`, `stand_txside`, `stand_rxside`, `normal_walk`.
- **How recorded:** `python/01_capture_dual_rx.py` reads both receivers in parallel and timestamps every line with the laptop clock.

**Columns (16):**

| Column | Meaning |
| --- | --- |
| `pc_monotonic_ns` | Laptop monotonic clock at arrival (ns) |
| `pc_elapsed_s` | Seconds since recording start, shared by RX1 and RX2 |
| `seq` | Receiver packet counter (a gap means a drop inside the receiver) |
| `device_timestamp_us` | ESP32 clock at reception (µs) |
| `rssi`, `noise_floor` | Signal strength and noise floor (dBm) |
| `channel`, `secondary_channel` | Wi-Fi channel 6 = 2.437 GHz; 0 = no 40 MHz extension |
| `sig_mode`, `mcs`, `cwb`, `stbc` | 1 = 802.11n packet; MCS index; 0 = 20 MHz; 0 = no STBC |
| `csi_len`, `first_word_invalid`, `firmware_dropped` | 256 bytes of CSI; ESP-IDF validity flag; packets dropped in the RX so far |
| `csi_data` | 256 signed numbers = 128 (imaginary, real) pairs: 64 LLTF slots, then 64 HT-LTF slots |

All recordings passed the quality checks: expected packet format, no firmware drops, no sequence gaps and no gap above 0.25 s.
