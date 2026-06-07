"""Shared fixtures for the triage test suite.

Ensures ``server/`` is on ``sys.path`` (same pattern as the classifier suite)
so tests can do ``from app.triage import ...`` from the repo root.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure ``server/`` is importable as a package root.
_SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

from app.schemas import ClassificationResult  # noqa: E402
from app.triage import TriageSettings  # noqa: E402


# ---------------------------------------------------------------------------
# ClassificationResult factory helpers
# ---------------------------------------------------------------------------


def make_result(
    *,
    label: str = "abusive",
    confidence: float = 0.8,
    is_offensive: bool = True,
    model_version: str = "v1.0-standin",
    latency_ms: float = 10.0,
    is_borderline: bool = False,
    raw_confidence: float | None = None,
    error: bool = False,
) -> ClassificationResult:
    """Build a ``ClassificationResult`` with sensible defaults."""
    return ClassificationResult(
        label=label,
        confidence=confidence,
        is_offensive=is_offensive,
        model_version=model_version,
        latency_ms=latency_ms,
        is_borderline=is_borderline,
        raw_confidence=raw_confidence if raw_confidence is not None else confidence,
        error=error,
    )


# ---------------------------------------------------------------------------
# TriageSettings fixture — defaults wiped of any leaked env vars.
# ---------------------------------------------------------------------------


@pytest.fixture
def default_settings(monkeypatch: pytest.MonkeyPatch) -> TriageSettings:
    """TriageSettings with all triage env vars removed so defaults are clean."""
    env_vars = [
        "BORDERLINE_LOW",
        "BORDERLINE_HIGH",
        "TRIAGE_BASELINE_THRESHOLD",
        "CONTEXT_AGENT_ENABLED",
        "TRIAGE_ALWAYS_ESCALATE_LABELS",
        "TRIAGE_ALWAYS_ALERT_LABELS",
    ]
    for var in env_vars:
        monkeypatch.delenv(var, raising=False)
    return TriageSettings()
