# phase2: motion detection and the final live system

Phase 2 extends presence detection to three states: **EMPTY**, **PERSON-STATIC** and **PERSON-MOVING**. It contains the final phone-controlled live system.

**What it reuses from [`phase1/`](../phase1/):**
- the firmware;
- the capture script;
- `presence/csi_utils.py`;
- the presence model;
- all EMPTY, STATIC and `normal_walk` recordings, read in place from `phase1/data/raw/`.

**New data:** 9 walking sessions (S01–S03 × `slow_walk`, `walk_left_right`, `walk_tx_rx`) in `data/raw_new/`.

| Item | Contents |
| --- | --- |
| [`python/`](python/) | Scripts 00–08 and `phase2_utils.py` (44 motion features) |
| [`data/`](data/) | `manifest.csv`, new recordings (`raw_new/`) and feature tables (`processed/`) |
| [`models/`](models/) | Motion model, direct three-class model and selection record |
| [`reports/`](reports/) | Quality check of the new data and the test results |
| `01_collect_phase2.ps1` | PowerShell script used to record the 9 walking sessions |
| `manifest_phase2.csv` | Original copy of the Phase 2 manifest (identical to `data/manifest.csv`) |
| `phase2_collection_plan.csv` | Instructions given to each subject for the walking sessions |
| `requirements_phase2.txt` | Original Python requirements (unpinned; see the root `requirements.txt`) |
| `README_PHASE2.txt`, `README_PHASE2_FINAL.txt` | Original working notes of the Phase 2 design |

**Phase 2 dataset:** 33 sessions, split by subject.

| Split | empty | moving | static | Sessions |
| --- | ---: | ---: | ---: | ---: |
| train | 5 | 4 | 4 | 13 |
| val | 2 | 4 | 4 | 10 |
| test | 2 | 4 | 4 | 10 |

**Held-out test results (subject S03):**
- cascade (deployed): 93.14% window accuracy, macro-F1 0.9421;
- direct three-class logistic regression: 91.98%, macro-F1 0.9227;
- 10/10 sessions correct by majority vote for both.

Run the Phase 2 pipeline scripts from `phase2/python/`. Run the final phone app from the repository root (see the main [README](../README.md#124-run-the-live-demo-final-system)).
