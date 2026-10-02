from __future__ import annotations

import argparse
import ast
import csv
import sys
import threading
import time
from collections import Counter, deque
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
    raw_iq_to_amplitude,
    resample,
    temporal_smooth,
)
from phase2_utils import extract_motion_features


class ReceiverStream:
    def __init__(self, port, baud, t0):
        self.t0 = t0
        self.ser = serial.Serial(port, baudrate=baud, timeout=0.10, write_timeout=0.10)
        self.ser.reset_input_buffer()
        self.lock = threading.Lock()
        self.times = deque(maxlen=4000)
        self.amps = deque(maxlen=4000)
        self.valid = 0
        self.parse_bad = 0
        self.last_t = None
        self.running = True
        self.last_error = None
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
                return np.empty(0), np.empty((0, TOTAL_ACTIVE_N), dtype=np.float32)
            return (
                np.asarray(self.times, dtype=float),
                np.vstack(self.amps).astype(np.float32),
            )

    def age(self, now_rel):
        with self.lock:
            return float("inf") if self.last_t is None else now_rel - self.last_t


def aligned_block(r1, r2, fs, duration, now_rel=None, stale=1.0):
    if now_rel is not None and (r1.age(now_rel) > stale or r2.age(now_rel) > stale):
        raise RuntimeError("One receiver stream is stale")

    t1, A1 = r1.snapshot()
    t2, A2 = r2.snapshot()
    if len(t1) < 20 or len(t2) < 20:
        raise RuntimeError("Not enough CSI yet")

    end = min(float(t1[-1]), float(t2[-1]))
    start = end - duration
    if t1[0] > start or t2[0] > start:
        raise RuntimeError("Not enough common overlap yet")

    m1 = (t1 >= start - 0.25) & (t1 <= end + 0.05)
    m2 = (t2 >= start - 0.25) & (t2 <= end + 0.05)
    t1w, A1w = t1[m1], A1[m1]
    t2w, A2w = t2[m2], A2[m2]

    if np.max(np.diff(t1w)) > 0.25 or np.max(np.diff(t2w)) > 0.25:
        raise RuntimeError("Large packet gap in live window")

    grid = np.arange(start, end, 1.0/fs, dtype=float)
    expected = int(round(duration*fs))
    grid = grid[:expected]
    if len(grid) < expected:
        raise RuntimeError("Resample grid too short")
    if grid[0] < t1w[0] or grid[-1] > t1w[-1]:
        raise RuntimeError("RX1 interpolation coverage incomplete")
    if grid[0] < t2w[0] or grid[-1] > t2w[-1]:
        raise RuntimeError("RX2 interpolation coverage incomplete")

    B1 = temporal_smooth(fieldwise_ltf_normalize(resample(t1w, A1w, grid)))
    B2 = temporal_smooth(fieldwise_ltf_normalize(resample(t2w, A2w, grid)))
    return B1, B2, end


def majority_label(items):
    c = Counter(items)
    best = max(c.values())
    tied = {k for k, v in c.items() if v == best}
    for x in reversed(items):
        if x in tied:
            return x
    return items[-1]


def main():
    ap = argparse.ArgumentParser(description="Live Phase-2 EMPTY/STATIC/MOVING.")
    ap.add_argument("--rx1", default="COM6")
    ap.add_argument("--rx2", default="COM8")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--presence-model", required=True)
    ap.add_argument("--motion-model", required=True)
    ap.add_argument("--calibration", type=float, default=12.0)
    ap.add_argument("--countdown", type=int, default=5)
    ap.add_argument("--fs", type=float, default=25.0)
    ap.add_argument("--window", type=float, default=2.0)
    ap.add_argument("--step", type=float, default=0.5)
    ap.add_argument("--vote", type=int, default=5)
    args = ap.parse_args()

    presence = joblib.load(args.presence_model)
    motion = joblib.load(args.motion_model)

    t0 = time.perf_counter()
    r1 = r2 = None

    print("="*80)
    print("PHASE-2 LIVE: EMPTY / PERSON STATIC / PERSON MOVING")
    print("="*80)

    try:
        r1 = ReceiverStream(args.rx1, args.baud, t0)
        r2 = ReceiverStream(args.rx2, args.baud, t0)
        r1.start()
        r2.start()

        input("Calibration needs an EMPTY sensing area.\nPress Enter when ready to leave...")
        for s in range(args.countdown, 0, -1):
            print(s, flush=True)
            time.sleep(1)

        r1.clear()
        r2.clear()
        print(f"\nCalibrating EMPTY for {args.calibration:.1f}s...")
        time.sleep(args.calibration)

        B1, B2, _ = aligned_block(r1, r2, args.fs, max(5.0, args.calibration-2.0))
        baseline = {
            "rx1": np.median(B1, axis=0).astype(np.float32),
            "rx2": np.median(B2, axis=0).astype(np.float32),
        }

        r1.clear()
        r2.clear()
        print("Calibration complete. Live detection starts now.\n")

        history = deque(maxlen=max(1, args.vote))
        next_infer = time.perf_counter() + args.window + 0.25
        last_end = -1.0

        while True:
            if not r1.running:
                raise RuntimeError(f"RX1 stopped: {r1.last_error}")
            if not r2.running:
                raise RuntimeError(f"RX2 stopped: {r2.last_error}")

            now = time.perf_counter()
            if now < next_infer:
                time.sleep(min(0.05, next_infer-now))
                continue
            next_infer += args.step

            try:
                W1, W2, end = aligned_block(
                    r1, r2, args.fs, args.window,
                    now_rel=time.perf_counter()-t0
                )
            except RuntimeError as exc:
                print(f"[waiting] {exc}")
                continue

            if end <= last_end + 1e-6:
                print("[waiting] common window has not advanced")
                continue
            last_end = end

            base_f = extract_window_features(W1, W2, baseline)
            Xp = pd.DataFrame([base_f], columns=presence["feature_names"])
            p_person = float(presence["model"].predict_proba(Xp)[0,1])
            is_person = p_person >= float(presence.get("decision_threshold",0.5))

            p_move = 0.0
            if not is_person:
                raw_label = "EMPTY"
            else:
                mf = extract_motion_features(W1, W2, fs=args.fs)
                Xm = pd.DataFrame([mf], columns=motion["feature_names"])
                p_move = float(motion["model"].predict_proba(Xm)[0,1])
                raw_label = "MOVING" if p_move >= float(motion.get("decision_threshold",0.5)) else "STATIC"

            history.append(raw_label)
            stable = majority_label(list(history))

            print(
                f"p_person={p_person:6.3f}  p_move={p_move:6.3f}  "
                f"raw={raw_label:6s} => {stable:6s}  "
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
