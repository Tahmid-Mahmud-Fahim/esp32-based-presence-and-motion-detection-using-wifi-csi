from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

SCORE_COL = "cross_baseline_absmean_average"


def metrics(y, pred, score):
    return {
        "accuracy": float(accuracy_score(y, pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y, pred)),
        "precision_person": float(precision_score(y, pred, zero_division=0)),
        "recall_person": float(recall_score(y, pred, zero_division=0)),
        "f1_person": float(f1_score(y, pred, zero_division=0)),
        "macro_f1": float(f1_score(y, pred, average="macro", zero_division=0)),
        "roc_auc": float(roc_auc_score(y, score)),
        "confusion_matrix": confusion_matrix(y, pred).tolist(),
    }


def main():
    ap = argparse.ArgumentParser(description="Phase-1 simple threshold baseline.")
    ap.add_argument("--train", required=True)
    ap.add_argument("--val", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    train = pd.read_csv(args.train)
    val = pd.read_csv(args.val)

    if SCORE_COL not in train or SCORE_COL not in val:
        raise ValueError(f"Missing required score column: {SCORE_COL}")

    # The score itself is predetermined. Validation is used only to choose its threshold.
    values = np.sort(val[SCORE_COL].unique())
    thresholds = np.r_[
        values[0] - 1e-9,
        (values[:-1] + values[1:]) / 2.0,
        values[-1] + 1e-9,
    ]

    y = val["y"].to_numpy(dtype=int)
    score = val[SCORE_COL].to_numpy(dtype=float)

    best = None
    for t in thresholds:
        pred = (score >= t).astype(int)
        mf1 = f1_score(y, pred, average="macro", zero_division=0)
        bal = balanced_accuracy_score(y, pred)
        key = (mf1, bal)
        if best is None or key > best[0]:
            best = (key, float(t), pred)

    _, threshold, pred = best
    result = {
        "method": "single-feature threshold baseline",
        "score_feature": SCORE_COL,
        "decision_rule": f"PERSON if {SCORE_COL} >= threshold",
        "threshold": threshold,
        "validation": metrics(y, pred, score),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print("=" * 72)
    print("PHASE-1 THRESHOLD BASELINE")
    print("=" * 72)
    print(f"Score feature : {SCORE_COL}")
    print(f"Threshold     : {threshold:.9f}")
    print("\nValidation metrics:")
    for k, v in result["validation"].items():
        print(f"  {k}: {v}")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
