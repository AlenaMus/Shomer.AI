"""Frontline Classifier module — DictaBERT/Ollama Hebrew text classifier.

Public surface (port-only, per docs/design/README.md):

    from server.app.classifier import TextClassifier

Concrete adapters live in private submodules and are constructed only in
server/app/main.py lifespan() — but they are re-exported here so the
composition root can do a single import. See docs/design/classifier/design.md.

The Protocol is the only symbol downstream business code (triage, route
handlers, pipeline) should import. Tests + main.py may import the adapters.
"""

from __future__ import annotations

from .calibration import CalibrationMethod, ConfidenceCalibrator
from .huggingface_adapter import HuggingFaceClassifier
from .ollama_adapter import OllamaDictaBertClassifier
from .protocol import TextClassifier
from .settings import (
    KNOWN_CALIBRATION_METHODS,
    KNOWN_MODEL_VERSIONS,
    ClassifierSettings,
)
from .stub_adapter import StubClassifier

__all__ = [
    # Port
    "TextClassifier",
    # Adapters — imported by main.py lifespan() (composition root).
    "OllamaDictaBertClassifier",
    "HuggingFaceClassifier",
    "StubClassifier",
    # Settings + calibration
    "ClassifierSettings",
    "ConfidenceCalibrator",
    "CalibrationMethod",
    "KNOWN_MODEL_VERSIONS",
    "KNOWN_CALIBRATION_METHODS",
]
