from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

def metrics(y, pred, labels):
    return {
        "accuracy": float(accuracy_score(y, pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y, pred)),
        "macro_f1": float(f1_score(y, pred, average="macro", zero_division=0)),
        "confusion_matrix": confusion_matrix(y, pred, labels=labels).tolist(),
    }

def candidates():
    return {
        "logistic_regression": Pipeline([
            ("scaler", StandardScaler()),
            ("model", LogisticRegression(
                C=1.0, class_weight="balanced", max_iter=5000, random_state=42
            )),
        ]),
        "random_forest": RandomForestClassifier(
            n_estimators=400, max_depth=7, min_samples_leaf=1,
            class_weight="balanced", random_state=42, n_jobs=-1
        ),
    }

def choose(results):
    return max(results, key=lambda n: (results[n]["macro_f1"], results[n]["balanced_accuracy"]))

def main():
    ap = argparse.ArgumentParser(description="Train Phase-2 models.")
    ap.add_argument("--train", required=True)
    ap.add_argument("--val", required=True)
    ap.add_argument("--metadata", required=True)
    ap.add_argument("--presence-model", required=True)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    tr = pd.read_csv(args.train)
    va = pd.read_csv(args.val)
    meta = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
    motion_names = meta["motion_feature_names"]
    all_names = meta["all_feature_names"]

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    print("="*80)
    print("PHASE-2 MODEL TRAINING")
    print("="*80)

    # Static vs moving, person-only, motion features only.
    trp = tr[tr["label"].isin(["static","moving"])].copy()
    vap = va[va["label"].isin(["static","moving"])].copy()
    Xtr_m, Xva_m = trp[motion_names], vap[motion_names]
    ytr_m = (trp["label"]=="moving").astype(int)
    yva_m = (vap["label"]=="moving").astype(int)

    motion_results, motion_models = {}, {}
    print("\n[1/3] STATIC vs MOVING")
    for name, model in candidates().items():
        model.fit(Xtr_m, ytr_m)
        pred = model.predict(Xva_m)
        m = metrics(yva_m, pred, [0,1])
        motion_results[name] = m
        motion_models[name] = model
        print(f"{name:<20} macro_f1={m['macro_f1']:.6f} bal_acc={m['balanced_accuracy']:.6f} cm={m['confusion_matrix']}")

    best_motion_name = choose(motion_results)
    best_motion = motion_models[best_motion_name]
    joblib.dump({
        "model": best_motion,
        "model_name": best_motion_name,
        "feature_names": motion_names,
        "class_map": {0:"static", 1:"moving"},
        "decision_threshold": 0.5,
    }, outdir/"motion_model.joblib")

    # Direct 3-class.
    Xtr_d, Xva_d = tr[all_names], va[all_names]
    ytr_d, yva_d = tr["y"].astype(int), va["y"].astype(int)

    direct_results, direct_models = {}, {}
    print("\n[2/3] DIRECT EMPTY / STATIC / MOVING")
    for name, model in candidates().items():
        model.fit(Xtr_d, ytr_d)
        pred = model.predict(Xva_d)
        m = metrics(yva_d, pred, [0,1,2])
        direct_results[name] = m
        direct_models[name] = model
        print(f"{name:<20} macro_f1={m['macro_f1']:.6f} bal_acc={m['balanced_accuracy']:.6f} cm={m['confusion_matrix']}")

    best_direct_name = choose(direct_results)
    best_direct = direct_models[best_direct_name]
    joblib.dump({
        "model": best_direct,
        "model_name": best_direct_name,
        "feature_names": all_names,
        "class_map": {0:"empty",1:"static",2:"moving"},
    }, outdir/"direct3_model.joblib")

    # Hierarchical validation.
    print("\n[3/3] HIERARCHICAL vs DIRECT on validation")
    presence = joblib.load(args.presence_model)
    pp = presence["model"].predict_proba(va[presence["feature_names"]])[:,1]
    present = pp >= float(presence.get("decision_threshold",0.5))

    pm = best_motion.predict_proba(va[motion_names])[:,1]
    moving = pm >= 0.5

    pred_h = np.zeros(len(va), dtype=int)
    pred_h[present & ~moving] = 1
    pred_h[present & moving] = 2

    hier = metrics(yva_d, pred_h, [0,1,2])
    direct = metrics(yva_d, best_direct.predict(Xva_d), [0,1,2])

    compare = {"hierarchical": hier, "direct3": direct}
    deployment = max(compare, key=lambda n: (compare[n]["macro_f1"], compare[n]["balanced_accuracy"]))

    report = {
        "motion_model_selection": {"best": best_motion_name, "validation": motion_results},
        "direct3_model_selection": {"best": best_direct_name, "validation": direct_results},
        "phase2_validation_comparison": compare,
        "selected_deployment": deployment,
        "test_used": False,
    }
    (outdir/"phase2_model_selection.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\nBest motion model : {best_motion_name}")
    print(f"Best direct model : {best_direct_name}")
    print(f"Hierarchical macro-F1: {hier['macro_f1']:.6f}")
    print(f"Direct-3 macro-F1    : {direct['macro_f1']:.6f}")
    print(f"Selected deployment  : {deployment}")
    print("TEST SET             : NOT USED")

if __name__ == "__main__":
    main()
