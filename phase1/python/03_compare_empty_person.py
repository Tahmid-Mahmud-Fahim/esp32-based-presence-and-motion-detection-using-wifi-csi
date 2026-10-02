import argparse
from pathlib import Path
import sys
import numpy as np
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from presence.csi_utils import align_dual_rx


def scalar_series(A):
    return np.mean(A, axis=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--empty-rx1", required=True)
    ap.add_argument("--empty-rx2", required=True)
    ap.add_argument("--person-rx1", required=True)
    ap.add_argument("--person-rx2", required=True)
    ap.add_argument("--fs", type=float, default=25.0)
    ap.add_argument("--out", default="reports/empty_vs_person.png")
    args = ap.parse_args()

    te, e1, e2 = align_dual_rx(args.empty_rx1, args.empty_rx2, args.fs)
    tp, p1, p2 = align_dual_rx(args.person_rx1, args.person_rx2, args.fs)
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(11, 5))
    ax = fig.add_subplot(111)
    ax.plot(te, scalar_series(e1), label="EMPTY RX1")
    ax.plot(te, scalar_series(e2), label="EMPTY RX2")
    ax.plot(tp, scalar_series(p1), label="PERSON RX1", alpha=0.75)
    ax.plot(tp, scalar_series(p2), label="PERSON RX2", alpha=0.75)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Mean normalized CSI amplitude")
    ax.set_title("Phase-1 sanity check: EMPTY versus PERSON")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out, dpi=180)
    print(f"Saved {out}")

    def profile_dist(A, B):
        n = min(A.shape[1], B.shape[1])
        return float(np.sqrt(np.mean((np.median(A[:, :n], axis=0) - np.median(B[:, :n], axis=0))**2)))
    print(f"RX1 median-profile RMSE: {profile_dist(e1,p1):.6f}")
    print(f"RX2 median-profile RMSE: {profile_dist(e2,p2):.6f}")

if __name__ == "__main__":
    main()
