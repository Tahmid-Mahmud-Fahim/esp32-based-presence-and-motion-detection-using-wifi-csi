PHASE 2 FINAL PACKAGE
=====================

Target:
  EMPTY / PERSON STATIC / PERSON MOVING

IMPORTANT: DO NOT CONCATENATE RAW CSV FILES.
--------------------------------------------
Keep every RX1/RX2 session as a separate file.

Phase-2 uses:
  - Phase-1 EMPTY sessions directly from phase1/data/raw
  - Phase-1 STATIC sessions directly from phase1/data/raw
  - Phase-1 normal_walk sessions directly from phase1/data/raw
  - 9 new Phase-2 walking sessions from phase2/data/raw_new

The manifest combines them LOGICALLY. The dataset-preparation script opens each
session separately, aligns RX1/RX2, preprocesses it, windows it, extracts
features, then concatenates the resulting feature rows into train/val/test CSVs.

Expected project layout
-----------------------
Micro_Project_Final_Try_1/
  phase1/
    data/raw/
    models/presence_model.joblib
    presence/csi_utils.py
    python/01_capture_dual_rx.py

  phase2/
    manifest_phase2.csv
    phase2_collection_plan.csv
    01_collect_phase2.ps1
    data/
      manifest.csv
      raw_new/
      processed/
    models/
    reports/
    python/
      00_setup_phase2.py
      phase2_utils.py
      02_validate_phase2_new.py
      03_prepare_phase2_dataset.py
      04_train_phase2_models.py
      05_evaluate_phase2_test.py
      06_live_phase2.py

Final 33-session design
-----------------------
EMPTY = 9
STATIC = 12
MOVING = 12
TOTAL = 33

STATIC scenarios used from Phase 1:
  stand_center
  sit_center
  stand_left
  stand_right

MOVING per subject:
  normal_walk          (existing Phase 1)
  slow_walk            (new Phase 2)
  walk_left_right      (new Phase 2)
  walk_tx_rx           (new Phase 2)

Split:
  S01 -> train
  S02 -> validation
  S03 -> untouched test

EMPTY split stays:
  train: empty_01, empty_03, empty_05, empty_06, empty_08
  val:   empty_02, empty_07
  test:  empty_04, empty_09

STEP 0 - Setup
--------------
Place this package contents inside phase2, then from phase2/python:

  python 00_setup_phase2.py

This creates folders and copies:
  phase2/manifest_phase2.csv
to:
  phase2/data/manifest.csv

STEP 1 - Put new raw data here
------------------------------
phase2/data/raw_new/

Exact expected names:
  S01_slow_walk_RX1.csv
  S01_slow_walk_RX2.csv
  S01_walk_left_right_RX1.csv
  S01_walk_left_right_RX2.csv
  S01_walk_tx_rx_RX1.csv
  S01_walk_tx_rx_RX2.csv

  S02_slow_walk_RX1.csv
  S02_slow_walk_RX2.csv
  S02_walk_left_right_RX1.csv
  S02_walk_left_right_RX2.csv
  S02_walk_tx_rx_RX1.csv
  S02_walk_tx_rx_RX2.csv

  S03_slow_walk_RX1.csv
  S03_slow_walk_RX2.csv
  S03_walk_left_right_RX1.csv
  S03_walk_left_right_RX2.csv
  S03_walk_tx_rx_RX1.csv
  S03_walk_tx_rx_RX2.csv

If Windows/browser has added "(1)" or "(2)" to filenames, rename them back to
the exact names above before running the scripts.

STEP 2 - QC
-----------
From phase2/python:

  python 02_validate_phase2_new.py --raw ..\data\raw_new --out ..\reports\new_data_qc.csv

Do not continue unless:
  OVERALL: PASS

STEP 3 - Prepare complete Phase-2 feature dataset
--------------------------------------------------
  python 03_prepare_phase2_dataset.py --manifest ..\data\manifest.csv --out ..\data\processed --fs 25 --window 2.0 --step 0.5

This is where the data is merged at FEATURE level.

Outputs:
  all_features.csv
  train_features.csv
  val_features.csv
  test_features.csv
  session_summary.csv
  metadata.json
  phase2_empty_baseline.npz

STEP 4 - Train only with TRAIN and select on VALIDATION
--------------------------------------------------------
  python 04_train_phase2_models.py --train ..\data\processed\train_features.csv --val ..\data\processed\val_features.csv --metadata ..\data\processed\metadata.json --presence-model ..\..\phase1\models\presence_model.joblib --outdir ..\models

Outputs:
  motion_model.joblib
  direct3_model.joblib
  phase2_model_selection.json

The script compares:
  A) Hierarchical: Phase-1 presence -> STATIC/MOVING
  B) Direct three-class: EMPTY/STATIC/MOVING

The untouched S03 test set is not used here.

STEP 5 - Final TEST once
------------------------
Only after Step 4 is complete:

  python 05_evaluate_phase2_test.py --test ..\data\processed\test_features.csv --presence-model ..\..\phase1\models\presence_model.joblib --motion-model ..\models\motion_model.joblib --direct-model ..\models\direct3_model.joblib --selection ..\models\phase2_model_selection.json --out ..\reports\test_results_phase2.json

Do not tune using S03 after seeing this result.

STEP 6 - Live detector
----------------------
After offline test is accepted:

  python 06_live_phase2.py --rx1 COM7 --rx2 COM5 --presence-model ..\..\phase1\models\presence_model.joblib --motion-model ..\models\motion_model.joblib

Live flow:
  startup EMPTY calibration
        ->
  Phase-1 presence model
        ->
  EMPTY, or if PERSON:
        ->
  Phase-2 motion model
        ->
  STATIC / MOVING

RAW DATA MERGING RULE
---------------------
DO NOT:
  - concatenate RX1 files together
  - concatenate RX2 files together
  - join different sessions into one raw CSV
  - mix train/val/test raw files manually
  - copy S03 data into training

DO:
  - preserve one RX1 + one RX2 CSV per session
  - let manifest.csv point to every raw pair
  - let 03_prepare_phase2_dataset.py perform the feature-level merge automatically
