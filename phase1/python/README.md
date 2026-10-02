# phase1/python

Numbered scripts for Phase 1. Run them **from the `phase1/` folder**, for example `python python/00_list_ports.py`. Every script prints its options with `--help`.

| Script | Purpose |
| --- | --- |
| `00_list_ports.py` | List the serial ports of the connected boards |
| `01_capture_dual_rx.py` | Record RX1 and RX2 at the same time into `<label>_RX1.csv` and `<label>_RX2.csv` (countdown, duration). No camera, no video |
| `01b_capture_from_plan.py` | Record many sessions in a row from a plan CSV (columns `session_id, duration_s, label, split, subject, scenario, notes`); the plan file itself is not included |
| `02_validate_capture.py` | Quality check of a recorded pair: rows, duration, packet rate, sequence gaps, CSI length |
| `03_compare_empty_person.py` | Sanity plot of an EMPTY versus a PERSON recording, with RMSE (`reports/empty_vs_person.png`) |
| `04_prepare_dataset.py` | Manifest → aligned, normalised, windowed **31-feature** tables, empty-room baseline and metadata (`data/processed/`) |
| `05a_threshold_baseline.py` | Single-feature threshold baseline (validation only) |
| `05_train_presence.py` | Train logistic regression and random forest, select on validation, save `models/presence_model.joblib` |
| `06_evaluate_test.py` | One-time evaluation on the untouched test subject → `reports/test_results.json` |
| `06b_external_raw_check.py` | Run the model on an extra raw RX1/RX2 recording, optionally against an expected label |
| `07_live_presence.py` | Live EMPTY/PERSON in the terminal: 5 s countdown, 12 s empty calibration, 2 s windows, 5-window vote |
| `08_phase6_phone_control_integrated.py` | Phase 1 live detector with the phone dashboard (START/STOP) |
| `PHASE6_PHONE_CONTROL_README.txt` | Original notes for the Phase 1 phone control |

Example run (from `phase1/`):

```bash
python python/01_capture_dual_rx.py --rx1 COM6 --rx2 COM8 --label S04_stand_center --duration 60 --countdown 5 --out data/raw
python python/04_prepare_dataset.py --manifest data/manifest.csv --out data/processed --fs 25 --window 2.0 --step 0.5
python python/05_train_presence.py --train data/processed/train_features.csv --val data/processed/val_features.csv --metadata data/processed/metadata.json --outdir models
python python/06_evaluate_test.py --test data/processed/test_features.csv --model models/presence_model.joblib --out reports/test_results.json
python python/07_live_presence.py --rx1 COM6 --rx2 COM8 --model models/presence_model.joblib --training-baseline data/processed/empty_baseline.npz
```

The final live system with motion detection is in [`../../phase2/python/`](../../phase2/python/).
