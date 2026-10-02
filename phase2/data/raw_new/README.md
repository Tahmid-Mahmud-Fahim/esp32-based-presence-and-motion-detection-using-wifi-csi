# phase2/data/raw_new

New walking recordings for Phase 2: **18 CSV files** = 9 sessions × 2 receivers, each about 60 s.

| Session | Instruction to the subject |
| --- | --- |
| `S0x_slow_walk` | Walk slowly and continuously through the sensing area |
| `S0x_walk_left_right` | Walk repeatedly left-to-right and back across the sensing area |
| `S0x_walk_tx_rx` | Walk repeatedly along the TX-to-RX direction and back |

The files have the same 16-column format as [`phase1/data/raw/`](../../../phase1/data/raw/). They were recorded with `phase2/01_collect_phase2.ps1`, which calls `phase1/python/01_capture_dual_rx.py`. All 9 sessions passed the quality check (`phase2/reports/new_data_qc.csv`): 41.67–49.86 packets per second and no missing sequence numbers.
