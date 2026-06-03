"""Unit tests for ConfidenceCalibrator."""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest

from app.classifier import ConfidenceCalibrator


# ---------------------------------------------------------------------------
# Identity / "none" mode
# ---------------------------------------------------------------------------


def test_none_method_is_identity() -> None:
    cal = ConfidenceCalibrator(method="none")
    for x in (0.0, 0.123, 0.5, 0.88, 1.0):
        assert cal.transform(x) == x
    assert cal.is_active is False


def test_none_with_pkl_path_still_identity(tmp_path: Path) -> None:
    """Even if a pkl file exists, ``method='none'`` ignores it."""
    pkl = tmp_path / "calib.pkl"
    pkl.write_bytes(pickle.dumps(2.0))
    cal = ConfidenceCalibrator(method="none", pkl_path=pkl)
    assert cal.transform(0.7) == 0.7


# ---------------------------------------------------------------------------
# Missing-file fallback
# ---------------------------------------------------------------------------


def test_missing_pkl_falls_back_to_identity_for_isotonic(tmp_path: Path) -> None:
    cal = ConfidenceCalibrator(
        method="isotonic", pkl_path=tmp_path / "does-not-exist.pkl"
    )
    assert cal.is_active is False  # downgraded to identity
    assert cal.transform(0.42) == 0.42


def test_missing_pkl_falls_back_to_identity_for_temperature(tmp_path: Path) -> None:
    cal = ConfidenceCalibrator(
        method="temperature", pkl_path=tmp_path / "does-not-exist.pkl"
    )
    assert cal.is_active is False
    assert cal.transform(0.42) == 0.42


def test_unreadable_pkl_falls_back_to_identity(tmp_path: Path) -> None:
    pkl = tmp_path / "bad.pkl"
    pkl.write_bytes(b"not a pickle at all")
    cal = ConfidenceCalibrator(method="temperature", pkl_path=pkl)
    assert cal.is_active is False
    assert cal.transform(0.3) == 0.3


# ---------------------------------------------------------------------------
# Temperature scaling
# ---------------------------------------------------------------------------


def test_temperature_T_equals_one_is_identity(tmp_path: Path) -> None:
    pkl = tmp_path / "T.pkl"
    pkl.write_bytes(pickle.dumps(1.0))
    cal = ConfidenceCalibrator(method="temperature", pkl_path=pkl)
    assert cal.is_active is True
    # T=1 ⇒ logits/T = logits ⇒ sigmoid(logit(p)) = p (up to floating noise).
    for x in (0.2, 0.5, 0.8):
        assert abs(cal.transform(x) - x) < 1e-6


def test_temperature_T_above_one_softens(tmp_path: Path) -> None:
    pkl = tmp_path / "T.pkl"
    pkl.write_bytes(pickle.dumps(2.0))
    cal = ConfidenceCalibrator(method="temperature", pkl_path=pkl)
    # T>1 should pull confidence toward 0.5
    assert cal.transform(0.9) < 0.9
    assert cal.transform(0.1) > 0.1


def test_temperature_clips_to_unit_interval(tmp_path: Path) -> None:
    pkl = tmp_path / "T.pkl"
    pkl.write_bytes(pickle.dumps(0.01))  # very sharp
    cal = ConfidenceCalibrator(method="temperature", pkl_path=pkl)
    # Even a sharp T should not exit [0, 1]
    for x in (0.0001, 0.5, 0.9999):
        y = cal.transform(x)
        assert 0.0 <= y <= 1.0


# ---------------------------------------------------------------------------
# Isotonic regression
# ---------------------------------------------------------------------------


def test_isotonic_loads_and_predicts(tmp_path: Path) -> None:
    """Fit a tiny IsotonicRegression and assert ``transform`` proxies to it."""
    sk_iso = pytest.importorskip("sklearn.isotonic")
    iso = sk_iso.IsotonicRegression(out_of_bounds="clip")
    iso.fit([0.0, 0.5, 1.0], [0.0, 0.4, 1.0])
    pkl = tmp_path / "iso.pkl"
    pkl.write_bytes(pickle.dumps(iso))

    cal = ConfidenceCalibrator(method="isotonic", pkl_path=pkl)
    assert cal.is_active is True
    assert abs(cal.transform(0.5) - 0.4) < 1e-6
    # Edges (clipped)
    assert 0.0 <= cal.transform(0.0) <= 1.0
    assert 0.0 <= cal.transform(1.0) <= 1.0


def test_isotonic_transform_failure_falls_back_to_identity(tmp_path: Path) -> None:
    """If the pickled object isn't an IsotonicRegression, identity wins."""
    pkl = tmp_path / "bogus.pkl"
    pkl.write_bytes(pickle.dumps({"not": "a model"}))
    cal = ConfidenceCalibrator(method="isotonic", pkl_path=pkl)
    # The loader treated this as an opaque "model" — transform tries predict()
    # and our guard catches AttributeError and returns raw_conf.
    assert cal.transform(0.6) == 0.6


# ---------------------------------------------------------------------------
# Output range guarantees
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["none", "temperature", "isotonic"])
def test_output_always_in_unit_interval(method: str, tmp_path: Path) -> None:
    pkl = None
    if method == "temperature":
        pkl = tmp_path / "T.pkl"
        pkl.write_bytes(pickle.dumps(2.0))
    elif method == "isotonic":
        sk_iso = pytest.importorskip("sklearn.isotonic")
        iso = sk_iso.IsotonicRegression(out_of_bounds="clip")
        iso.fit([0.0, 1.0], [0.0, 1.0])
        pkl = tmp_path / "iso.pkl"
        pkl.write_bytes(pickle.dumps(iso))

    cal = ConfidenceCalibrator(method=method, pkl_path=pkl)
    for x in (0.0, 0.05, 0.5, 0.95, 1.0):
        y = cal.transform(x)
        assert 0.0 <= y <= 1.0
