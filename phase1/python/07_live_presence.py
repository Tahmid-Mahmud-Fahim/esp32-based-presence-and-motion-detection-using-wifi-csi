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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from presence.csi_utils import (
    EXPECTED_CSI_LEN,
    TOTAL_ACTIVE_N,
    extract_window_features,
    fieldwise_ltf_normalize,
    load_baseline,
    raw_iq_to_amplitude,
    resample,
    save_baseline,
    temporal_smooth,
)


class ReceiverStream:
    def __init__(self, name: str, port: str, baud: int, t0: float):
        self.name = name
        self.port = port
        self.baud = baud
        self.t0 = t0
        self.ser = serial.Serial(port, baudrate=baud, timeout=0.10, write_timeout=0.10)
        self.ser.reset_input_buffer()

        self.lock = threading.Lock()
        self.times = deque(maxlen=4000)
        self.amps = deque(maxlen=4000)

        self.total_lines = 0
        self.valid_packets = 0
        self.parse_bad = 0
        self.serial_errors = 0
        self.last_packet_t = None
        self.last_error = None
        self.running = True

        self.thread = threading.Thread(
            target=self._reader,
            name=f"{name}-reader",
            daemon=True,
        )

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
            self.last_packet_t = None
        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass

    def _reader(self):
        while self.running:
            try:
                raw_line = self.ser.readline()
            except serial.SerialException as exc:
                self.serial_errors += 1
                self.last_error = f"{type(exc).__name__}: {exc}"
                self.running = False
                break
            except Exception as exc:
                self.serial_errors += 1
                self.last_error = f"{type(exc).__name__}: {exc}"
                self.running = False
                break

            if not raw_line:
                continue

            self.total_lines += 1

            try:
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if not line.startswith("CSI_DATA,"):
                    continue

                row = next(csv.reader([line]))
                if len(row) != 15:
                    self.parse_bad += 1
                    continue

                channel = int(row[5])
                secondary_channel = int(row[6])
                sig_mode = int(row[7])
                cwb = int(row[9])
                stbc = int(row[10])
                csi_len = int(row[11])

                if (
                    channel != 6
                    or secondary_channel != 0
                    or sig_mode != 1
                    or cwb != 0
                    or stbc != 0
                    or csi_len != EXPECTED_CSI_LEN
                ):
                    continue

                csi_raw = np.asarray(ast.literal_eval(row[14]), dtype=np.int16)
                amp = raw_iq_to_amplitude(csi_raw)

                if amp.shape != (TOTAL_ACTIVE_N,):
                    self.parse_bad += 1
                    continue

                host_t = time.perf_counter() - self.t0

                with self.lock:
                    self.times.append(host_t)
                    self.amps.append(amp)
                    self.last_packet_t = host_t

                self.valid_packets += 1

            except Exception:
                self.parse_bad += 1
                continue

    def snapshot(self):
        with self.lock:
            if not self.times:
                return (
                    np.empty(0, dtype=np.float64),
                    np.empty((0, TOTAL_ACTIVE_N), dtype=np.float32),
                )
            return (
                np.asarray(self.times, dtype=np.float64),
                np.vstack(self.amps).astype(np.float32),
            )

    def age(self, now_rel: float) -> float:
        with self.lock:
            if self.last_packet_t is None:
                return float("inf")
            return now_rel - self.last_packet_t


def align_snapshot(t1, A1, t2, A2, fs: float, min_overlap_s: float):
    start = max(float(t1[0]), float(t2[0]))
    end = min(float(t1[-1]), float(t2[-1]))

    if end - start < min_overlap_s:
        raise RuntimeError(
            f"Not enough common calibration overlap: {end - start:.2f}s"
        )

    grid = np.arange(start, end, 1.0 / fs, dtype=np.float64)

    if len(grid) < int(fs * min_overlap_s):
        raise RuntimeError("Calibration resample grid is too short.")

    if np.max(np.diff(t1)) > 0.25:
        raise RuntimeError("RX1 has a >0.25 s gap during calibration.")
    if np.max(np.diff(t2)) > 0.25:
        raise RuntimeError("RX2 has a >0.25 s gap during calibration.")

    B1 = resample(t1, A1, grid)
    B2 = resample(t2, A2, grid)

    B1 = temporal_smooth(fieldwise_ltf_normalize(B1))
    B2 = temporal_smooth(fieldwise_ltf_normalize(B2))

    return grid, B1, B2


def build_current_empty_baseline(
    r1: ReceiverStream,
    r2: ReceiverStream,
    fs: float,
    min_overlap_s: float,
):
    t1, A1 = r1.snapshot()
    t2, A2 = r2.snapshot()

    if len(t1) < 20 or len(t2) < 20:
        raise RuntimeError("Too few CSI packets for empty calibration.")

    _, B1, B2 = align_snapshot(t1, A1, t2, A2, fs, min_overlap_s)

    return {
        "rx1": np.median(B1, axis=0).astype(np.float32),
        "rx2": np.median(B2, axis=0).astype(np.float32),
    }


def prepare_live_window(
    r1: ReceiverStream,
    r2: ReceiverStream,
    fs: float,
    window_s: float,
    now_rel: float,
    stale_s: float,
):
    age1 = r1.age(now_rel)
    age2 = r2.age(now_rel)

    if age1 > stale_s or age2 > stale_s:
        return None, f"stale stream: RX1 age={age1:.2f}s, RX2 age={age2:.2f}s"

    t1, A1 = r1.snapshot()
    t2, A2 = r2.snapshot()

    if len(t1) < 10 or len(t2) < 10:
        return None, "not enough CSI yet"

    common_end = min(float(t1[-1]), float(t2[-1]))
    common_start = common_end - window_s

    if t1[0] > common_start or t2[0] > common_start:
        return None, "waiting for full common window"

    mask1 = (t1 >= common_start - 0.25) & (t1 <= common_end + 0.05)
    mask2 = (t2 >= common_start - 0.25) & (t2 <= common_end + 0.05)

    t1w, A1w = t1[mask1], A1[mask1]
    t2w, A2w = t2[mask2], A2[mask2]

    if len(t1w) < 10 or len(t2w) < 10:
        return None, "too few packets in live window"

    gap1 = float(np.max(np.diff(t1w)))
    gap2 = float(np.max(np.diff(t2w)))
    if gap1 > 0.25 or gap2 > 0.25:
        return None, f"large gap: RX1={gap1:.3f}s, RX2={gap2:.3f}s"

    grid = np.arange(common_start, common_end, 1.0 / fs, dtype=np.float64)
    expected_n = int(round(window_s * fs))

    if len(grid) > expected_n:
        grid = grid[:expected_n]
    elif len(grid) < expected_n:
        return None, "resample grid too short"

    if grid[0] < t1w[0] or grid[-1] > t1w[-1]:
        return None, "RX1 interpolation coverage incomplete"
    if grid[0] < t2w[0] or grid[-1] > t2w[-1]:
        return None, "RX2 interpolation coverage incomplete"

    B1 = temporal_smooth(fieldwise_ltf_normalize(resample(t1w, A1w, grid)))
    B2 = temporal_smooth(fieldwise_ltf_normalize(resample(t2w, A2w, grid)))

    return (B1, B2, common_end), None


def rmse(a, b):
    return float(np.sqrt(np.mean((np.asarray(a) - np.asarray(b)) ** 2)))


def main():
    ap = argparse.ArgumentParser(
        description="Live Phase-1 detector with startup EMPTY-room calibration."
    )
    ap.add_argument("--rx1", default="COM6")
    ap.add_argument("--rx2", default="COM8")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--model", required=True)
    ap.add_argument("--training-baseline", default=None,
                    help="Optional old training baseline, used only to print drift.")
    ap.add_argument("--save-calibration", default=None,
                    help="Optional path to save the current empty calibration baseline.")
    ap.add_argument("--calibration", type=float, default=12.0)
    ap.add_argument("--countdown", type=int, default=5)
    ap.add_argument("--fs", type=float, default=25.0)
    ap.add_argument("--window", type=float, default=2.0)
    ap.add_argument("--step", type=float, default=0.5)
    ap.add_argument("--vote", type=int, default=5)
    ap.add_argument("--stale", type=float, default=1.0)
    args = ap.parse_args()

    bundle = joblib.load(args.model)
    model = bundle["model"]
    model_name = bundle.get("model_name", "unknown")
    feature_names = list(bundle["feature_names"])
    threshold = float(bundle.get("decision_threshold", 0.5))

    t0 = time.perf_counter()
    r1 = None
    r2 = None

    print("=" * 78)
    print("PHASE-1 LIVE PRESENCE - STARTUP EMPTY CALIBRATION")
    print("=" * 78)
    print(f"RX1 / RX2          : {args.rx1} / {args.rx2}")
    print(f"Model              : {model_name}")
    print(f"Decision threshold : {threshold:.3f}")
    print(f"Empty calibration  : {args.calibration:.1f} s")
    print(f"Window / step      : {args.window:.1f} s / {args.step:.1f} s")
    print()

    try:
        r1 = ReceiverStream("RX1", args.rx1, args.baud, t0)
        r2 = ReceiverStream("RX2", args.rx2, args.baud, t0)
        r1.start()
        r2.start()

        input(
            "IMPORTANT: This calibration requires an EMPTY sensing area.\n"
            "Press Enter when you are ready to leave the area..."
        )

        print(f"\nLeave the sensing area. Calibration starts in {args.countdown}s.")
        for s in range(args.countdown, 0, -1):
            print(s, flush=True)
            time.sleep(1.0)

        # Exclude all CSI collected while the user was at the terminal.
        r1.clear()
        r2.clear()

        print(f"\nCalibrating EMPTY room for {args.calibration:.1f}s...")
        start_valid1 = r1.valid_packets
        start_valid2 = r2.valid_packets
        time.sleep(args.calibration)

        if not r1.running:
            raise RuntimeError(f"RX1 reader stopped: {r1.last_error}")
        if not r2.running:
            raise RuntimeError(f"RX2 reader stopped: {r2.last_error}")

        got1 = r1.valid_packets - start_valid1
        got2 = r2.valid_packets - start_valid2
        print(f"Calibration packets: RX1={got1}, RX2={got2}")

        current_baseline = build_current_empty_baseline(
            r1,
            r2,
            fs=args.fs,
            min_overlap_s=max(5.0, args.calibration - 2.0),
        )

        if args.training_baseline:
            old = load_baseline(args.training_baseline)
            print(
                "Current-vs-training baseline RMSE: "
                f"RX1={rmse(current_baseline['rx1'], old['rx1']):.6f}, "
                f"RX2={rmse(current_baseline['rx2'], old['rx2']):.6f}"
            )

        if args.save_calibration:
            save_path = Path(args.save_calibration)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_baseline(save_path, current_baseline)
            print(f"Saved current EMPTY baseline: {save_path}")

        # Start live classification on entirely fresh post-calibration samples.
        r1.clear()
        r2.clear()

        print("\nCalibration complete.")
        print("You may now enter/leave the sensing area.")
        print("Waiting for a fresh 2-second live window...\n")

        recent = deque(maxlen=max(1, args.vote))
        next_infer = time.perf_counter() + args.window + 0.25
        last_used_common_end = -1.0

        while True:
            if not r1.running:
                raise RuntimeError(f"RX1 reader stopped: {r1.last_error}")
            if not r2.running:
                raise RuntimeError(f"RX2 reader stopped: {r2.last_error}")

            now = time.perf_counter()
            if now < next_infer:
                time.sleep(min(0.05, next_infer - now))
                continue

            next_infer += args.step
            now_rel = time.perf_counter() - t0

            prepared, reason = prepare_live_window(
                r1,
                r2,
                fs=args.fs,
                window_s=args.window,
                now_rel=now_rel,
                stale_s=args.stale,
            )

            if prepared is None:
                print(
                    f"[waiting] {reason} | "
                    f"RX1={r1.valid_packets} RX2={r2.valid_packets}"
                )
                continue

            W1, W2, common_end = prepared

            if common_end <= last_used_common_end + 1e-6:
                print("[waiting] common RX window has not advanced")
                continue
            last_used_common_end = common_end

            feat = extract_window_features(W1, W2, current_baseline)

            if feat.shape[0] != len(feature_names):
                raise RuntimeError(
                    f"Feature mismatch: live={feat.shape[0]}, "
                    f"model={len(feature_names)}"
                )

            X_live = pd.DataFrame([feat], columns=feature_names)
            prob = float(model.predict_proba(X_live)[0, 1])

            raw_person = prob >= threshold
            recent.append(1 if raw_person else 0)

            person_votes = int(sum(recent))
            empty_votes = len(recent) - person_votes
            stable_person = person_votes > empty_votes

            raw_label = "PERSON" if raw_person else "EMPTY"
            stable_label = "PERSON" if stable_person else "EMPTY"

            print(
                f"prob={prob:6.3f}  "
                f"raw={raw_label:6s}  "
                f"vote={person_votes}/{len(recent)}  "
                f"=> {stable_label:6s}  "
                f"| RX1={r1.valid_packets:5d} RX2={r2.valid_packets:5d}"
            )

    except KeyboardInterrupt:
        print("\nStopping live detector...")

    except Exception as exc:
        print("\nLIVE DETECTOR ERROR")
        print(f"{type(exc).__name__}: {exc}")

    finally:
        if r1 is not None:
            r1.stop()
        if r2 is not None:
            r2.stop()

        if r1 is not None and r2 is not None:
            print(
                f"\nRX1 valid={r1.valid_packets}, parse_bad={r1.parse_bad}, "
                f"serial_errors={r1.serial_errors}"
            )
            print(
                f"RX2 valid={r2.valid_packets}, parse_bad={r2.parse_bad}, "
                f"serial_errors={r2.serial_errors}"
            )

        print("Stopped.")


if __name__ == "__main__":
    main()
