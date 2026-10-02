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


def fast_motion_score(W1: np.ndarray, W2: np.ndarray) -> float:
    """Short-window motion score independent of the EMPTY baseline."""
    def one(W):
        d = np.diff(np.asarray(W, dtype=np.float32), axis=0)
        if len(d) == 0:
            return 0.0
        packet_rms = np.sqrt(np.mean(d * d, axis=1))
        return float(np.median(packet_rms))

    # Motion visible strongly at either RX should count.
    return max(one(W1), one(W2))


def calibrate_fast_threshold(
    r1: ReceiverStream,
    r2: ReceiverStream,
    fs: float,
    fast_window: float,
):
    """Estimate the normal EMPTY short-term motion floor from startup data."""
    t1, A1 = r1.snapshot()
    t2, A2 = r2.snapshot()

    start = max(float(t1[0]), float(t2[0]))
    end = min(float(t1[-1]), float(t2[-1]))

    if end - start < 5.0:
        raise RuntimeError("Not enough common EMPTY calibration data")

    grid = np.arange(start, end, 1.0 / fs, dtype=float)

    if np.max(np.diff(t1)) > 0.25 or np.max(np.diff(t2)) > 0.25:
        raise RuntimeError("Large gap during EMPTY calibration")

    B1 = fieldwise_ltf_normalize(resample(t1, A1, grid))
    B2 = fieldwise_ltf_normalize(resample(t2, A2, grid))

    n = max(4, int(round(fast_window * fs)))
    hop = max(1, int(round(0.10 * fs)))

    scores = []
    for s in range(0, len(grid) - n + 1, hop):
        scores.append(fast_motion_score(B1[s:s+n], B2[s:s+n]))

    if len(scores) < 10:
        raise RuntimeError("Too few EMPTY fast-motion calibration windows")

    scores = np.asarray(scores, dtype=float)
    med = float(np.median(scores))
    mad = float(np.median(np.abs(scores - med)))
    robust_sigma = 1.4826 * mad
    q995 = float(np.percentile(scores, 99.5))

    # Conservative automatic threshold. User may override from CLI.
    threshold = max(med + 8.0 * robust_sigma, q995 * 1.20)

    return threshold, med, q995, scores


def main():
    ap = argparse.ArgumentParser(
        description="Recommended low-latency Phase-2 dual-timescale live detector."
    )
    ap.add_argument("--rx1", default="COM6")
    ap.add_argument("--rx2", default="COM8")
    ap.add_argument("--baud", type=int, default=921600)

    ap.add_argument("--presence-model", required=True)
    ap.add_argument("--motion-model", required=True)

    ap.add_argument("--calibration", type=float, default=12.0)
    ap.add_argument("--countdown", type=int, default=5)

    ap.add_argument("--fs", type=float, default=25.0)
    ap.add_argument("--slow-window", type=float, default=2.0)
    ap.add_argument("--fast-window", type=float, default=0.6)
    ap.add_argument("--step", type=float, default=0.10)

    ap.add_argument("--fast-threshold", type=float, default=None,
                    help="Optional manual fast-motion threshold. Default=auto from EMPTY.")
    ap.add_argument("--fast-confirm", type=int, default=2,
                    help="Consecutive fast-motion hits before immediate MOVING.")
    ap.add_argument("--fast-clear", type=int, default=4,
                    help="Consecutive low-motion checks before MOVING can clear.")
    ap.add_argument("--fast-release-ratio", type=float, default=0.75)

    ap.add_argument("--presence-on", type=float, default=0.60)
    ap.add_argument("--presence-off", type=float, default=0.35)
    ap.add_argument("--move-fallback-on", type=float, default=0.75,
                    help="2-s motion-model fallback for very slow walking.")
    args = ap.parse_args()

    presence = joblib.load(args.presence_model)
    motion = joblib.load(args.motion_model)

    t0 = time.perf_counter()
    r1 = r2 = None

    print("=" * 90)
    print("PHASE-2 LOW-LATENCY DUAL-TIMESCALE DETECTOR")
    print("=" * 90)
    print(f"FAST path : {args.fast_window:.2f}s window every {args.step:.2f}s")
    print(f"SLOW path : {args.slow_window:.2f}s trained presence/motion models")
    print()

    try:
        r1 = ReceiverStream("RX1", args.rx1, args.baud, t0)
        r2 = ReceiverStream("RX2", args.rx2, args.baud, t0)
        r1.start()
        r2.start()

        input(
            "Startup calibration needs an EMPTY sensing area.\n"
            "Press Enter when ready to leave..."
        )

        for s in range(args.countdown, 0, -1):
            print(s, flush=True)
            time.sleep(1)

        r1.clear()
        r2.clear()

        print(f"\nCalibrating EMPTY for {args.calibration:.1f}s...")
        time.sleep(args.calibration)

        # Build current EMPTY baseline for the Phase-1 presence model.
        B1c, B2c, _ = aligned_recent(
            r1, r2, args.fs, max(5.0, args.calibration - 2.0), smooth=True
        )
        baseline = {
            "rx1": np.median(B1c, axis=0).astype(np.float32),
            "rx2": np.median(B2c, axis=0).astype(np.float32),
        }

        auto_thr, empty_med, empty_q995, _ = calibrate_fast_threshold(
            r1, r2, args.fs, args.fast_window
        )
        fast_thr = auto_thr if args.fast_threshold is None else args.fast_threshold

        print(f"EMPTY fast-motion median : {empty_med:.6f}")
        print(f"EMPTY fast-motion q99.5  : {empty_q995:.6f}")
        print(f"FAST motion threshold    : {fast_thr:.6f}")

        # Start classification using fresh samples only.
        r1.clear()
        r2.clear()

        print("\nCalibration complete.")
        print("FAST path can trigger MOVING before the 2-second model is full.")
        print("Press Ctrl+C to stop.\n")

        state = "EMPTY"
        fast_hits = 0
        clear_hits = 0
        last_fast_end = -1.0
        last_slow_end = -1.0
        last_p_person = 0.0
        last_p_move = 0.0

        next_tick = time.perf_counter() + args.fast_window + 0.15

        while True:
            if not r1.running:
                raise RuntimeError(f"RX1 reader stopped: {r1.last_error}")
            if not r2.running:
                raise RuntimeError(f"RX2 reader stopped: {r2.last_error}")

            now = time.perf_counter()
            if now < next_tick:
                time.sleep(min(0.02, next_tick - now))
                continue
            next_tick += args.step

            now_rel = time.perf_counter() - t0

            # -------------------------
            # FAST branch (~0.6 s)
            # -------------------------
            try:
                F1, F2, fast_end = aligned_recent(
                    r1, r2, args.fs, args.fast_window,
                    now_rel=now_rel, smooth=False
                )
            except RuntimeError as exc:
                print(f"[waiting-fast] {exc}")
                continue

            if fast_end <= last_fast_end + 1e-6:
                continue
            last_fast_end = fast_end

            score = fast_motion_score(F1, F2)
            fast_active = score >= fast_thr
            fast_low = score <= fast_thr * args.fast_release_ratio

            if fast_active:
                fast_hits += 1
                clear_hits = 0
            else:
                fast_hits = 0
                if fast_low:
                    clear_hits += 1
                else:
                    clear_hits = 0

            # -------------------------
            # SLOW trained branch (2 s)
            # -------------------------
            slow_ready = False
            try:
                W1, W2, slow_end = aligned_recent(
                    r1, r2, args.fs, args.slow_window,
                    now_rel=now_rel, smooth=True
                )
                if slow_end > last_slow_end + 1e-6:
                    last_slow_end = slow_end
                    slow_ready = True

                    base_f = extract_window_features(W1, W2, baseline)
                    Xp = pd.DataFrame([base_f], columns=presence["feature_names"])
                    last_p_person = float(
                        presence["model"].predict_proba(Xp)[0, 1]
                    )

                    # Motion model is person-only and baseline independent.
                    motion_f = extract_motion_features(W1, W2, fs=args.fs)
                    Xm = pd.DataFrame([motion_f], columns=motion["feature_names"])
                    last_p_move = float(
                        motion["model"].predict_proba(Xm)[0, 1]
                    )
            except RuntimeError:
                pass

            # -------------------------
            # State logic
            # -------------------------
            # Immediate movement onset from the fast branch.
            if fast_hits >= max(1, args.fast_confirm):
                state = "MOVING"

            # Slow motion-model fallback catches very slow locomotion.
            elif slow_ready and last_p_person >= args.presence_on \
                    and last_p_move >= args.move_fallback_on:
                state = "MOVING"

            elif state == "MOVING":
                # Once short-term movement disappears, stop calling it MOVING
                # quickly; use current presence estimate to choose STATIC/EMPTY.
                if clear_hits >= max(1, args.fast_clear):
                    if last_p_person <= args.presence_off:
                        state = "EMPTY"
                    else:
                        state = "STATIC"

            else:
                # EMPTY <-> STATIC remains the slower presence problem.
                if slow_ready:
                    if state == "EMPTY":
                        if last_p_person >= args.presence_on:
                            state = "STATIC"
                    elif state == "STATIC":
                        if last_p_person <= args.presence_off:
                            state = "EMPTY"

            print(
                f"fast={score:8.5f}/{fast_thr:8.5f}  "
                f"p_person={last_p_person:5.3f}  "
                f"p_move={last_p_move:5.3f}  "
                f"=> {state:6s}  "
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
