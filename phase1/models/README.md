# phase1/models

| File | Contents |
| --- | --- |
| `presence_model.joblib` | **Selected Phase 1 model**: random forest (300 trees, max depth 5, balanced classes) on the 31 features |
| `model_selection.json` | Validation comparison of logistic regression and random forest, and the selection decision |
| `threshold_baseline.json` | Single-feature threshold baseline (average absolute baseline deviation ≥ 0.022511673) and its validation metrics |
| `current_empty_baseline.npz` | An empty-room baseline saved from a live start-up calibration |

`presence_model.joblib` is a dictionary with the keys `model`, `model_name`, `feature_names` and `decision_threshold` (0.5):

```python
import joblib
bundle = joblib.load("phase1/models/presence_model.joblib")
model, features = bundle["model"], bundle["feature_names"]
```

The model was trained with **scikit-learn 1.9.0**; load it with the same version (see `requirements.txt`). Phase 2 reuses it as the first stage of the cascade.
