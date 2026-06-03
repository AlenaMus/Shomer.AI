"""Audit logging: one JSON line per request, plus a human-friendly console line.

Records are written to ``server/logs/audit-YYYY-MM-DD.jsonl`` — daily rotation
by filename, append-only, never edited in place. The format is JSONL so the
file can be tailed live (`Get-Content -Wait`) and also batch-loaded into
pandas / jq for the architecture study in Phase 4.

What gets logged is controlled by :class:`app.middleware.AuditLoggingMiddleware`;
this module is just the sink.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Mapping

# server/logs/  (resolved relative to this file so it works regardless of CWD).
DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR = Path(os.environ.get("AUDIT_LOG_DIR", str(DEFAULT_LOG_DIR)))
LOG_DIR.mkdir(parents=True, exist_ok=True)

_console_logger = logging.getLogger("shomer.audit")
if not _console_logger.handlers:
    # Inherit uvicorn's handler config; just give us a level + format if standalone.
    _console_logger.setLevel(logging.INFO)

# Writes happen from middleware which runs in the asyncio loop; in practice
# only one writer at a time. The lock is cheap insurance for the rare case of
# overlapping requests on a multi-worker uvicorn config.
_write_lock = Lock()


def _path_for(ts: datetime) -> Path:
    return LOG_DIR / f"audit-{ts.strftime('%Y-%m-%d')}.jsonl"


def write_audit(record: Mapping[str, Any]) -> None:
    """Persist one audit record and emit a one-line console summary.

    The record should already contain ``ts`` (ISO8601 UTC); if it doesn't, we
    fall back to "now" only for the file-rotation decision so the on-disk
    timestamp stays whatever the caller chose.
    """
    ts_str = record.get("ts")
    if isinstance(ts_str, str):
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            ts = datetime.now(timezone.utc)
    else:
        ts = datetime.now(timezone.utc)

    line = json.dumps(record, ensure_ascii=False, default=str)
    path = _path_for(ts)
    with _write_lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    # Compact console summary — useful when watching uvicorn output live.
    rid = str(record.get("request_id", "?"))[:8]
    method = record.get("method", "?")
    pth = record.get("path", "?")
    status = record.get("response", {}).get("status", "?") if isinstance(record.get("response"), Mapping) else "?"
    latency = record.get("latency_ms", 0)
    _console_logger.info("audit %s %s %s -> %s (%dms)", rid, method, pth, status, latency)


def log_path_today() -> Path:
    """Return the path of today's audit file (useful for tests / smoke checks)."""
    return _path_for(datetime.now(timezone.utc))
