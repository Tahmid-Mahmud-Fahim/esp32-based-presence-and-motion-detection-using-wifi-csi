PHASE 2 CODE BUNDLE — WALKING-ONLY MOVING DATASET
=================================================

Goal:
  EMPTY / PERSON STATIC / PERSON MOVING

MOVING definition for this dataset:
  locomotion/walking movement.

REUSE FROM PHASE 1
------------------
- ESP32 TX/RX firmware
- phase1/python/01_capture_dual_rx.py
- phase1/presence/csi_utils.py
- phase1/models/presence_model.joblib
- existing EMPTY / STATIC / normal_walk recordings

NEW DATA
--------
9 x 60-second MOVING sessions:

S01_slow_walk
S01_walk_left_right
S01_walk_tx_rx

S02_slow_walk
S02_walk_left_right
S02_walk_tx_rx

S03_slow_walk
S03_walk_left_right
S03_walk_tx_rx

Each subject therefore has four MOVING sessions total when the existing
Phase-1 normal_walk recording is included:
  normal_walk
  slow_walk
  walk_left_right
  walk_tx_rx

The final Phase-2 dataset contains:
  9 EMPTY
  12 STATIC
  12 MOVING
  = 33 sessions

FILES
-----
manifest_phase2.csv
phase2_collection_plan.csv
python/phase2_utils.py
python/02_validate_phase2_new.py
python/03_prepare_phase2_dataset.py
python/04_train_phase2_models.py
python/05_evaluate_phase2_test.py
python/06_live_phase2.py

DO NOT RUN PREPARATION/TRAINING UNTIL THE 9 NEW SESSIONS ARE COLLECTED.

After collection, from phase2/python:

1) QC
python 02_validate_phase2_new.py --raw ..\data\raw_new --out ..\reports\new_data_qc.csv

2) Prepare
python 03_prepare_phase2_dataset.py --manifest ..\data\manifest.csv --out ..\data\processed --fs 25 --window 2.0 --step 0.5

3) Train/validation
python 04_train_phase2_models.py --train ..\data\processed\train_features.csv --val ..\data\processed\val_features.csv --metadata ..\data\processed\metadata.json --presence-model ..\..\phase1\models\presence_model.joblib --outdir ..\models

4) Test once
python 05_evaluate_phase2_test.py --test ..\data\processed\test_features.csv --presence-model ..\..\phase1\models\presence_model.joblib --motion-model ..\models\motion_model.joblib --direct-model ..\models\direct3_model.joblib --selection ..\models\phase2_model_selection.json --out ..\reports\test_results_phase2.json

5) Live
python 06_live_phase2.py --rx1 COM6 --rx2 COM8 --presence-model ..\..\phase1\models\presence_model.joblib --motion-model ..\models\motion_model.joblib
