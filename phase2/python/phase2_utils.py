from __future__ import annotations
import numpy as np

RX_MOTION_FEATURE_NAMES = [
    "temporal_std_mean", "temporal_std_median", "temporal_std_p90", "temporal_std_max",
    "absdiff_mean", "absdiff_median", "absdiff_p90", "absdiff_max",
    "rmsdiff_mean", "rmsdiff_p90",
    "range_mean", "range_p90",
    "packet_change_mean", "packet_change_std", "packet_change_p90", "packet_change_max",
    "bandpower_mean", "bandpower_p90",
]

CROSS_MOTION_FEATURE_NAMES = [
    "cross_temporal_std_mean_avg",
    "cross_temporal_std_mean_max",
    "cross_absdiff_mean_avg",
    "cross_absdiff_mean_max",
    "cross_packet_change_mean_avg",
    "cross_packet_change_mean_max",
    "cross_packet_change_mean_absdiff",
    "cross_bandpower_mean_avg",
]

MOTION_FEATURE_NAMES = (
    [f"rx1_motion_{x}" for x in RX_MOTION_FEATURE_NAMES]
    + [f"rx2_motion_{x}" for x in RX_MOTION_FEATURE_NAMES]
    + CROSS_MOTION_FEATURE_NAMES
)

def _p90(x):
    return float(np.percentile(x, 90))

def _receiver_motion_features(W: np.ndarray, fs: float) -> np.ndarray:
    W = np.asarray(W, dtype=np.float32)
    if W.ndim != 2 or W.shape[0] < 4:
        raise ValueError(f"Invalid CSI window shape: {W.shape}")

    stdp = np.std(W, axis=0)
    d = np.diff(W, axis=0)
    ad = np.abs(d)
    absdiff = np.mean(ad, axis=0)
    rmsdiff = np.sqrt(np.mean(d * d, axis=0))
    rangep = np.ptp(W, axis=0)
    packet_change = np.sqrt(np.mean(d * d, axis=1))

    centered = W - np.mean(W, axis=0, keepdims=True)
    spec = np.fft.rfft(centered, axis=0)
    power = (np.abs(spec) ** 2) / max(1, W.shape[0])
    freqs = np.fft.rfftfreq(W.shape[0], d=1.0 / fs)
    mask = (freqs >= 0.5) & (freqs <= 5.0)
    bandp = np.log1p(np.mean(power[mask], axis=0)) if np.any(mask) else np.zeros(W.shape[1])

    f = np.array([
        np.mean(stdp), np.median(stdp), _p90(stdp), np.max(stdp),
        np.mean(absdiff), np.median(absdiff), _p90(absdiff), np.max(absdiff),
        np.mean(rmsdiff), _p90(rmsdiff),
        np.mean(rangep), _p90(rangep),
        np.mean(packet_change), np.std(packet_change), _p90(packet_change), np.max(packet_change),
        np.mean(bandp), _p90(bandp),
    ], dtype=np.float32)

    return np.nan_to_num(f, nan=0.0, posinf=0.0, neginf=0.0)

def extract_motion_features(W1: np.ndarray, W2: np.ndarray, fs: float = 25.0) -> np.ndarray:
    f1 = _receiver_motion_features(W1, fs)
    f2 = _receiver_motion_features(W2, fs)

    cross = np.array([
        (f1[0] + f2[0]) / 2.0, max(f1[0], f2[0]),
        (f1[4] + f2[4]) / 2.0, max(f1[4], f2[4]),
        (f1[12] + f2[12]) / 2.0, max(f1[12], f2[12]),
        abs(f1[12] - f2[12]),
        (f1[16] + f2[16]) / 2.0,
    ], dtype=np.float32)

    out = np.concatenate([f1, f2, cross]).astype(np.float32)
    if len(out) != len(MOTION_FEATURE_NAMES):
        raise RuntimeError("Motion feature count mismatch")
    return out
