from __future__ import annotations
import argparse, ast
from pathlib import Path
import numpy as np
import pandas as pd

EXPECTED = [
    "S01_slow_walk", "S01_walk_left_right", "S01_walk_tx_rx",
    "S02_slow_walk", "S02_walk_left_right", "S02_walk_tx_rx",
    "S03_slow_walk", "S03_walk_left_right", "S03_walk_tx_rx",
]

def inspect_file(path: Path):
    df = pd.read_csv(path)
    req = {
        "pc_elapsed_s","seq","channel","secondary_channel","sig_mode",
        "cwb","stbc","csi_len","first_word_invalid","firmware_dropped","csi_data"
    }
    miss = req - set(df.columns)
    if miss:
        return False, f"missing columns {sorted(miss)}", {}

    t = df["pc_elapsed_s"].to_numpy(float)
    dur = float(t[-1]-t[0])
    rate = float((len(df)-1)/dur) if dur > 0 else 0.0
    gap = float(np.max(np.diff(t))) if len(t) > 1 else 999.0
    seq = df["seq"].to_numpy(np.int64)
    seq_missing = int(np.sum(np.maximum(np.diff(seq)-1, 0)))

    parse_bad = 0
    for x in df["csi_data"]:
        try:
            a = np.asarray(ast.literal_eval(str(x)), dtype=np.int16)
            if a.ndim != 1 or len(a) != 256:
                parse_bad += 1
        except Exception:
            parse_bad += 1

    checks = [
        dur >= 55.0,
        rate >= 35.0,
        gap <= 0.25,
        seq_missing == 0,
        bool((df["channel"] == 6).all()),
        bool((df["secondary_channel"] == 0).all()),
        bool((df["sig_mode"] == 1).all()),
        bool((df["cwb"] == 0).all()),
        bool((df["stbc"] == 0).all()),
        bool((df["csi_len"] == 256).all()),
        int(df["firmware_dropped"].max()) == 0,
        int(df["first_word_invalid"].max()) == 0,
        parse_bad == 0,
    ]
    return all(checks), "", {
        "rows": len(df), "duration_s": dur, "rate_hz": rate,
        "max_gap_s": gap, "seq_missing": seq_missing, "parse_bad": parse_bad
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    raw = Path(args.raw).resolve()
    summary, overall = [], True

    print("="*90)
    print("PHASE-2 NEW MOVING DATA QC")
    print("="*90)

    for sid in EXPECTED:
        pair_ok = True
        row = {"session_id": sid}
        for rx in ("RX1","RX2"):
            p = raw / f"{sid}_{rx}.csv"
            if not p.exists():
                print(f"{sid:<26} {rx}: MISSING")
                pair_ok = overall = False
                continue
            ok, reason, m = inspect_file(p)
            if not ok:
                pair_ok = overall = False
            print(
                f"{sid:<26} {rx}: {'PASS' if ok else 'FAIL'} "
                f"rows={m.get('rows',0):4d} rate={m.get('rate_hz',0):6.2f}Hz "
                f"gap={m.get('max_gap_s',0):.3f}s seqmiss={m.get('seq_missing',-1)}"
            )
            if reason:
                print("   ", reason)
            row[f"{rx.lower()}_ok"] = ok
            row[f"{rx.lower()}_rate_hz"] = m.get("rate_hz", np.nan)
            row[f"{rx.lower()}_max_gap_s"] = m.get("max_gap_s", np.nan)

        row["pair_ok"] = pair_ok
        summary.append(row)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(summary).to_csv(out, index=False)
        print(f"\nSaved: {out}")

    print("\nOVERALL:", "PASS" if overall else "FAIL")
    raise SystemExit(0 if overall else 2)

if __name__ == "__main__":
    main()
