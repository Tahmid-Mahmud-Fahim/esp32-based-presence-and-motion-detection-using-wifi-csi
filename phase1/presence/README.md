# phase1/presence

Python package with the shared CSI processing code. The **same functions** build the offline datasets and run in the live system, so training and deployment use identical preprocessing. Phase 2 imports it too.

| Function | Purpose |
| --- | --- |
| `parse_csi_cell()` | Parse the quoted `csi_data` text into 256 integers |
| `raw_iq_to_amplitude()` | Convert (imag, real) pairs to amplitudes and keep the 107 active subcarriers (51 LLTF + 56 HT-LTF) |
| `load_receiver_csv()` | Load one receiver CSV, keep only packets with the expected layout (HT20, 256-byte CSI) and sort by laptop time |
| `robust_subcarrier_normalize()` | Alternative per-subcarrier robust normalisation (kept for comparison) |
| `fieldwise_ltf_normalize()` | Divide LLTF and HT-LTF of every packet by their own median amplitude |
| `temporal_smooth()` | Savitzky-Golay smoothing along time (5 samples, order 2) |
| `resample()` | Linear interpolation of one receiver onto a time grid |
| `align_dual_rx()` | Put RX1 and RX2 on one shared 25 Hz grid over their overlap; reject gaps > 0.25 s |
| `window_slices()` | 2-s windows (50 samples) with the requested hop |
| `fit_empty_baseline()` | Median empty-room profile per receiver (median over time, then across sessions) |
| `extract_window_features()` | The 31 Phase 1 features of one aligned RX1/RX2 window |
| `session_features()` | Full pipeline for one session: load, align, normalise, smooth, window, extract features |
| `save_baseline()` | Write an empty-room baseline to `.npz` |
| `load_baseline()` | Read an empty-room baseline from `.npz` |
| `read_manifest()` | Read a session manifest CSV |

**Processing chain:**
1. Load and check the packets.
2. Convert to amplitude and keep 107 subcarriers.
3. Align RX1/RX2 on a 25 Hz grid.
4. Normalise each training field by its median.
5. Smooth with Savitzky-Golay.
6. Cut 2-second windows.
7. Extract 31 features (13 per receiver + 5 cross-receiver).

`__init__.py` makes the folder importable as `presence`.
