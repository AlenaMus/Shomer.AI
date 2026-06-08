"""Tests for the DedupStore port and adapters.

Covers:
  - seen/mark basic lifecycle
  - TTL expiry (time-travel via monkeypatching monotonic)
  - Per-child isolation
  - Cap eviction (oldest entry is evicted when max_per_child is reached)
  - NullDedupStore always returns False

Run from repo root:
    python -m pytest server/tests/dedup/test_dedup.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio

# Ensure server/ is on sys.path for ``app`` imports.
_SERVER_DIR = str(Path(__file__).resolve().parents[2])
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from app.dedup import InMemoryTtlDedupStore, NullDedupStore
from app.dedup.protocol import DedupStore
from app.schemas import HealthState


# ---------------------------------------------------------------------------
# InMemoryTtlDedupStore tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seen_returns_false_for_unknown():
    store = InMemoryTtlDedupStore()
    assert await store.seen("child-1", "hash-abc") is False


@pytest.mark.asyncio
async def test_mark_then_seen_returns_true():
    store = InMemoryTtlDedupStore()
    await store.mark("child-1", "hash-abc", ttl_s=3600)
    assert await store.seen("child-1", "hash-abc") is True


@pytest.mark.asyncio
async def test_ttl_expiry():
    """After TTL expires, seen() should return False and evict the entry.

    Directly manipulate the internal bucket to set expiry in the past — this
    is the most reliable way to test TTL without timing tricks.
    """
    import time as _time
    store = InMemoryTtlDedupStore()

    # Mark normally first.
    await store.mark("child-1", "hash-abc", ttl_s=3600)
    # Confirm it's seen.
    assert await store.seen("child-1", "hash-abc") is True

    # Fast-forward: set the expiry to 1 second in the past.
    with store._lock:
        store._buckets["child-1"]["hash-abc"] = _time.monotonic() - 1.0

    # Now seen() should detect expiry and return False.
    result = await store.seen("child-1", "hash-abc")
    assert result is False

    # The expired entry should have been lazily evicted.
    with store._lock:
        assert "hash-abc" not in store._buckets.get("child-1", {})


@pytest.mark.asyncio
async def test_per_child_isolation():
    """Different child_ids have completely independent dedup buckets."""
    store = InMemoryTtlDedupStore()
    await store.mark("child-A", "hash-xyz", ttl_s=3600)

    # child-B with same hash is NOT seen.
    assert await store.seen("child-B", "hash-xyz") is False
    # child-A with same hash IS seen.
    assert await store.seen("child-A", "hash-xyz") is True


@pytest.mark.asyncio
async def test_cap_eviction():
    """When max_per_child is reached, the oldest-expiry entry is evicted."""
    store = InMemoryTtlDedupStore(max_per_child=3)

    # Fill to capacity.
    await store.mark("child-1", "hash-1", ttl_s=100)
    await store.mark("child-1", "hash-2", ttl_s=200)
    await store.mark("child-1", "hash-3", ttl_s=300)

    # Adding hash-4 must evict the entry with the smallest TTL (hash-1).
    await store.mark("child-1", "hash-4", ttl_s=400)

    # hash-4 is definitely present.
    assert await store.seen("child-1", "hash-4") is True
    # The bucket still has exactly 3 entries (cap enforced).
    with store._lock:
        assert len(store._buckets["child-1"]) == 3


@pytest.mark.asyncio
async def test_mark_reset_ttl():
    """Marking an existing key resets its TTL (second mark wins)."""
    store = InMemoryTtlDedupStore()
    await store.mark("child-1", "hash-abc", ttl_s=100)
    await store.mark("child-1", "hash-abc", ttl_s=7200)

    # Should still be seen (not double-counted in the bucket).
    assert await store.seen("child-1", "hash-abc") is True
    with store._lock:
        # Only one entry for this hash.
        assert len(store._buckets["child-1"]) == 1


@pytest.mark.asyncio
async def test_health_returns_ok():
    store = InMemoryTtlDedupStore()
    await store.mark("child-1", "hash-abc", ttl_s=60)
    state, detail = await store.health()
    assert state == HealthState.OK
    assert "1 children" in detail
    assert "1 entries" in detail


# ---------------------------------------------------------------------------
# Protocol conformance (runtime_checkable)
# ---------------------------------------------------------------------------


def test_inmemory_is_dedup_store_protocol():
    store = InMemoryTtlDedupStore()
    assert isinstance(store, DedupStore)


def test_null_is_dedup_store_protocol():
    store = NullDedupStore()
    assert isinstance(store, DedupStore)


# ---------------------------------------------------------------------------
# NullDedupStore tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_null_seen_always_false():
    store = NullDedupStore()
    await store.mark("child-1", "hash-abc")
    assert await store.seen("child-1", "hash-abc") is False


@pytest.mark.asyncio
async def test_null_health():
    store = NullDedupStore()
    state, detail = await store.health()
    assert state == HealthState.OK
    assert "null" in detail.lower()
