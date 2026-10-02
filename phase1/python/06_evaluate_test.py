from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
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


def metrics(y, pred, prob):
    return {
        "accuracy": float(accuracy_score(y, pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y, pred)),
        "precision_person": float(precision_score(y, pred, zero_division=0)),
        "recall_person": float(recall_score(y, pred, zero_division=0)),
        "f1_person": float(f1_score(y, pred, zero_division=0)),
        "macro_f1": float(f1_score(y, pred, average="macro", zero_division=0)),
        "roc_auc": float(roc_auc_score(y, prob)),
        "confusion_matrix": confusion_matrix(y, pred).tolist(),
    }


def main():
    ap = argparse.ArgumentParser(description="One-time Phase-1 untouched test evaluation.")
    ap.add_argument("--test", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    test = pd.read_csv(args.test)
    bundle = joblib.load(args.model)
    model = bundle["model"]
    features = bundle["feature_names"]
    threshold = float(bundle.get("decision_threshold", 0.5))

    X = test[features]
    y = test["y"].astype(int).to_numpy()

    prob = model.predict_proba(X)[:, 1]
    pred = (prob >= threshold).astype(int)

    window_metrics = metrics(y, pred, prob)

    # Session-level result using mean window probability.
    sess = test[["session_id", "label", "y"]].copy()
    sess["prob_person"] = prob
    session_table = (
        sess.groupby(["session_id", "label", "y"], as_index=False)["prob_person"]
        .mean()
    )
    session_table["pred"] = (session_table["prob_person"] >= threshold).astype(int)
    session_metrics = metrics(
        session_table["y"].to_numpy(),
        session_table["pred"].to_numpy(),
        session_table["prob_person"].to_numpy(),
    )

    result = {
        "model_name": bundle.get("model_name", "unknown"),
        "decision_threshold": threshold,
        "window_level": window_metrics,
        "session_level": session_metrics,
        "sessions": session_table.to_dict(orient="records"),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print("=" * 72)
    print("PHASE-1 UNTOUCHED TEST EVALUATION")
    print("=" * 72)
    print(f"Model: {result['model_name']}")
    print("\nWindow-level:")
    for k, v in window_metrics.items():
        print(f"  {k}: {v}")

    print("\nSession-level:")
    for k, v in session_metrics.items():
        print(f"  {k}: {v}")

    print("\nPer-session mean PERSON probability:")
    print(session_table.to_string(index=False))
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
