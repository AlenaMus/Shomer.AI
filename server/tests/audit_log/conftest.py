"""Shared fixtures for audit_log adapter tests.

The SqliteAuditStore fixture uses a **real temp file** (not ``:memory:``) because
WAL mode requires a file-backed database. The store is initialized before each
test and closed after.
"""

from __future__ import annotations

import os
import sys
from typing import AsyncIterator

import pytest
import pytest_asyncio

# Make ``app`` importable (mirrors server/conftest.py; harmless if already set).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.audit_log.sqlite_adapter import SqliteAuditStore  # noqa: E402


@pytest.fixture
def db_path(tmp_path) -> str:
    """A real temp-file DB path (WAL needs a file, not :memory:)."""
    return str(tmp_path / "audit_test.db")


@pytest_asyncio.fixture
async def sqlite_store(db_path) -> AsyncIterator[SqliteAuditStore]:
    """An initialized SqliteAuditStore; closed on teardown."""
    store = SqliteAuditStore(db_path=db_path)
    await store.initialize()
    try:
        yield store
    finally:
        await store.close()
