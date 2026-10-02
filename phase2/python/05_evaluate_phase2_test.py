from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score

def metrics(y, pred):
    return {
        "accuracy": float(accuracy_score(y, pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y, pred)),
        "macro_f1": float(f1_score(y, pred, average="macro", zero_division=0)),
        "confusion_matrix": confusion_matrix(y, pred, labels=[0,1,2]).tolist(),
    }

def session_majority(df, pred):
    temp = df[["session_id","y","label"]].copy()
    temp["pred"] = pred
    rows = []
    for sid, g in temp.groupby("session_id"):
        counts = Counter(g["pred"].tolist())
        chosen = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[0][0]
        rows.append({
            "session_id": sid,
            "label": g["label"].iloc[0],
            "y": int(g["y"].iloc[0]),
            "pred": int(chosen),
            "windows": int(len(g)),
        })
    out = pd.DataFrame(rows)
    return out, metrics(out["y"].to_numpy(), out["pred"].to_numpy())

def main():
    ap = argparse.ArgumentParser(description="One-time Phase-2 test.")
    ap.add_argument("--test", required=True)
    ap.add_argument("--presence-model", required=True)
    ap.add_argument("--motion-model", required=True)
    ap.add_argument("--direct-model", required=True)
    ap.add_argument("--selection", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    df = pd.read_csv(args.test)
    y = df["y"].astype(int).to_numpy()

    presence = joblib.load(args.presence_model)
    motion = joblib.load(args.motion_model)
    direct = joblib.load(args.direct_model)
    selection = json.loads(Path(args.selection).read_text(encoding="utf-8"))

    pp = presence["model"].predict_proba(df[presence["feature_names"]])[:,1]
    present = pp >= float(presence.get("decision_threshold",0.5))
    pm = motion["model"].predict_proba(df[motion["feature_names"]])[:,1]
    moving = pm >= float(motion.get("decision_threshold",0.5))

    pred_h = np.zeros(len(df), dtype=int)
    pred_h[present & ~moving] = 1
    pred_h[present & moving] = 2

    pred_d = direct["model"].predict(df[direct["feature_names"]]).astype(int)

    wh, wd = metrics(y, pred_h), metrics(y, pred_d)
    sht, sh = session_majority(df, pred_h)
    sdt, sd = session_majority(df, pred_d)

    chosen = selection["selected_deployment"]
    result = {
        "selected_deployment_from_validation": chosen,
        "hierarchical": {
            "window_level": wh,
            "session_level": sh,
            "sessions": sht.to_dict(orient="records"),
        },
        "direct3": {
            "window_level": wd,
            "session_level": sd,
            "sessions": sdt.to_dict(orient="records"),
        },
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print("="*80)
    print("PHASE-2 UNTOUCHED TEST")
    print("="*80)
    print(f"Selected deployment: {chosen}")
    print(f"Hierarchical window macro-F1: {wh['macro_f1']:.6f}")
    print(f"Direct-3     window macro-F1: {wd['macro_f1']:.6f}")
    print(f"Hierarchical session macro-F1: {sh['macro_f1']:.6f}")
    print(f"Direct-3     session macro-F1: {sd['macro_f1']:.6f}")
    print(f"\nSaved: {out}")

if __name__ == "__main__":
    main()
