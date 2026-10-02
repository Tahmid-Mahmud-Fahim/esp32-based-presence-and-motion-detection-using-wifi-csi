import argparse
import ast
from pathlib import Path
import numpy as np
import pandas as pd


def analyze(path: Path):
    df = pd.read_csv(path)
    t = df["pc_elapsed_s"].to_numpy(float)
    duration = max(t[-1] - t[0], 1e-9)
    rate = (len(t) - 1) / duration
    gaps = np.diff(df["seq"].to_numpy(int))
    seq_missing = int(np.sum(np.clip(gaps - 1, 0, None))) if len(gaps) else 0
    lengths = df["csi_len"].value_counts().to_dict()
    fw_drop = int(df["firmware_dropped"].max()) if "firmware_dropped" in df else -1
    invalid = int(df["first_word_invalid"].sum()) if "first_word_invalid" in df else -1
    rssi = df["rssi"].to_numpy(float)
    parse_bad = 0
    for s, n in zip(df["csi_data"].head(200), df["csi_len"].head(200)):
        try:
            if len(ast.literal_eval(s)) != int(n):
                parse_bad += 1
        except Exception:
            parse_bad += 1
    return {
        "rows": len(df), "duration_s": duration, "rate_hz": rate,
        "seq_missing": seq_missing, "csi_lengths": lengths,
        "fw_drop": fw_drop, "first_word_invalid": invalid,
        "rssi_mean": float(np.mean(rssi)), "rssi_std": float(np.std(rssi)),
        "sample_parse_bad_first200": parse_bad,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rx1", required=True)
    ap.add_argument("--rx2", required=True)
    args = ap.parse_args()
    for name, p in [("RX1", Path(args.rx1)), ("RX2", Path(args.rx2))]:
        x = analyze(p)
        print(f"\n{name}: {p}")
        for k, v in x.items():
            print(f"  {k:28s}: {v}")
        if x["rate_hz"] < 35:
            print("  WARNING: measured CSI rate <35 Hz; diagnose before full dataset collection.")
        if len(x["csi_lengths"]) > 1:
            print("  NOTE: more than one CSI length observed; preprocessing will retain modal length.")

if __name__ == "__main__":
    main()
