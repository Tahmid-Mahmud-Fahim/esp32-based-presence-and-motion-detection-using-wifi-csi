# phase2/reports

| File | Contents |
| --- | --- |
| `new_data_qc.csv` | Quality check of the 9 new walking sessions: rows, packet rate per receiver, missing sequence numbers |
| `test_results_phase2.json` | One-time held-out test (subject S03) of the cascade and the direct model: confusion matrices, accuracy, macro-F1, per-session results |

**Cascade:** 1,127 of 1,210 test windows correct (93.14%). Recall is 99.17% EMPTY, 86.57% STATIC and 96.69% MOVING. Most errors come from the `S03_stand_center` session.
