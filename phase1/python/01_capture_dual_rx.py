"""Stage-1 dual-RX CSI capture: NO CAMERA, NO VIDEO.

Example:
    python 01_capture_dual_rx.py --rx1 COM6 --rx2 COM8 --label engineering_empty --duration 60 --out ../data/raw

What this version fixes:
1. Adds a configurable countdown (default: 5 s) after ENTER.
2. Starts the requested capture duration only after the countdown finishes.
3. Cleanly stops both RX workers at the requested duration.
4. Fixes the summary deadlock from calling rate_hz() while holding a non-reentrant lock.
5. Flushes/closes both CSV files and releases both COM ports before exiting.
6. Handles Ctrl+C cleanly.
7. Keeps a shared PC monotonic time base for RX1/RX2 alignment.
"""

import argparse
import csv
import os
import serial
import threading
import time
from collections import Counter

BAUD = 921600
SERIAL_TIMEOUT_S = 0.20
DEFAULT_COUNTDOWN_S = 5

HEADER = [
    "pc_monotonic_ns", "pc_elapsed_s", "seq", "device_timestamp_us",
    "rssi", "noise_floor", "channel", "secondary_channel", "sig_mode",
    "mcs", "cwb", "stbc", "csi_len", "first_word_invalid",
    "firmware_dropped", "csi_data"
]


class RxStats:
    def __init__(self):
        self.count = 0
        self.parse_errors = 0
        self.first_pc_ns = None
        self.last_pc_ns = None
        self.lengths = Counter()
        self.first_word_invalid = 0
        self.max_fw_dropped = 0
        self.last_seq = None
        self.seq_gaps = 0
        self.fatal_error = None
        self.lock = threading.Lock()

    def add(self, pc_ns, seq, csi_len, first_invalid, fw_dropped):
        with self.lock:
            if self.first_pc_ns is None:
                self.first_pc_ns = pc_ns

            self.last_pc_ns = pc_ns

            if self.last_seq is not None and seq > self.last_seq + 1:
                self.seq_gaps += seq - self.last_seq - 1

            self.last_seq = seq
            self.count += 1
            self.lengths[csi_len] += 1
            self.first_word_invalid += int(first_invalid)
            self.max_fw_dropped = max(self.max_fw_dropped, fw_dropped)

    def add_parse_error(self):
        with self.lock:
            self.parse_errors += 1
            return self.parse_errors

    def set_fatal_error(self, message):
        with self.lock:
            self.fatal_error = str(message)

    def snapshot(self):
        """Return a consistent stats snapshot without nested-lock deadlocks."""
        with self.lock:
            count = self.count
            first_pc_ns = self.first_pc_ns
            last_pc_ns = self.last_pc_ns

            if (
                count >= 2
                and first_pc_ns is not None
                and last_pc_ns is not None
                and last_pc_ns > first_pc_ns
            ):
                seconds = (last_pc_ns - first_pc_ns) / 1e9
                rate_hz = (count - 1) / seconds
            else:
                rate_hz = 0.0

            return {
                "count": count,
                "rate_hz": rate_hz,
                "parse_errors": self.parse_errors,
                "lengths": dict(self.lengths),
                "first_word_invalid": self.first_word_invalid,
                "max_fw_dropped": self.max_fw_dropped,
                "seq_gaps": self.seq_gaps,
                "fatal_error": self.fatal_error,
            }

    def rate_hz(self):
        return self.snapshot()["rate_hz"]

    def packet_count(self):
        with self.lock:
            return self.count


def parse_csi_line(line):
    if not line.startswith("CSI_DATA,"):
        return None

    row = next(csv.reader([line]))
    if len(row) != 15:
        raise ValueError(f"expected 15 fields, got {len(row)}")

    csi_text = row[14].strip()
    if not (csi_text.startswith("[") and csi_text.endswith("]")):
        raise ValueError("CSI data field is not a bracketed list")

    body = csi_text[1:-1].strip()
    values = [int(x) for x in body.split(",")] if body else []

    result = {
        "seq": int(row[1]),
        "device_timestamp_us": int(row[2]),
        "rssi": int(row[3]),
        "noise_floor": int(row[4]),
        "channel": int(row[5]),
        "secondary_channel": int(row[6]),
        "sig_mode": int(row[7]),
        "mcs": int(row[8]),
        "cwb": int(row[9]),
        "stbc": int(row[10]),
        "csi_len": int(row[11]),
        "first_word_invalid": int(row[12]),
        "firmware_dropped": int(row[13]),
        "values": values,
    }

    if len(values) != result["csi_len"]:
        raise ValueError(
            f"CSI length mismatch: metadata={result['csi_len']} "
            f"parsed={len(values)}"
        )

    return result


def capture_receiver(
    name,
    port,
    out_path,
    start_event,
    stop_event,
    ready_event,
    timing,
    stats,
):
    try:
        with serial.Serial(
            port=port,
            baudrate=BAUD,
            timeout=SERIAL_TIMEOUT_S,
        ) as ser, open(
            out_path,
            "w",
            newline="",
            encoding="utf-8",
        ) as f:

            writer = csv.writer(f)
            writer.writerow(HEADER)
            f.flush()

            # Remove anything already waiting from boot/previous CSI output.
            ser.reset_input_buffer()

            print(f"[{name}] opened {port} @ {BAUD} baud")
            ready_event.set()

            # Wait until the 5-second countdown has completed.
            while not start_event.is_set():
                if stop_event.is_set():
                    return
                start_event.wait(timeout=0.05)

            if stop_event.is_set():
                return

            # Discard all bytes accumulated while the user was leaving the room.
            ser.reset_input_buffer()

            t0_ns = timing["t0_ns"]
            deadline_ns = timing["deadline_ns"]

            while not stop_event.is_set():
                if time.perf_counter_ns() >= deadline_ns:
                    break

                raw = ser.readline()
                if not raw:
                    continue

                pc_ns = time.perf_counter_ns()

                # Do not save a packet whose completed line arrived after the
                # requested experiment window.
                if pc_ns > deadline_ns:
                    break

                line = raw.decode(
                    "utf-8",
                    errors="ignore"
                ).strip("\r\n\x00 ")

                if not line.startswith("CSI_DATA,"):
                    continue

                try:
                    p = parse_csi_line(line)
                    if p is None:
                        continue

                    elapsed = (pc_ns - t0_ns) / 1e9

                    writer.writerow([
                        pc_ns,
                        f"{elapsed:.9f}",
                        p["seq"],
                        p["device_timestamp_us"],
                        p["rssi"],
                        p["noise_floor"],
                        p["channel"],
                        p["secondary_channel"],
                        p["sig_mode"],
                        p["mcs"],
                        p["cwb"],
                        p["stbc"],
                        p["csi_len"],
                        p["first_word_invalid"],
                        p["firmware_dropped"],
                        "[" + ",".join(map(str, p["values"])) + "]",
                    ])

                    stats.add(
                        pc_ns,
                        p["seq"],
                        p["csi_len"],
                        p["first_word_invalid"],
                        p["firmware_dropped"],
                    )

                except Exception as exc:
                    error_number = stats.add_parse_error()
                    if error_number <= 5:
                        print(f"\n[{name}] parse error: {exc}")

            f.flush()

    except Exception as exc:
        stats.set_fatal_error(exc)
        print(f"\n[{name}] FATAL: {exc}")
        stop_event.set()

    finally:
        # Always signal readiness so main() cannot wait forever if opening
        # the port/file failed.
        ready_event.set()


def print_summary(name, stats):
    s = stats.snapshot()

    print(f"\n{name} summary")
    print(f"  packets saved       : {s['count']}")
    print(f"  measured rate       : {s['rate_hz']:.2f} Hz")
    print(f"  CSI lengths         : {s['lengths']}")
    print(f"  first_word_invalid  : {s['first_word_invalid']}")
    print(f"  sequence gaps       : {s['seq_gaps']}")
    print(f"  firmware drop count : {s['max_fw_dropped']}")
    print(f"  parse errors        : {s['parse_errors']}")

    if s["fatal_error"]:
        print(f"  FATAL ERROR         : {s['fatal_error']}")


def countdown(seconds):
    if seconds <= 0:
        return

    print("\nLeave the sensing area now.")
    for remaining in range(seconds, 0, -1):
        print(f"Starting capture in {remaining}...", flush=True)
        time.sleep(1.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--rx1",
        required=True,
        help="RX1 serial port, e.g. COM6",
    )
    ap.add_argument(
        "--rx2",
        required=True,
        help="RX2 serial port, e.g. COM8",
    )
    ap.add_argument(
        "--label",
        required=True,
        help="e.g. engineering_empty or person_center_01",
    )
    ap.add_argument(
        "--duration",
        type=float,
        default=60.0,
        help="Actual CSI recording duration in seconds",
    )
    ap.add_argument(
        "--countdown",
        type=int,
        default=DEFAULT_COUNTDOWN_S,
        help="Seconds to wait after ENTER before recording starts (default: 5)",
    )
    ap.add_argument(
        "--out",
        default="data/raw",
        help="Output directory",
    )
    args = ap.parse_args()

    if args.rx1.lower() == args.rx2.lower():
        raise SystemExit("RX1 and RX2 must be different serial ports")

    if args.duration <= 0:
        raise SystemExit("--duration must be greater than 0")

    if args.countdown < 0:
        raise SystemExit("--countdown cannot be negative")

    os.makedirs(args.out, exist_ok=True)

    rx1_path = os.path.join(
        args.out,
        f"{args.label}_RX1.csv",
    )
    rx2_path = os.path.join(
        args.out,
        f"{args.label}_RX2.csv",
    )

    print("=" * 64)
    print("STAGE-1 DUAL-RX CSI CAPTURE — NO CAMERA")
    print(f"RX1      : {args.rx1}")
    print(f"RX2      : {args.rx2}")
    print(f"Duration : {args.duration:.1f} s")
    print(f"Countdown: {args.countdown} s")
    print(f"Label    : {args.label}")
    print(f"Output   : {args.out}")
    print("=" * 64)

    start_event = threading.Event()
    stop_event = threading.Event()
    rx1_ready = threading.Event()
    rx2_ready = threading.Event()

    timing = {
        "t0_ns": None,
        "deadline_ns": None,
    }

    s1 = RxStats()
    s2 = RxStats()

    t1 = threading.Thread(
        target=capture_receiver,
        args=(
            "RX1",
            args.rx1,
            rx1_path,
            start_event,
            stop_event,
            rx1_ready,
            timing,
            s1,
        ),
        daemon=False,
    )

    t2 = threading.Thread(
        target=capture_receiver,
        args=(
            "RX2",
            args.rx2,
            rx2_path,
            start_event,
            stop_event,
            rx2_ready,
            timing,
            s2,
        ),
        daemon=False,
    )

    # Open both receivers first. They wait at start_event and do not record yet.
    t1.start()
    t2.start()

    print("Opening both receivers...")

    while not (rx1_ready.is_set() and rx2_ready.is_set()):
        if stop_event.is_set():
            break
        time.sleep(0.05)

    if stop_event.is_set():
        # Unblock any worker still waiting.
        start_event.set()
        t1.join(timeout=2.0)
        t2.join(timeout=2.0)

        print_summary("RX1", s1)
        print_summary("RX2", s2)
        raise SystemExit("\nCapture could not start because a receiver failed.")

    try:
        input("\nPress ENTER when TX, RX1 and RX2 are powered and ready... ")

        countdown(args.countdown)

        # The actual requested experiment duration begins HERE.
        t0_ns = time.perf_counter_ns()
        duration_ns = int(args.duration * 1e9)

        timing["t0_ns"] = t0_ns
        timing["deadline_ns"] = t0_ns + duration_ns

        print("\nCAPTURE STARTED")
        start_event.set()

        last_printed_second = -1

        while True:
            now_ns = time.perf_counter_ns()
            elapsed = (now_ns - t0_ns) / 1e9

            if elapsed >= args.duration:
                break

            whole_second = int(elapsed)
            if whole_second != last_printed_second:
                last_printed_second = whole_second
                shown = min(elapsed, args.duration)

                print(
                    f"\r{shown:6.1f}/{args.duration:.1f}s | "
                    f"RX1 {s1.packet_count():5d} ({s1.rate_hz():5.1f} Hz) | "
                    f"RX2 {s2.packet_count():5d} ({s2.rate_hz():5.1f} Hz)",
                    end="",
                    flush=True,
                )

            time.sleep(0.05)

        # Print the exact requested end point rather than 16/15, 61/60, etc.
        print(
            f"\r{args.duration:6.1f}/{args.duration:.1f}s | "
            f"RX1 {s1.packet_count():5d} ({s1.rate_hz():5.1f} Hz) | "
            f"RX2 {s2.packet_count():5d} ({s2.rate_hz():5.1f} Hz)",
            end="",
            flush=True,
        )

    except KeyboardInterrupt:
        print("\n\n[ABORT] Ctrl+C received. Stopping capture safely...")

    finally:
        stop_event.set()

        # If Ctrl+C happened before capture started, release waiting workers.
        start_event.set()

        # readline() has a short timeout, so both threads should finish promptly.
        t1.join(timeout=3.0)
        t2.join(timeout=3.0)

    print("\n\nCAPTURE COMPLETE")

    if t1.is_alive():
        print("[WARNING] RX1 worker did not stop within 3 seconds.")
    if t2.is_alive():
        print("[WARNING] RX2 worker did not stop within 3 seconds.")

    print_summary("RX1", s1)
    print_summary("RX2", s2)

    print(f"\nSaved:\n  {rx1_path}\n  {rx2_path}")

    r1 = s1.rate_hz()
    r2 = s2.rate_hz()

    if s1.snapshot()["fatal_error"] or s2.snapshot()["fatal_error"]:
        print("\n[FAIL] A receiver reported a fatal error. Do NOT use this capture.")
    elif min(r1, r2) < 35:
        print(
            "\n[CHECK] One or both receivers are below 35 Hz. "
            "Do NOT start the full dataset yet."
        )
    else:
        print(
            "\n[OK] Acquisition rate is suitable for the first "
            "presence experiment."
        )


if __name__ == "__main__":
    main()
