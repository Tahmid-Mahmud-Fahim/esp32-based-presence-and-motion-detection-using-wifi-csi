from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

# This script is expected at: phase1/python/04_prepare_dataset.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from presence.csi_utils import (
    fit_empty_baseline,
    read_manifest,
    save_baseline,
    session_features,
)


RX_FEATURE_NAMES = [
    "mean_profile_mean",
    "mean_profile_std",
    "mean_profile_median",
    "temporal_std_mean",
    "temporal_std_median",
    "temporal_std_max",
    "temporal_absdiff_mean",
    "temporal_diff_std",
    "baseline_abs_mean",
    "baseline_abs_median",
    "baseline_abs_max",
    "baseline_rmse",
    "baseline_corr",
]

FEATURE_NAMES = (
    [f"rx1_{x}" for x in RX_FEATURE_NAMES]
    + [f"rx2_{x}" for x in RX_FEATURE_NAMES]
    + [
        "cross_baseline_absmean_difference",
        "cross_baseline_absmean_average",
        "cross_baseline_absmean_max",
        "cross_motion_absdiff_average",
        "cross_motion_absdiff_max",
    ]
)


def resolve_input_path(value: str) -> Path:
    """Resolve manifest paths against the Phase-1 project root."""
    p = Path(value)
    if p.is_absolute():
        return p
    return (PROJECT_ROOT / p).resolve()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Prepare the Phase-1 EMPTY/PERSON feature dataset."
    )
    ap.add_argument("--manifest", required=True, help="Path to manifest.csv")
    ap.add_argument("--out", required=True, help="Output directory")
    ap.add_argument("--fs", type=float, default=25.0)
    ap.add_argument("--window", type=float, default=2.0)
    ap.add_argument("--step", type=float, default=0.5)
    args = ap.parse_args()

    manifest_path = Path(args.manifest).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    df = read_manifest(manifest_path).copy()

    # Resolve and verify every raw CSV before doing any expensive processing.
    df["rx1_resolved"] = df["rx1_csv"].map(lambda x: str(resolve_input_path(x)))
    df["rx2_resolved"] = df["rx2_csv"].map(lambda x: str(resolve_input_path(x)))

    missing = []
    for r in df.itertuples(index=False):
        if not Path(r.rx1_resolved).is_file():
            missing.append(r.rx1_resolved)
        if not Path(r.rx2_resolved).is_file():
            missing.append(r.rx2_resolved)

    if missing:
        print("\nERROR: Missing raw files:")
        for p in missing:
            print("  ", p)
        raise SystemExit(2)

    # Absolutely no leakage: the empty baseline is fitted from TRAIN EMPTY only.
    train_empty = df[(df["split"] == "train") & (df["label"] == "empty")]
    if train_empty.empty:
        raise ValueError("Manifest contains no TRAIN EMPTY sessions.")

    train_empty_pairs = [
        (r.rx1_resolved, r.rx2_resolved)
        for r in train_empty.itertuples(index=False)
    ]

    print("=" * 78)
    print("PHASE-1 DATASET PREPARATION")
    print("=" * 78)
    print(f"Project root : {PROJECT_ROOT}")
    print(f"Manifest     : {manifest_path}")
    print(f"Output       : {out_dir}")
    print(f"Sessions     : {len(df)}")
    print(f"Resample fs  : {args.fs} Hz")
    print(f"Window       : {args.window} s")
    print(f"Step target  : {args.step} s")
    print(f"Train EMPTY  : {len(train_empty_pairs)} sessions")
    print()

    print("[1/3] Fitting EMPTY baseline from TRAIN EMPTY only...")
    baseline = fit_empty_baseline(train_empty_pairs, fs=args.fs)
    baseline_path = out_dir / "empty_baseline.npz"
    save_baseline(baseline_path, baseline)
    print(f"      Saved: {baseline_path}")
    print(f"      RX1 baseline dimension: {len(baseline['rx1'])}")
    print(f"      RX2 baseline dimension: {len(baseline['rx2'])}")

    print("\n[2/3] Extracting window features...")
    all_frames = []
    summary_rows = []

    for i, r in enumerate(df.itertuples(index=False), start=1):
        X, centers = session_features(
            r.rx1_resolved,
            r.rx2_resolved,
            baseline,
            fs=args.fs,
            window_s=args.window,
            step_s=args.step,
        )

        if X.shape[1] != len(FEATURE_NAMES):
            raise ValueError(
                f"{r.session_id}: expected {len(FEATURE_NAMES)} features, "
                f"got {X.shape[1]}"
            )

        block = pd.DataFrame(X, columns=FEATURE_NAMES)
        block.insert(0, "window_center_s", centers)
        block.insert(0, "y", 0 if r.label == "empty" else 1)
        block.insert(0, "split", r.split)
        block.insert(0, "label", r.label)
        block.insert(0, "session_id", r.session_id)
        all_frames.append(block)

        summary_rows.append(
            {
                "session_id": r.session_id,
                "label": r.label,
                "split": r.split,
                "windows": len(block),
            }
        )

        print(
            f"      [{i:02d}/{len(df):02d}] "
            f"{r.session_id:<28} {r.split:<5} {r.label:<6} "
            f"windows={len(block)}"
        )

    features = pd.concat(all_frames, ignore_index=True)

    print("\n[3/3] Saving prepared dataset...")
    all_path = out_dir / "all_features.csv"
    features.to_csv(all_path, index=False)

    split_counts = {}
    for split in ("train", "val", "test"):
        part = features[features["split"] == split].reset_index(drop=True)
        p = out_dir / f"{split}_features.csv"
        part.to_csv(p, index=False)
        split_counts[split] = {
            "windows": int(len(part)),
            "empty_windows": int((part["y"] == 0).sum()),
            "person_windows": int((part["y"] == 1).sum()),
            "sessions": int(part["session_id"].nunique()),
        }

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(out_dir / "session_summary.csv", index=False)

    metadata = {
        "fs_hz": args.fs,
        "window_s": args.window,
        "requested_step_s": args.step,
        "feature_count": len(FEATURE_NAMES),
        "baseline_source": "TRAIN EMPTY sessions only",
        "train_empty_sessions": train_empty["session_id"].tolist(),
        "split_counts": split_counts,
        "feature_names": FEATURE_NAMES,
    }
    (out_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    print("\n" + "=" * 78)
    print("DONE")
    print("=" * 78)
    print(f"Features per window: {len(FEATURE_NAMES)}")
    for split in ("train", "val", "test"):
        c = split_counts[split]
        print(
            f"{split.upper():5} : sessions={c['sessions']:2d}, "
            f"windows={c['windows']:4d}, "
            f"empty={c['empty_windows']:4d}, "
            f"person={c['person_windows']:4d}"
        )

    print("\nCreated:")
    for name in [
        "empty_baseline.npz",
        "all_features.csv",
        "train_features.csv",
        "val_features.csv",
        "test_features.csv",
        "session_summary.csv",
        "metadata.json",
    ]:
        print("  ", out_dir / name)


if __name__ == "__main__":
    main()
