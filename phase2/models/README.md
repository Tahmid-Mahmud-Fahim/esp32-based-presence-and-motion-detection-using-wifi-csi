# phase2/models

| File | Contents |
| --- | --- |
| `motion_model.joblib` | **Deployed motion model**: random forest (400 trees, max depth 7) on the 44 motion features, trained on STATIC and MOVING windows only. Validation macro-F1 0.9628 (logistic regression: 0.9451) |
| `direct3_model.joblib` | Direct three-class alternative: standardised logistic regression on all 75 features. Validation macro-F1 0.9856 (random forest: 0.9817) |
| `phase2_model_selection.json` | Validation metrics of all candidates and of the full cascade, with the selection decisions |

The cascade uses `phase1/models/presence_model.joblib` first (EMPTY / PERSON) and then `motion_model.joblib` (STATIC / MOVING). Both model files are dictionaries with `model` and `feature_names` (plus `class_map` and `decision_threshold` for the motion model). They were trained with **scikit-learn 1.9.0**.
