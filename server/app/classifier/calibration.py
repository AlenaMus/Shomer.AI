"""Post-hoc confidence calibration for the Frontline Classifier.

Reference: docs/design/classifier/design.md §3.4, §7.3.

The borderline zone (typically [0.3, 0.7]) is only statistically meaningful
when the model's confidence is a well-calibrated probability. Three modes:

- ``none``:        identity — pass raw_confidence through unchanged.
- ``temperature``: temperature scaling on the predicted-class probability.
- ``isotonic``:    sklearn ``IsotonicRegression`` fit on (raw_conf, y_true).

The fitted artefact is loaded from a pickle file. When the file is missing
or unreadable the calibrator falls back to identity and logs a WARNING — the
classifier MUST still serve traffic; calibration is a *quality* feature,
not a *correctness* one.
"""

from __future__ import annotations

import math
import pickle
from pathlib import Path
from typing import Any, Literal

from .logging import log

CalibrationMethod = Literal["none", "temperature", "isotonic"]


class ConfidenceCalibrator:
    """Stateless transformer mapping raw confidence -> calibrated confidence.

    Construct once at startup; call ``transform()`` on every classification.
    Thread-safe (the underlying sklearn model is read-only after construction).
    """

    def __init__(
        self,
        method: CalibrationMethod = "none",
        pkl_path: Path | str | None = None,
    ) -> None:
        self.method: CalibrationMethod = method
        self.pkl_path: Path | None = Path(pkl_path) if pkl_path else None
        self._model: Any | None = None  # IsotonicRegression instance or float T

        if self.method == "none":
            log.debug("calibrator_disabled", method="none")
            return

        if self.pkl_path is None or not self.pkl_path.exists():
            log.warning(
                "calibrator_pkl_missing",
                method=self.method,
                pkl_path=str(self.pkl_path) if self.pkl_path else None,
                fallback="identity",
            )
            # Downgrade: behave as identity until the operator fits + drops a pkl.
            self.method = "none"
            return

        try:
            with open(self.pkl_path, "rb") as f:
                self._model = pickle.load(f)
            log.info(
                "calibrator_loaded",
                method=self.method,
                pkl_path=str(self.pkl_path),
            )
        except (pickle.UnpicklingError, EOFError, OSError) as exc:
            log.warning(
                "calibrator_pkl_unreadable",
                method=self.method,
                pkl_path=str(self.pkl_path),
                error=type(exc).__name__,
                fallback="identity",
            )
            self._model = None
            self.method = "none"

    @property
    def is_active(self) -> bool:
        """True when the calibrator will actually transform inputs."""
        return self.method != "none" and self._model is not None

    def transform(self, raw_conf: float) -> float:
        """Apply the chosen calibration to ``raw_conf`` and clip to [0, 1].

        ``raw_conf`` is the predicted-class softmax probability. The output
        is always in [0, 1] regardless of the calibrator's internal output —
        an isotonic regressor can over/under-shoot slightly at the edges and
        we want a clean probability for downstream borderline checks.
        """
        if not self.is_active:
            return _clip(raw_conf)

        if self.method == "temperature":
            return _clip(_temperature_scale(raw_conf, float(self._model)))

        if self.method == "isotonic":
            # sklearn's IsotonicRegression exposes predict([x]) -> ndarray.
            try:
                y = self._model.predict([raw_conf])
                return _clip(float(y[0]))
            except Exception as exc:  # noqa: BLE001 - bubble nothing up
                log.warning(
                    "calibrator_transform_failed",
                    method="isotonic",
                    error=type(exc).__name__,
                    fallback="identity",
                )
                return _clip(raw_conf)

        return _clip(raw_conf)


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def _temperature_scale(p: float, T: float) -> float:
    """Apply temperature scaling to a single predicted-class probability.

    For a binary view of "is this the predicted class?" we treat ``p`` and
    ``1-p`` as the two-class softmax. We invert to logit, divide by T,
    and re-apply the sigmoid. Equivalent to the standard logits/T trick
    on the predicted class, derived from the K-class softmax.
    """
    if T <= 0:
        return p
    # Guard against p exactly 0 or 1 — would produce -inf / +inf logits.
    eps = 1e-7
    p_clamped = min(max(p, eps), 1.0 - eps)
    logit = math.log(p_clamped / (1.0 - p_clamped))
    scaled = logit / T
    # Numerically-stable sigmoid that won't overflow on extreme |scaled|.
    if scaled >= 0:
        z = math.exp(-scaled)
        return 1.0 / (1.0 + z)
    z = math.exp(scaled)
    return z / (1.0 + z)
