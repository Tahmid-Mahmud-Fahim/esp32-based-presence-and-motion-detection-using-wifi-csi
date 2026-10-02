# phase2/python

Run the pipeline scripts **from this folder**, for example `python 03_prepare_phase2_dataset.py ...`. Run the final phone app from the repository root. Every script prints its options with `--help`.

| Script | Purpose |
| --- | --- |
| `00_setup_phase2.py` | Create the Phase 2 folders and copy `manifest_phase2.csv` to `data/manifest.csv` |
| `02_validate_phase2_new.py` | Quality check of the 9 new walking sessions → `../reports/new_data_qc.csv` |
| `03_prepare_phase2_dataset.py` | Manifest (33 sessions) → **75-feature** tables: 31 presence + 44 motion features |
| `04_train_phase2_models.py` | Train and select the motion model (STATIC vs MOVING, 44 features) and the direct three-class model (75 features) |
| `05_evaluate_phase2_test.py` | One-time test of the cascade and the direct model → `../reports/test_results_phase2.json` |
| `06_live_phase2.py` | Live cascade in the terminal |
| `07_live_phase2_dual_timescale.py` | Experimental lower-latency variant (fast 0.6 s motion path + 2 s models) |
| `08_live_phase2_direct3.py` | Live direct three-class model, for comparison |
| `08_phase2_phone_control.py` | Earlier phone-controlled version (Phase 2 voting started after a stable Phase 1 vote) |
| **`08_phase2_phone_control_FINAL_NO_CASCADE_LAG.py`** | **Final system:** phone dashboard, start-up calibration, presence and motion voting in parallel |
| `phase2_utils.py` | `extract_motion_features()`: the 44 baseline-free motion features (18 per receiver + 8 cross-receiver) |

**Pipeline** (from this folder):

```bash
python 02_validate_phase2_new.py --raw ../data/raw_new --out ../reports/new_data_qc.csv
python 03_prepare_phase2_dataset.py --manifest ../data/manifest.csv --out ../data/processed --fs 25 --window 2.0 --step 0.5
python 04_train_phase2_models.py --train ../data/processed/train_features.csv --val ../data/processed/val_features.csv --metadata ../data/processed/metadata.json --presence-model ../../phase1/models/presence_model.joblib --outdir ../models
python 05_evaluate_phase2_test.py --test ../data/processed/test_features.csv --presence-model ../../phase1/models/presence_model.joblib --motion-model ../models/motion_model.joblib --direct-model ../models/direct3_model.joblib --selection ../models/phase2_model_selection.json --out ../reports/test_results_phase2.json
```

**Final live system** (from the repository root):

```bash
python phase2/python/08_phase2_phone_control_FINAL_NO_CASCADE_LAG.py --rx1 COM6 --rx2 COM8 --presence-model phase1/models/presence_model.joblib --motion-model phase2/models/motion_model.joblib --training-baseline phase1/data/processed/empty_baseline.npz --host 0.0.0.0 --port 8080
```

Then open `http://<laptop-IP>:8080` on a phone in the same local network.
