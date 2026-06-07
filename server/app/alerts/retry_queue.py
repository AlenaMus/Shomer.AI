"""Local in-process retry queue for the Alerts module.

Reference: docs/design/alerts/design.md §3 (Retry Queue).

``LocalRetryQueue`` is a bounded deque of ``AlertRequest`` objects.  When a
notification channel fails all its retry attempts, the failed request is
enqueued here.  The ``/classify`` handler (or a future background sweep)
drains the queue and re-attempts delivery.

Capacity contract:
- ``maxlen`` enforces a hard cap.  When the deque is full, the oldest item
  is silently dropped (standard ``deque(maxlen=N)`` behavior in CPython).
- ``size()`` is used by ``health_status()`` to populate ``queued_alerts``.
- ``drain()`` atomically removes and returns all queued items.
"""

from __future__ import annotations

from collections import deque
from threading import Lock

from ..schemas import AlertRequest


class LocalRetryQueue:
    """Bounded in-process queue of undelivered ``AlertRequest`` objects.

    Thread-safe via an internal ``threading.Lock``.  The queue is LIFO only
    in the sense that ``drain()`` returns items in FIFO insertion order
    (oldest first) so the caller retries the longest-waiting alert first.

    Parameters
    ----------
    max_size:
        Maximum number of queued items.  Oldest item is silently evicted
        when the deque is full (``deque(maxlen=max_size)`` semantics).
    """

    def __init__(self, max_size: int = 100) -> None:
        self._q: deque[AlertRequest] = deque(maxlen=max_size)
        self._lock = Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, request: AlertRequest) -> None:
        """Add a failed ``AlertRequest`` to the tail of the queue.

        If the queue is already at capacity the oldest (head) item is
        silently dropped by the deque's ``maxlen`` mechanism.
        """
        with self._lock:
            self._q.append(request)

    def drain(self) -> list[AlertRequest]:
        """Remove and return all queued items in insertion order.

        Returns an empty list if nothing is queued.  The queue is empty
        after this call (until new items are enqueued).
        """
        with self._lock:
            items = list(self._q)
            self._q.clear()
            return items

    def size(self) -> int:
        """Return the number of items currently in the queue."""
        with self._lock:
            return len(self._q)
