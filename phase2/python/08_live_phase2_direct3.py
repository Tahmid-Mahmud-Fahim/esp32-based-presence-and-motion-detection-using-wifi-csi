from __future__ import annotations

import argparse
import ast
import csv
import sys
import threading
import time
from collections import deque
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import serial

THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[2]
PHASE1_ROOT = PROJECT_ROOT / "phase1"

sys.path.insert(0, str(PHASE1_ROOT))
sys.path.insert(0, str(THIS_FILE.parent))

from presence.csi_utils import (
    EXPECTED_CSI_LEN,
    TOTAL_ACTIVE_N,
    extract_window_features,
    fieldwise_ltf_normalize,
    load_baseline,
    raw_iq_to_amplitude,
    resample,
    temporal_smooth,
)
from phase2_utils import extract_motion_features


class ReceiverStream:
    def __init__(self, name: str, port: str, baud: int, t0: float):
        self.name = name
        self.port = port
        self.t0 = t0
        self.ser = serial.Serial(port, baudrate=baud, timeout=0.10, write_timeout=0.10)
        self.ser.reset_input_buffer()

        self.lock = threading.Lock()
        self.times = deque(maxlen=5000)
        self.amps = deque(maxlen=5000)

        self.valid = 0
        self.parse_bad = 0
        self.serial_errors = 0
        self.last_t = None
        self.last_error = None
        self.running = True

        self.thread = threading.Thread(target=self._reader, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.running = False
        try:
            self.thread.join(timeout=1.0)
        except Exception:
            pass
        try:
            self.ser.close()
        except Exception:
            pass

    def clear(self):
        with self.lock:
            self.times.clear()
            self.amps.clear()
            self.last_t = None
        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass

    def _reader(self):
        while self.running:
            try:
                raw_line = self.ser.readline()
            except Exception as exc:
                self.serial_errors += 1
                self.last_error = f"{type(exc).__name__}: {exc}"
                self.running = False
                break

            if not raw_line:
                continue

            try:
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if not line.startswith("CSI_DATA,"):
                    continue

                row = next(csv.reader([line]))
                if len(row) != 15:
                    self.parse_bad += 1
                    continue

                if not (
                    int(row[5]) == 6
                    and int(row[6]) == 0
                    and int(row[7]) == 1
                    and int(row[9]) == 0
                    and int(row[10]) == 0
                    and int(row[11]) == EXPECTED_CSI_LEN
                ):
                    continue

                raw = np.asarray(ast.literal_eval(row[14]), dtype=np.int16)
                amp = raw_iq_to_amplitude(raw)

                if amp.shape != (TOTAL_ACTIVE_N,):
                    self.parse_bad += 1
                    continue

                t = time.perf_counter() - self.t0
                with self.lock:
                    self.times.append(t)
                    self.amps.append(amp)
                    self.last_t = t
                self.valid += 1

            except Exception:
                self.parse_bad += 1

    def snapshot(self):
        with self.lock:
            if not self.times:
                return (
                    np.empty(0, dtype=float),
                    np.empty((0, TOTAL_ACTIVE_N), dtype=np.float32),
                )
            return (
                np.asarray(self.times, dtype=float),
                np.vstack(self.amps).astype(np.float32),
            )

    def age(self, now_rel: float) -> float:
        with self.lock:
            return float("inf") if self.last_t is None else now_rel - self.last_t


def aligned_recent(
    r1: ReceiverStream,
    r2: ReceiverStream,
    fs: float,
    duration: float,
    now_rel: float | None = None,
    stale: float = 1.0,
    smooth: bool = True,
):
    if now_rel is not None:
        if r1.age(now_rel) > stale or r2.age(now_rel) > stale:
            raise RuntimeError("One receiver stream is stale")

    t1, A1 = r1.snapshot()
    t2, A2 = r2.snapshot()

    if len(t1) < 10 or len(t2) < 10:
        raise RuntimeError("Not enough CSI yet")

    common_end = min(float(t1[-1]), float(t2[-1]))
    common_start = common_end - duration

    if t1[0] > common_start or t2[0] > common_start:
        raise RuntimeError("Not enough common overlap yet")

    m1 = (t1 >= common_start - 0.25) & (t1 <= common_end + 0.05)
    m2 = (t2 >= common_start - 0.25) & (t2 <= common_end + 0.05)

    t1w, A1w = t1[m1], A1[m1]
    t2w, A2w = t2[m2], A2[m2]

    if len(t1w) < 4 or len(t2w) < 4:
        raise RuntimeError("Too few packets in current window")

    if np.max(np.diff(t1w)) > 0.25 or np.max(np.diff(t2w)) > 0.25:
        raise RuntimeError("Large packet gap in current window")

    grid = np.arange(common_start, common_end, 1.0 / fs, dtype=float)
    expected = int(round(duration * fs))
    if len(grid) > expected:
        grid = grid[:expected]

    if len(grid) < expected:
        raise RuntimeError("Resample grid too short")

    if grid[0] < t1w[0] or grid[-1] > t1w[-1]:
        raise RuntimeError("RX1 interpolation coverage incomplete")
    if grid[0] < t2w[0] or grid[-1] > t2w[-1]:
        raise RuntimeError("RX2 interpolation coverage incomplete")

    B1 = fieldwise_ltf_normalize(resample(t1w, A1w, grid))
    B2 = fieldwise_ltf_normalize(resample(t2w, A2w, grid))

    if smooth:
        B1 = temporal_smooth(B1)
        B2 = temporal_smooth(B2)

    return B1, B2, common_end


def main():
    ap = argparse.ArgumentParser(
        description="Direct 3-class Phase-2 live detector for comparison."
    )
    ap.add_argument("--rx1", default="COM6")
    ap.add_argument("--rx2", default="COM8")
    ap.add_argument("--baud", type=int, default=921600)

    ap.add_argument("--model", required=True,
                    help="phase2/models/direct3_model.joblib")
    ap.add_argument("--baseline", required=True,
                    help="phase2/data/processed/phase2_empty_baseline.npz")

    ap.add_argument("--fs", type=float, default=25.0)
    ap.add_argument("--window", type=float, default=2.0)
    ap.add_argument("--step", type=float, default=0.20)
    ap.add_argument("--confirm", type=int, default=1,
                    help="Consecutive identical predictions before state changes.")
    args = ap.parse_args()

    bundle = joblib.load(args.model)
    model = bundle["model"]
    feature_names = list(bundle["feature_names"])
    class_map = {
        int(k): v for k, v in bundle.get(
            "class_map", {0: "empty", 1: "static", 2: "moving"}
        ).items()
    }
    baseline = load_baseline(args.baseline)

    t0 = time.perf_counter()
    r1 = r2 = None

    print("=" * 90)
    print("PHASE-2 DIRECT 3-CLASS LIVE DETECTOR")
    print("=" * 90)
    print("Uses the validation-selected direct model.")
    print("Uses the TRAINING EMPTY baseline to match offline preprocessing.")
    print(f"Window={args.window:.1f}s, update={args.step:.2f}s, confirm={args.confirm}")
    print()

    try:
        r1 = ReceiverStream("RX1", args.rx1, args.baud, t0)
        r2 = ReceiverStream("RX2", args.rx2, args.baud, t0)
        r1.start()
        r2.start()

        print("Collecting enough CSI for the first window...")
        print("Press Ctrl+C to stop.\n")

        state = None
        pending = None
        pending_count = 0
        last_end = -1.0
        next_tick = time.perf_counter() + args.window + 0.15

        while True:
            if not r1.running:
                raise RuntimeError(f"RX1 reader stopped: {r1.last_error}")
            if not r2.running:
                raise RuntimeError(f"RX2 reader stopped: {r2.last_error}")

            now = time.perf_counter()
            if now < next_tick:
                time.sleep(min(0.03, next_tick - now))
                continue
            next_tick += args.step

            now_rel = time.perf_counter() - t0

            try:
                W1, W2, end = aligned_recent(
                    r1, r2, args.fs, args.window,
                    now_rel=now_rel, smooth=True
                )
            except RuntimeError as exc:
                print(f"[waiting] {exc}")
                continue

            if end <= last_end + 1e-6:
                continue
            last_end = end

            base_f = extract_window_features(W1, W2, baseline)
            motion_f = extract_motion_features(W1, W2, fs=args.fs)
            all_f = np.concatenate([base_f, motion_f]).astype(np.float32)

            if len(all_f) != len(feature_names):
                raise RuntimeError(
                    f"Feature mismatch: live={len(all_f)}, model={len(feature_names)}"
                )

            X = pd.DataFrame([all_f], columns=feature_names)
            probs = model.predict_proba(X)[0]
            classes = np.asarray(model.classes_, dtype=int)

            winner_i = int(np.argmax(probs))
            pred_id = int(classes[winner_i])
            raw_state = class_map[pred_id].upper()

            prob_by_name = {
                class_map[int(c)].upper(): float(p)
                for c, p in zip(classes, probs)
            }

            if state is None:
                state = raw_state
                pending = None
                pending_count = 0
            elif raw_state == state:
                pending = None
                pending_count = 0
            else:
                if raw_state == pending:
                    pending_count += 1
                else:
                    pending = raw_state
                    pending_count = 1

                if pending_count >= max(1, args.confirm):
                    state = raw_state
                    pending = None
                    pending_count = 0

            print(
                f"P(E)={prob_by_name.get('EMPTY', 0.0):5.3f}  "
                f"P(S)={prob_by_name.get('STATIC', 0.0):5.3f}  "
                f"P(M)={prob_by_name.get('MOVING', 0.0):5.3f}  "
                f"raw={raw_state:6s} => {state:6s}  "
                f"| RX1={r1.valid:5d} RX2={r2.valid:5d}"
            )

    except KeyboardInterrupt:
        print("\nStopping...")

    except Exception as exc:
        print(f"\nERROR: {type(exc).__name__}: {exc}")

    finally:
        if r1 is not None:
            r1.stop()
        if r2 is not None:
            r2.stop()
        print("Stopped.")


if __name__ == "__main__":
    main()
