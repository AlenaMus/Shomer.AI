"""Structured logger for the Frontline Classifier module.

Reference: docs/design/classifier/design.md §6.1.

All log lines emitted by the module are bound to the ``shomer.classifier``
logger and carry ``module="classifier"`` plus any trace_id supplied by the
caller. The three documented events are:

- ``classification_complete``    — confident, non-borderline result
- ``classification_borderline``  — borderline confidence → escalate to CA
- ``classification_error``       — model failure → review_flag fallback
"""

from __future__ import annotations

from typing import Any

import structlog

# Module-level logger. Callers in adapters do ``from .logging import log``
# and then ``log.info("classification_complete", **fields)``.
log = structlog.get_logger("shomer.classifier")


def bind_context(
    *,
    trace_id: str | None = None,
    model_version: str | None = None,
    **extra: Any,
) -> structlog.stdlib.BoundLogger:
    """Return a child logger pre-bound to a trace_id + model_version.

    Adapters use this once per ``classify()`` call so every log line emitted
    during that call (info / warning / error) automatically carries the
    request's trace_id and the running model version — matching the field
    contract spelled out in classifier LLD §6.1.

    Args:
        trace_id: Per-request correlation id. Falls through from middleware
            (currently the ``request_id`` set by AuditLoggingMiddleware).
        model_version: Adapter's ``model_version`` property, e.g.
            ``"v1.0-standin"`` or ``"v1.1-dictabert"``.
        **extra: Any other key=value pairs to bind for the duration of this
            scope (e.g. ``text_len``).

    Returns:
        A ``structlog`` bound logger with ``module="classifier"`` set.
    """
    binding: dict[str, Any] = {"module": "classifier"}
    if trace_id is not None:
        binding["trace_id"] = trace_id
    if model_version is not None:
        binding["model_version"] = model_version
    binding.update(extra)
    return log.bind(**binding)
