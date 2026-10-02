from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, Iterable, Tuple

import numpy as np
import pandas as pd
from scipy.interpolate import interp1d
from scipy.signal import savgol_filter


# Phase-1 acquisition contract for the current ESP32-S3 firmware:
#   sig_mode = 1       (HT / 802.11n)
#   secondary_channel = 0
#   cwb = 0            (20 MHz)
#   stbc = 0
#   csi_len = 256
#
# For this layout, the CSI buffer contains:
#   128 bytes LLTF  = 64 complex values
#   128 bytes HT-LTF = 64 complex values
#
# Each complex value is stored as [imag, real].
#
# We keep active 20 MHz subcarriers only and normalize LLTF/HT-LTF
# separately so changes in the relative scale of the two LTF fields do
# not become an artificial "presence" feature.

EXPECTED_CSI_LEN = 256
MAX_INTERP_GAP_S = 0.25

# ESP-IDF CSI order for each 64-complex field:
# [0, +1, +2, ... +31, -32, -31, ... -1]
#
# LLTF active 20 MHz carriers: +1..+26 and -26..-1.
# The first two complex values of the whole CSI buffer may be invalid on
# affected packets. To keep a fixed feature dimension for every packet,
# we conservatively exclude LLTF complex indices 0 and +1 for ALL packets.
#
# Therefore LLTF keeps +2..+26 (25) and -26..-1 (26) = 51 values.
LLTF_ACTIVE_IDX = np.r_[
    np.arange(2, 27, dtype=int),
    np.arange(38, 64, dtype=int),
]

# HT-LTF active 20 MHz carriers: +1..+28 and -28..-1 = 56 values.
HTLTF_ACTIVE_IDX = np.r_[
    np.arange(1, 29, dtype=int),
    np.arange(36, 64, dtype=int),
]

LLTF_N = len(LLTF_ACTIVE_IDX)     # 51
HTLTF_N = len(HTLTF_ACTIVE_IDX)   # 56
TOTAL_ACTIVE_N = LLTF_N + HTLTF_N # 107


def parse_csi_cell(cell) -> np.ndarray:
    """Parse a '[1,2,...]' CSI CSV cell into a one-dimensional int16 array."""
    if isinstance(cell, (list, tuple, np.ndarray)):
        arr = np.asarray(cell, dtype=np.int16)
    else:
        value = ast.literal_eval(str(cell))
        arr = np.asarray(value, dtype=np.int16)

    if arr.ndim != 1:
        raise ValueError("CSI cell must be one-dimensional")

    return arr


def _iq_bytes_to_amplitude(raw_field: np.ndarray) -> np.ndarray:
    """Convert one [imag, real, imag, real, ...] field to amplitude."""
    raw_field = np.asarray(raw_field, dtype=np.float32)

    if raw_field.ndim != 1:
        raise ValueError("CSI field must be one-dimensional")

    if raw_field.size % 2:
        raise ValueError("CSI field has an odd number of I/Q bytes")

    imag = raw_field[0::2]
    real = raw_field[1::2]

    return np.sqrt(real * real + imag * imag)


def raw_iq_to_amplitude(
    raw: np.ndarray,
    drop_first_two_complex: bool = True,
) -> np.ndarray:
    """Convert one Phase-1 ESP32-S3 CSI packet to active-subcarrier amplitudes.

    Current Phase-1 firmware retains HT, 20 MHz, non-STBC frames with
    csi_len=256. ESP-IDF places LLTF first and HT-LTF second.

    This function:
      1. splits LLTF and HT-LTF,
      2. converts [imag, real] pairs to amplitude,
      3. removes guard/DC positions,
      4. conservatively excludes the first potentially-invalid LLTF values,
      5. returns [LLTF_active, HTLTF_active].

    The legacy `drop_first_two_complex` argument is retained only for API
    compatibility with the earlier Phase-1 scripts. The fixed active-index
    selection already handles the potentially-invalid first CSI word.
    """
    raw = np.asarray(raw, dtype=np.float32)

    if raw.ndim != 1:
        raise ValueError("CSI packet must be one-dimensional")

    if raw.size != EXPECTED_CSI_LEN:
        raise ValueError(
            f"Expected {EXPECTED_CSI_LEN} CSI bytes for Phase-1 HT20 layout, "
            f"got {raw.size}"
        )

    lltf_raw = raw[:128]
    htltf_raw = raw[128:256]

    lltf_amp = _iq_bytes_to_amplitude(lltf_raw)
    htltf_amp = _iq_bytes_to_amplitude(htltf_raw)

    if len(lltf_amp) != 64 or len(htltf_amp) != 64:
        raise ValueError("Unexpected LLTF/HT-LTF complex-value count")

    lltf_active = lltf_amp[LLTF_ACTIVE_IDX]
    htltf_active = htltf_amp[HTLTF_ACTIVE_IDX]

    return np.concatenate([lltf_active, htltf_active]).astype(np.float32)


def _filter_expected_layout(df: pd.DataFrame, path: Path) -> pd.DataFrame:
    """Keep the fixed PHY layout used by the current Phase-1 firmware."""
    if "csi_len" not in df.columns:
        raise ValueError(f"{path}: missing csi_len")

    # Keep the modal CSI length first, then require the known Phase-1 length.
    modal_len = int(df["csi_len"].mode().iloc[0])
    df = df[df["csi_len"] == modal_len].copy()

    if modal_len != EXPECTED_CSI_LEN:
        raise ValueError(
            f"{path}: expected Phase-1 CSI length {EXPECTED_CSI_LEN}, "
            f"but modal length is {modal_len}"
        )

    expected_meta = {
        "sig_mode": 1,
        "secondary_channel": 0,
        "cwb": 0,
        "stbc": 0,
    }

    for col, expected in expected_meta.items():
        if col in df.columns:
            df = df[df[col] == expected].copy()

    # Do not silently mix Wi-Fi channels within one session.
    if "channel" in df.columns and len(df):
        modal_channel = int(df["channel"].mode().iloc[0])
        df = df[df["channel"] == modal_channel].copy()

    if len(df) < 10:
        raise ValueError(
            f"{path}: insufficient packets after Phase-1 PHY-layout filtering"
        )

    return df


def load_receiver_csv(
    path: str | Path,
    drop_first_two_complex: bool = True,
) -> Tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    """Load one receiver CSV.

    Returns:
        time_seconds,
        amplitude_matrix with 107 active carriers
        (51 LLTF + 56 HT-LTF),
        filtered metadata dataframe.

    Time is the shared PC elapsed time created by the dual-RX capture script.
    """
    path = Path(path)
    df = pd.read_csv(path)

    required = {"pc_elapsed_s", "csi_len", "csi_data"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")

    if len(df) < 10:
        raise ValueError(f"{path}: too few CSI packets ({len(df)})")

    df = _filter_expected_layout(df, path)

    amps = []
    good_idx = []

    for idx, cell in zip(df.index, df["csi_data"]):
        try:
            a = raw_iq_to_amplitude(
                parse_csi_cell(cell),
                drop_first_two_complex=drop_first_two_complex,
            )

            if len(a) != TOTAL_ACTIVE_N:
                continue

            amps.append(a)
            good_idx.append(idx)

        except Exception:
            continue

    if len(amps) < 10:
        raise ValueError(f"{path}: insufficient valid CSI after parsing")

    df = df.loc[good_idx].reset_index(drop=True)
    t = df["pc_elapsed_s"].to_numpy(dtype=float)
    A = np.vstack(amps).astype(np.float32)

    order = np.argsort(t)
    t = t[order]
    A = A[order]
    df = df.iloc[order].reset_index(drop=True)

    # Remove duplicate/non-increasing host timestamps.
    keep = np.r_[True, np.diff(t) > 1e-9]

    t = t[keep]
    A = A[keep]
    df = df.loc[keep].reset_index(drop=True)

    if len(t) < 10:
        raise ValueError(f"{path}: too few unique timestamps")

    # Do not bridge a long acquisition outage by linear interpolation.
    if len(t) > 1:
        max_gap = float(np.max(np.diff(t)))
        if max_gap > MAX_INTERP_GAP_S:
            raise ValueError(
                f"{path}: host-time gap {max_gap:.3f}s exceeds "
                f"{MAX_INTERP_GAP_S:.3f}s"
            )

    return t, A, df


def robust_subcarrier_normalize(A: np.ndarray) -> np.ndarray:
    """Normalize each packet by its median amplitude.

    Kept for compatibility. For Phase-1 dual-LTF CSI, prefer
    fieldwise_ltf_normalize(), which prevents LLTF/HT-LTF relative scaling
    from becoming an artificial feature.
    """
    A = np.asarray(A, dtype=np.float32)

    med = np.median(A, axis=1, keepdims=True)
    med = np.where(np.abs(med) < 1e-6, 1.0, med)

    return A / med


def fieldwise_ltf_normalize(A: np.ndarray) -> np.ndarray:
    """Normalize LLTF and HT-LTF separately for every packet."""
    A = np.asarray(A, dtype=np.float32)

    if A.ndim != 2 or A.shape[1] != TOTAL_ACTIVE_N:
        raise ValueError(
            f"Expected amplitude matrix with {TOTAL_ACTIVE_N} columns, "
            f"got shape {A.shape}"
        )

    lltf = A[:, :LLTF_N]
    htltf = A[:, LLTF_N:]

    lltf_med = np.median(lltf, axis=1, keepdims=True)
    htltf_med = np.median(htltf, axis=1, keepdims=True)

    lltf_med = np.where(np.abs(lltf_med) < 1e-6, 1.0, lltf_med)
    htltf_med = np.where(np.abs(htltf_med) < 1e-6, 1.0, htltf_med)

    lltf_n = lltf / lltf_med
    htltf_n = htltf / htltf_med

    return np.concatenate([lltf_n, htltf_n], axis=1).astype(np.float32)


def temporal_smooth(A: np.ndarray, window: int = 5) -> np.ndarray:
    """Light Savitzky-Golay smoothing along time."""
    if len(A) < window or window < 3:
        return A

    if window % 2 == 0:
        window += 1

    if len(A) < window:
        return A

    return savgol_filter(
        A,
        window_length=window,
        polyorder=2,
        axis=0,
        mode="interp",
    ).astype(np.float32)


def resample(
    t: np.ndarray,
    A: np.ndarray,
    grid: np.ndarray,
) -> np.ndarray:
    if grid[0] < t[0] or grid[-1] > t[-1]:
        raise ValueError("Requested grid is outside available receiver time span")

    f = interp1d(
        t,
        A,
        axis=0,
        kind="linear",
        bounds_error=True,
    )

    return f(grid).astype(np.float32)


def align_dual_rx(
    rx1_csv: str | Path,
    rx2_csv: str | Path,
    fs: float = 25.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load both receivers and place them on one shared host-time grid."""
    if fs <= 0:
        raise ValueError("fs must be greater than zero")

    t1, A1, _ = load_receiver_csv(rx1_csv)
    t2, A2, _ = load_receiver_csv(rx2_csv)

    start = max(float(t1[0]), float(t2[0]))
    end = min(float(t1[-1]), float(t2[-1]))

    if end - start < 4.0:
        raise ValueError("RX1/RX2 common overlap is too short")

    dt = 1.0 / fs
    grid = np.arange(start, end, dt, dtype=np.float64)

    # Resample amplitudes first, then normalize LLTF and HT-LTF separately.
    B1 = resample(t1, A1, grid)
    B2 = resample(t2, A2, grid)

    B1 = fieldwise_ltf_normalize(B1)
    B2 = fieldwise_ltf_normalize(B2)

    B1 = temporal_smooth(B1)
    B2 = temporal_smooth(B2)

    return grid, B1, B2


def window_slices(
    n: int,
    fs: float,
    window_s: float,
    step_s: float,
) -> Iterable[slice]:
    w = int(round(window_s * fs))
    step = int(round(step_s * fs))

    if w < 2 or step < 1:
        raise ValueError("Invalid window/step")

    for s in range(0, n - w + 1, step):
        yield slice(s, s + w)


def fit_empty_baseline(
    session_pairs: Iterable[Tuple[str, str]],
    fs: float = 25.0,
) -> Dict[str, np.ndarray]:
    """Fit templates using TRAIN empty sessions only."""
    r1_profiles = []
    r2_profiles = []

    for p1, p2 in session_pairs:
        _, A1, A2 = align_dual_rx(p1, p2, fs=fs)
        r1_profiles.append(np.median(A1, axis=0))
        r2_profiles.append(np.median(A2, axis=0))

    if not r1_profiles:
        raise ValueError("No empty training sessions available for baseline")

    n1 = min(map(len, r1_profiles))
    n2 = min(map(len, r2_profiles))

    b1 = np.median(
        np.vstack([x[:n1] for x in r1_profiles]),
        axis=0,
    ).astype(np.float32)

    b2 = np.median(
        np.vstack([x[:n2] for x in r2_profiles]),
        axis=0,
    ).astype(np.float32)

    return {"rx1": b1, "rx2": b2}


def _receiver_features(
    W: np.ndarray,
    baseline: np.ndarray,
) -> np.ndarray:
    n = min(W.shape[1], len(baseline))

    W = W[:, :n]
    b = baseline[:n]

    mean_profile = np.mean(W, axis=0)
    std_profile = np.std(W, axis=0)
    diff = np.diff(W, axis=0)
    baseline_abs = np.abs(mean_profile - b)

    features = np.array([
        np.mean(mean_profile),
        np.std(mean_profile),
        np.median(mean_profile),
        np.mean(std_profile),
        np.median(std_profile),
        np.max(std_profile),
        np.mean(np.abs(diff)) if len(diff) else 0.0,
        np.std(diff) if len(diff) else 0.0,
        np.mean(baseline_abs),
        np.median(baseline_abs),
        np.max(baseline_abs),
        np.sqrt(np.mean((mean_profile - b) ** 2)),
        (
            np.corrcoef(mean_profile, b)[0, 1]
            if np.std(mean_profile) > 1e-8 and np.std(b) > 1e-8
            else 0.0
        ),
    ], dtype=np.float32)

    return np.nan_to_num(
        features,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )


def extract_window_features(
    W1: np.ndarray,
    W2: np.ndarray,
    baseline: Dict[str, np.ndarray],
) -> np.ndarray:
    f1 = _receiver_features(W1, baseline["rx1"])
    f2 = _receiver_features(W2, baseline["rx2"])

    cross = np.array([
        abs(f1[8] - f2[8]),
        (f1[8] + f2[8]) / 2.0,
        max(f1[8], f2[8]),
        (f1[6] + f2[6]) / 2.0,
        max(f1[6], f2[6]),
    ], dtype=np.float32)

    return np.concatenate([f1, f2, cross])


def session_features(
    rx1_csv: str | Path,
    rx2_csv: str | Path,
    baseline: Dict[str, np.ndarray],
    fs: float = 25.0,
    window_s: float = 2.0,
    step_s: float = 0.5,
) -> Tuple[np.ndarray, np.ndarray]:
    grid, A1, A2 = align_dual_rx(
        rx1_csv,
        rx2_csv,
        fs=fs,
    )

    feats = []
    centers = []

    for sl in window_slices(
        len(grid),
        fs,
        window_s,
        step_s,
    ):
        feats.append(
            extract_window_features(
                A1[sl],
                A2[sl],
                baseline,
            )
        )
        centers.append(float(np.mean(grid[sl])))

    if not feats:
        raise ValueError("Session too short for requested window")

    return np.vstack(feats), np.asarray(centers)


def save_baseline(
    path: str | Path,
    baseline: Dict[str, np.ndarray],
) -> None:
    np.savez(
        path,
        rx1=baseline["rx1"],
        rx2=baseline["rx2"],
    )


def load_baseline(
    path: str | Path,
) -> Dict[str, np.ndarray]:
    z = np.load(path)

    return {
        "rx1": z["rx1"].astype(np.float32),
        "rx2": z["rx2"].astype(np.float32),
    }


def read_manifest(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    needed = {
        "session_id",
        "label",
        "split",
        "rx1_csv",
        "rx2_csv",
    }

    missing = needed - set(df.columns)
    if missing:
        raise ValueError(
            f"Manifest missing columns: {sorted(missing)}"
        )

    df["label"] = df["label"].str.lower().str.strip()
    df["split"] = df["split"].str.lower().str.strip()

    bad_label = ~df["label"].isin(["empty", "person"])
    bad_split = ~df["split"].isin(["train", "val", "test"])

    if bad_label.any():
        raise ValueError(
            "Unsupported labels: "
            f"{df.loc[bad_label, 'label'].unique().tolist()}"
        )

    if bad_split.any():
        raise ValueError(
            "Unsupported splits: "
            f"{df.loc[bad_split, 'split'].unique().tolist()}"
        )

    return df
