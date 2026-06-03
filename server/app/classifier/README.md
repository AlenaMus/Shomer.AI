# Frontline Classifier — quick reference

This module ships the `TextClassifier` Port and three concrete adapters. It
is the fast, local first-pass for every classification request. See the full
LLD at `docs/design/classifier/design.md` for the long version.

## Which adapter when?

| Adapter | `model_version` | Use when | Requires |
|---|---|---|---|
| `OllamaDictaBertClassifier` | `v1.0-standin` | **Default today.** Stand-in path — Qwen via Ollama running locally. Keeps the end-to-end pipeline alive while DictaBERT is being trained. | Ollama running at `OLLAMA_URL`, model `OLLAMA_MODEL` (default `offensive-hebrew:v1`) installed. |
| `HuggingFaceClassifier` | `v1.1-dictabert` (or `v1.1-dictabert-base-untrained` if no fine-tune yet) | After Meeting-5 fine-tune. Faster than Ollama (~2×), exact control over softmax + temperature. | `transformers`, `torch`, `safetensors`. First call downloads ~440 MB from HuggingFace if `DICTABERT_MODEL_PATH` is absent. |
| `StubClassifier` | `stub` | Unit + contract tests; degraded-mode fallback if both real adapters fail to construct at startup. | Nothing. |

## How to switch

Two env vars in `server/.env` drive the choice:

```bash
CLASSIFIER_MODEL_VERSION=v1.0-standin     # or v1.1-dictabert
DICTABERT_MODEL_PATH=server/models/dictabert-offensive
```

The actual swap happens in **one line** in `server/app/main.py` `lifespan()`:

```python
# v1.0-standin
classifier: TextClassifier = OllamaDictaBertClassifier(
    ollama=app.state.ollama, settings=settings.classifier
)

# v1.1-dictabert
classifier: TextClassifier = HuggingFaceClassifier(settings.classifier)
```

Every other module (triage, route handler, pipeline, tests) types its
dependency as `TextClassifier`, never the concrete class, so nothing else
changes.

## Borderline zone

The classifier emits **calibrated** confidence in `[0, 1]`. Anything in
`[BORDERLINE_LOW, BORDERLINE_HIGH]` (default `[0.3, 0.7]`) sets
`is_borderline=True`, which the triage router uses to escalate to the
Context Agent. The zone is the *cost-control* knob: widen it to escalate
more (better recall, more LLM spend); narrow it to escalate less.

## Calibration

`ConfidenceCalibrator` runs after the model's softmax and before the
borderline check. Three modes:

| `CALIBRATION_METHOD` | What it does | When to use |
|---|---|---|
| `none` | Identity. Pass `raw_confidence` through. | Always for the stand-in (Qwen has no calibration set fit). |
| `temperature` | Single-parameter scalar `T` on the predicted-class logit. | Fast post-hoc; small expected-calibration-error reduction. |
| `isotonic` | sklearn `IsotonicRegression` fit on a held-out validation set. | After Meeting 5. ECE typically drops to < 0.05. |

The pickle file is loaded from `CALIBRATION_PKL_PATH`. If it's missing the
calibrator silently falls back to identity and logs a WARNING — the
classifier MUST still serve traffic.

## Known limitations

- **Untrained HF head.** When `DICTABERT_MODEL_PATH` is missing,
  `HuggingFaceClassifier` loads the HF base model with a freshly
  initialised 5-label classification head. Predictions are essentially
  random and confidence sits near `1/5 = 0.2`. The audit log captures this
  state via `model_version="v1.1-dictabert-base-untrained"`. Fix lands
  with the Meeting-5 fine-tune.
- **CPU only.** The server box has no inference GPU. DictaBERT-base
  (~110M params) hits the PRD §8.1 p99 < 100 ms target on a modern CPU
  with `max_length=512`. If a future variant overshoots, push to a
  worker process or batch.
- **Stand-in confidence is uncalibrated.** Qwen-via-Ollama emits a
  self-reported confidence from the JSON prompt — it is NOT a softmax. Do
  not enable `temperature` or `isotonic` calibration in `v1.0-standin`
  mode unless you have first fit the calibrator on the stand-in's outputs.

## SinaLab 5-label schema

`abusive` · `hate` · `violence` · `pornographic` · `non_offensive`

`is_offensive` is derived as `label != "non_offensive"`. See LLD §5.2 for
the multi-label collapse rules (priority: `violence > hate > pornographic
> abusive`).
