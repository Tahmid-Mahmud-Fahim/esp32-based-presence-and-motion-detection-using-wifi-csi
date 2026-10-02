from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def get_metrics(y, pred, prob):
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
    ap = argparse.ArgumentParser(description="Train Phase-1 EMPTY/PERSON models.")
    ap.add_argument("--train", required=True)
    ap.add_argument("--val", required=True)
    ap.add_argument("--metadata", required=True)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    train = pd.read_csv(args.train)
    val = pd.read_csv(args.val)
    metadata = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
    features = metadata["feature_names"]

    missing = [c for c in features if c not in train.columns or c not in val.columns]
    if missing:
        raise ValueError(f"Missing feature columns: {missing}")

    X_train = train[features]
    y_train = train["y"].astype(int)
    X_val = val[features]
    y_val = val["y"].astype(int)

    models = {
        "logistic_regression": Pipeline([
            ("scaler", StandardScaler()),
            ("model", LogisticRegression(
                C=1.0,
                class_weight="balanced",
                max_iter=5000,
                random_state=42,
            )),
        ]),
        "random_forest": RandomForestClassifier(
            n_estimators=300,
            max_depth=5,
            min_samples_leaf=1,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        ),
    }

    results = {}
    fitted = {}

    for name, model in models.items():
        print(f"\nTraining {name}...")
        model.fit(X_train, y_train)
        prob = model.predict_proba(X_val)[:, 1]
        pred = (prob >= 0.5).astype(int)
        m = get_metrics(y_val, pred, prob)
        results[name] = m
        fitted[name] = model

        print(f"  accuracy          : {m['accuracy']:.6f}")
        print(f"  balanced_accuracy : {m['balanced_accuracy']:.6f}")
        print(f"  precision_person  : {m['precision_person']:.6f}")
        print(f"  recall_person     : {m['recall_person']:.6f}")
        print(f"  f1_person         : {m['f1_person']:.6f}")
        print(f"  macro_f1          : {m['macro_f1']:.6f}")
        print(f"  roc_auc           : {m['roc_auc']:.6f}")
        print(f"  confusion_matrix  : {m['confusion_matrix']}")

    # Select using validation macro-F1; balanced accuracy is the tie-breaker.
    best_name = max(
        results,
        key=lambda n: (results[n]["macro_f1"], results[n]["balanced_accuracy"]),
    )
    best_model = fitted[best_name]

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    model_path = outdir / "presence_model.joblib"
    joblib.dump(
        {
            "model": best_model,
            "model_name": best_name,
            "feature_names": features,
            "decision_threshold": 0.5,
        },
        model_path,
    )

    report = {
        "selection_rule": "highest validation macro-F1, balanced accuracy tie-break",
        "test_set_used_for_selection": False,
        "best_model": best_name,
        "decision_threshold": 0.5,
        "validation_results": results,
    }
    report_path = outdir / "model_selection.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n" + "=" * 72)
    print("MODEL SELECTION")
    print("=" * 72)
    print(f"Selected model : {best_name}")
    print("Test set       : NOT USED")
    print(f"Saved model    : {model_path}")
    print(f"Saved report   : {report_path}")


if __name__ == "__main__":
    main()
