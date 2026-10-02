# phase2/data

| Item | Contents |
| --- | --- |
| `manifest.csv` | One row per session: `session_id, label, split, rx1_csv, rx2_csv` (paths relative to the repository root) |
| [`raw_new/`](raw_new/) | The 9 new walking sessions recorded for Phase 2 |
| [`processed/`](processed/) | Feature tables produced by `python/03_prepare_phase2_dataset.py` |

The manifest combines **existing Phase 1 recordings**, read in place from `phase1/data/raw/`, with the **new walking sessions** in `raw_new/`. No raw file is copied or concatenated:
- 9 EMPTY sessions;
- 12 STATIC sessions (`stand_center`, `stand_left`, `stand_right`, `sit_center` × 3 subjects);
- 12 MOVING sessions (`normal_walk`, `slow_walk`, `walk_left_right`, `walk_tx_rx` × 3 subjects).

| Split | empty | moving | static | Sessions |
| --- | ---: | ---: | ---: | ---: |
| train | 5 | 4 | 4 | 13 |
| val | 2 | 4 | 4 | 10 |
| test | 2 | 4 | 4 | 10 |
