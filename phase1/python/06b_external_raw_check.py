from __future__ import annotations

import argparse
import sys
from pathlib import Path

import joblib
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from presence.csi_utils import load_baseline, session_features


def main():
    ap = argparse.ArgumentParser(
        description="External raw-session sanity check using the frozen Phase-1 model."
    )
    ap.add_argument("--rx1", required=True)
    ap.add_argument("--rx2", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--expected", choices=["empty", "person"], default=None)
    ap.add_argument("--fs", type=float, default=25.0)
    ap.add_argument("--window", type=float, default=2.0)
    ap.add_argument("--step", type=float, default=0.5)
    args = ap.parse_args()

    baseline = load_baseline(args.baseline)
    bundle = joblib.load(args.model)

    X, centers = session_features(
        args.rx1,
        args.rx2,
        baseline,
        fs=args.fs,
        window_s=args.window,
        step_s=args.step,
    )

    expected_feature_count = len(bundle["feature_names"])
    if X.shape[1] != expected_feature_count:
        raise ValueError(
            f"Feature-count mismatch: model expects {expected_feature_count}, "
            f"but raw session produced {X.shape[1]}"
        )

    model = bundle["model"]
    threshold = float(bundle.get("decision_threshold", 0.5))
    prob = model.predict_proba(X)[:, 1]
    pred = (prob >= threshold).astype(int)

    person_fraction = float(pred.mean())
    mean_prob = float(prob.mean())
    median_prob = float(np.median(prob))
    max_prob = float(prob.max())

    session_pred = "person" if mean_prob >= threshold else "empty"

    print("=" * 72)
    print("FROZEN-MODEL EXTERNAL RAW SESSION CHECK")
    print("=" * 72)
    print(f"Model              : {bundle.get('model_name', 'unknown')}")
    print(f"Decision threshold : {threshold:.3f}")
    print(f"Windows            : {len(pred)}")
    print(f"Mean PERSON prob   : {mean_prob:.6f}")
    print(f"Median PERSON prob : {median_prob:.6f}")
    print(f"Max PERSON prob    : {max_prob:.6f}")
    print(f"PERSON windows     : {int(pred.sum())}/{len(pred)} ({100*person_fraction:.2f}%)")
    print(f"Session prediction : {session_pred.upper()}")

    if args.expected is not None:
        expected_y = 0 if args.expected == "empty" else 1
        window_acc = float((pred == expected_y).mean())
        session_ok = session_pred == args.expected
        print(f"Expected            : {args.expected.upper()}")
        print(f"Window agreement    : {100*window_acc:.2f}%")
        print(f"Session correct     : {'YES' if session_ok else 'NO'}")


if __name__ == "__main__":
    main()
