# phase2/data/processed

Output of `python/03_prepare_phase2_dataset.py`: 33 sessions × 121 windows.

| File | Rows (windows) | Columns |
| --- | ---: | ---: |
| `all_features.csv` | 3,993 | 80 |
| `train_features.csv` | 1,573 | 80 |
| `val_features.csv` | 1,210 | 80 |
| `test_features.csv` | 1,210 | 80 |

- **Features:** 75 per window: the 31 Phase 1 presence features plus 44 motion features (18 per receiver + 8 cross-receiver).
- **Other columns:** `session_id`, `label`, `split`, `y`, `window_center_s`.

| File | Contents |
| --- | --- |
| `session_summary.csv` | Label, split and window count for every session |
| `metadata.json` | Processing settings, feature names and split definition |
| `phase2_empty_baseline.npz` | Empty-room baseline from the Phase 2 training EMPTY sessions |
