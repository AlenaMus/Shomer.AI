"""Bound structlog logger for the OCR module.

All OCR log events are emitted through this logger.  Every event carries at
minimum: ``module="ocr"``, ``event``, ``latency_ms``.

Reference: docs/design/ocr/design.md §6.1
"""

from __future__ import annotations

import structlog

# Module-level bound logger.  The name "shomer.ocr" places it under the
# project-wide "shomer.*" hierarchy so log aggregation tooling can filter it.
logger: structlog.stdlib.BoundLogger = structlog.get_logger("shomer.ocr")

__all__ = ["logger"]
