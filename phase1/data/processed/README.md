# phase1/data/processed

Output of `python/04_prepare_dataset.py` (25 Hz grid, 2 s windows, 0.48 s hop, so 121 windows per session).

| File | Rows (windows) | Columns |
| --- | ---: | ---: |
| `all_features.csv` | 3,630 | 36 |
| `train_features.csv` | 1,452 | 36 |
| `val_features.csv` | 1,089 | 36 |
| `test_features.csv` | 1,089 | 36 |

- **Features:** 31 per window, 13 per receiver (`rx1_…`, `rx2_…`) plus 5 cross-receiver (`cross_…`). They describe the spectral profile, temporal variation and deviation from the empty-room baseline.
- **Other columns:** `session_id`, `label`, `split`, `y`, `window_center_s`.

| File | Contents |
| --- | --- |
| `session_summary.csv` | Label, split and window count for every session |
| `metadata.json` | Processing settings (sampling rate, window, step, feature names, split) |
| `empty_baseline.npz` | Training empty-room baseline (median profile per receiver from the 5 training EMPTY sessions); used by the live scripts as a reference |
