# phase1: hardware, firmware and presence detection

Phase 1 covers everything up to the **EMPTY / PERSON** decision:
- the ESP32-S3 firmware;
- dual-receiver CSI capture;
- the 30-session Phase 1 dataset;
- the shared preprocessing library;
- the presence models, the test evaluation and the live detectors.

| Folder | Contents |
| --- | --- |
| [`firmware/`](firmware/) | ESP-IDF projects for the transmitter and the two receivers |
| [`presence/`](presence/) | `csi_utils.py`: CSI decoding, alignment, normalisation, windowing and the 31 presence features (also used by Phase 2) |
| [`python/`](python/) | Numbered scripts 00–08: ports, capture, quality checks, dataset, training, test, live and phone control |
| [`data/`](data/) | `manifest.csv`, raw recordings (`raw/`) and feature tables (`processed/`) |
| [`models/`](models/) | Trained presence model and selection records |
| [`reports/`](reports/) | Test results and a sanity-check plot |

**Phase 1 dataset:** 30 sessions (9 EMPTY + 21 with a person), split by subject.

| Split | empty | person | Sessions |
| --- | ---: | ---: | ---: |
| train | 5 | 7 | 12 |
| val | 2 | 7 | 9 |
| test | 2 | 7 | 9 |

**Held-out test result (subject S03):** random forest, 99.82% window accuracy, macro-F1 0.9973, PERSON recall 100%, all test sessions correct.

Run the Phase 1 scripts from this folder, for example `python python/04_prepare_dataset.py ...`. See [`python/`](python/) and the main [README](../README.md#12-getting-started).
