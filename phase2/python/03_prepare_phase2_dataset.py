from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[2]   # Micro_Project_Final_Try_1
PHASE1_ROOT = PROJECT_ROOT / "phase1"

sys.path.insert(0, str(PHASE1_ROOT))
sys.path.insert(0, str(THIS_FILE.parent))

from presence.csi_utils import (
    align_dual_rx,
    extract_window_features,
    fit_empty_baseline,
    save_baseline,
    window_slices,
)
from phase2_utils import MOTION_FEATURE_NAMES, extract_motion_features

RX_BASE_NAMES = [
    "mean_profile_mean","mean_profile_std","mean_profile_median",
    "temporal_std_mean","temporal_std_median","temporal_std_max",
    "temporal_absdiff_mean","temporal_diff_std",
    "baseline_abs_mean","baseline_abs_median","baseline_abs_max",
    "baseline_rmse","baseline_corr",
]

BASE_FEATURE_NAMES = (
    [f"rx1_{x}" for x in RX_BASE_NAMES]
    + [f"rx2_{x}" for x in RX_BASE_NAMES]
    + [
        "cross_baseline_absmean_difference",
        "cross_baseline_absmean_average",
        "cross_baseline_absmean_max",
        "cross_motion_absdiff_average",
        "cross_motion_absdiff_max",
    ]
)

ALL_FEATURE_NAMES = BASE_FEATURE_NAMES + MOTION_FEATURE_NAMES
LABEL_TO_Y = {"empty": 0, "static": 1, "moving": 2}

def resolve_path(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()

def read_manifest(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    need = {"session_id","label","split","rx1_csv","rx2_csv"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"Manifest missing columns: {sorted(missing)}")
    df["label"] = df["label"].str.lower().str.strip()
    df["split"] = df["split"].str.lower().str.strip()
    if (~df["label"].isin(LABEL_TO_Y)).any():
        raise ValueError("Labels must be empty/static/moving")
    if (~df["split"].isin(["train","val","test"])).any():
        raise ValueError("Splits must be train/val/test")
    return df

def main():
    ap = argparse.ArgumentParser(description="Prepare Phase-2 features.")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fs", type=float, default=25.0)
    ap.add_argument("--window", type=float, default=2.0)
    ap.add_argument("--step", type=float, default=0.5)
    args = ap.parse_args()

    manifest_path = Path(args.manifest).resolve()
    outdir = Path(args.out).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    df = read_manifest(manifest_path).copy()
    df["rx1_resolved"] = df["rx1_csv"].map(lambda x: str(resolve_path(x)))
    df["rx2_resolved"] = df["rx2_csv"].map(lambda x: str(resolve_path(x)))

    missing_files = []
    for r in df.itertuples(index=False):
        for p in (r.rx1_resolved, r.rx2_resolved):
            if not Path(p).is_file():
                missing_files.append(p)
    if missing_files:
        print("Missing files:")
        for p in missing_files:
            print(" ", p)
        raise SystemExit(2)

    train_empty = df[(df["split"]=="train") & (df["label"]=="empty")]
    train_empty_pairs = [(r.rx1_resolved, r.rx2_resolved) for r in train_empty.itertuples(index=False)]

    print("="*82)
    print("PHASE-2 DATASET PREPARATION")
    print("="*82)
    print(f"Sessions      : {len(df)}")
    print(f"Base features : {len(BASE_FEATURE_NAMES)}")
    print(f"Motion feats  : {len(MOTION_FEATURE_NAMES)}")
    print(f"Total features: {len(ALL_FEATURE_NAMES)}")

    print("\n[1/3] Fitting baseline from TRAIN EMPTY only...")
    baseline = fit_empty_baseline(train_empty_pairs, fs=args.fs)
    save_baseline(outdir/"phase2_empty_baseline.npz", baseline)

    print("[2/3] Extracting windows/features...")
    blocks, session_summary = [], []

    for i, r in enumerate(df.itertuples(index=False), 1):
        grid, A1, A2 = align_dual_rx(r.rx1_resolved, r.rx2_resolved, fs=args.fs)
        feats, centers = [], []

        for sl in window_slices(len(grid), args.fs, args.window, args.step):
            W1, W2 = A1[sl], A2[sl]
            bf = extract_window_features(W1, W2, baseline)
            mf = extract_motion_features(W1, W2, fs=args.fs)
            f = np.concatenate([bf, mf]).astype(np.float32)
            if len(f) != len(ALL_FEATURE_NAMES):
                raise RuntimeError(f"{r.session_id}: wrong feature count")
            feats.append(f)
            centers.append(float(np.mean(grid[sl])))

        X = np.vstack(feats)
        block = pd.DataFrame(X, columns=ALL_FEATURE_NAMES)
        block.insert(0, "window_center_s", centers)
        block.insert(0, "y", LABEL_TO_Y[r.label])
        block.insert(0, "split", r.split)
        block.insert(0, "label", r.label)
        block.insert(0, "session_id", r.session_id)
        blocks.append(block)

        session_summary.append({
            "session_id": r.session_id, "label": r.label,
            "split": r.split, "windows": len(block)
        })

        print(
            f"[{i:02d}/{len(df):02d}] {r.session_id:<28} "
            f"{r.split:<5} {r.label:<6} windows={len(block)}"
        )

    all_df = pd.concat(blocks, ignore_index=True)

    print("[3/3] Saving...")
    all_df.to_csv(outdir/"all_features.csv", index=False)

    split_counts = {}
    for split in ("train","val","test"):
        part = all_df[all_df["split"]==split].reset_index(drop=True)
        part.to_csv(outdir/f"{split}_features.csv", index=False)
        split_counts[split] = {
            "sessions": int(part["session_id"].nunique()),
            "windows": int(len(part)),
            "empty": int((part["label"]=="empty").sum()),
            "static": int((part["label"]=="static").sum()),
            "moving": int((part["label"]=="moving").sum()),
        }

    pd.DataFrame(session_summary).to_csv(outdir/"session_summary.csv", index=False)

    metadata = {
        "fs_hz": args.fs,
        "window_s": args.window,
        "step_s": args.step,
        "label_to_y": LABEL_TO_Y,
        "base_feature_names": BASE_FEATURE_NAMES,
        "motion_feature_names": MOTION_FEATURE_NAMES,
        "all_feature_names": ALL_FEATURE_NAMES,
        "feature_count": len(ALL_FEATURE_NAMES),
        "baseline_source": "TRAIN EMPTY only",
        "train_empty_sessions": train_empty["session_id"].tolist(),
        "split_counts": split_counts,
    }
    (outdir/"metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print("\nDONE")
    for split, c in split_counts.items():
        print(
            f"{split.upper():5}: sessions={c['sessions']:2d}, windows={c['windows']:4d}, "
            f"empty={c['empty']:4d}, static={c['static']:4d}, moving={c['moving']:4d}"
        )

if __name__ == "__main__":
    main()
