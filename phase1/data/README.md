# phase1/data

| Item | Contents |
| --- | --- |
| `manifest.csv` | One row per session: `session_id, label, split, rx1_csv, rx2_csv` (paths relative to `phase1/`) |
| [`raw/`](raw/) | Raw CSI recordings, one CSV per receiver per session |
| [`processed/`](processed/) | Feature tables, session summary, metadata and empty-room baseline produced by `04_prepare_dataset.py` |

The manifest defines the dataset and its **subject-wise split** (S01 train, S02 validation, S03 test; EMPTY sessions 5 / 2 / 2):

| Split | empty | person | Sessions |
| --- | ---: | ---: | ---: |
| train | 5 | 7 | 12 |
| val | 2 | 7 | 9 |
| test | 2 | 7 | 9 |

Raw files are never concatenated. Each session is aligned and windowed separately, then the feature rows are combined.
