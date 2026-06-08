"""Public port for the Identity module.

Reference: linked-yawning-sifakis.md §S2 "Identity & Auth".

Handles:
  - Parent registration (opaque parent_id + parent token)
  - Child record minting (opaque server-minted child_id, no PII)
  - Pairing OTP: parent issues a short-lived code; child device redeems it for
    a long-lived device token
  - Device token → DeviceContext lookup (Gatekeeper auth check)
  - Parent token → DeviceContext lookup (parent-authenticated endpoints)

Concrete adapters: ``SqliteIdentityStore`` (default), ``InMemoryIdentityStore``
(tests).

Design constraints:
  - ``child_id`` and ``device_token`` are opaque UUIDs — no PII embedded.
  - Tokens are generated via ``secrets.token_urlsafe(32)`` (256-bit entropy).
  - OTP codes are 6-digit strings generated via ``secrets.randbelow``.
  - Raw tokens are NEVER logged; only a truncated prefix is permissible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..schemas import HealthState


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChildRecord:
    """A registered child — server-minted opaque IDs, display name only."""

    child_id: str       # opaque uuid4 (no PII)
    parent_id: str
    display_name: str   # display only — no other PII
    created_at: float   # epoch seconds


@dataclass(frozen=True)
class PairingCode:
    """Short-lived OTP a parent issues so a child device can claim its token."""

    code: str           # 6-digit string
    parent_id: str
    child_id: str       # the child this code will bind the device to
    expires_at: float   # epoch seconds; TTL configurable (default 10 min)
    redeemed: bool = False


@dataclass(frozen=True)
class DeviceContext:
    """The resolved identity attached to a request after token validation."""

    device_token: str   # the raw token (set only on authenticate_*, not stored in plain)
    child_id: str
    parent_id: str
    role: str           # "child" | "parent"


# ---------------------------------------------------------------------------
# The Port
# ---------------------------------------------------------------------------


@runtime_checkable
class IdentityStore(Protocol):
    """Persistent identity store: parents, children, pairing codes, device tokens.

    MVP parent auth is an opaque token (no email/password/JWT). This is
    sufficient for S4 and keeps the scope small; production-grade parent login
    (email/password, JWTs, MFA) is explicitly out of MVP scope.
    """

    # --- Parent ------------------------------------------------------------------

    async def register_parent(self, display_name: str = "") -> tuple[str, str]:
        """Mint and store a parent record.

        Returns ``(parent_id, parent_token)`` — both opaque; parent_token is a
        long-lived credential for authenticating parent-role requests.
        """
        ...

    async def authenticate_parent(self, token: str) -> DeviceContext | None:
        """Validate a parent token; return DeviceContext(role="parent") or None."""
        ...

    # --- Child -------------------------------------------------------------------

    async def issue_child(self, parent_id: str, display_name: str) -> ChildRecord:
        """Mint a new child record linked to ``parent_id``.

        Returns a ``ChildRecord`` with a server-minted opaque ``child_id``.
        The ``display_name`` is the only human-readable field stored.
        """
        ...

    async def list_children(self, parent_id: str) -> list[ChildRecord]:
        """Return all children registered under ``parent_id``."""
        ...

    # --- Pairing -----------------------------------------------------------------

    async def create_pairing_code(self, parent_id: str, child_id: str) -> PairingCode:
        """Issue a short-lived OTP that a child device redeems for a device token.

        Prior unredeemed codes for the same (parent_id, child_id) pair are
        invalidated (each redemption should use a fresh code).
        """
        ...

    async def redeem_pairing_code(
        self,
        code: str,
        device_fingerprint: str,
    ) -> DeviceContext | None:
        """Validate ``code`` and mint a long-lived device token.

        Validity checks: code exists, not expired, not redeemed.
        On success: marks the code redeemed, mints a device token bound to
        (child_id, parent_id, role="child"), and returns DeviceContext.
        Returns ``None`` on any failure (invalid, expired, already redeemed).
        """
        ...

    # --- Device token ------------------------------------------------------------

    async def authenticate_device(self, token: str) -> DeviceContext | None:
        """Validate a device token; return DeviceContext or None.

        Used by the Gatekeeper auth middleware on every request that carries a
        Bearer token.  Must be fast (in-memory map for InMemory adapter; one
        indexed SELECT for SQLite adapter).
        """
        ...

    # --- Cross-module helpers ----------------------------------------------------

    async def parent_for_child(self, child_id: str) -> str | None:
        """Return the parent_id for a given child_id, or None if not found.

        Used by DigestScheduler (S3) to resolve the FCM target.
        """
        ...

    # --- FCM token (S3) ----------------------------------------------------------

    async def set_fcm_token(self, device_token: str, fcm_token: str) -> bool:
        """Store or update the FCM push token for a device.

        Both child and parent role devices may register FCM tokens; for
        digest delivery we need the PARENT device's token.
        Returns True if the device token was found and updated; False if not
        found (unknown device token).
        """
        ...

    async def fcm_token_for_parent(self, parent_id: str) -> str | None:
        """Return the most-recently-registered FCM token for a parent-role device.

        Scans device_tokens for rows with role="parent" and the given parent_id,
        returns the fcm_token of the most recently created entry.
        Returns None if no parent device has registered an FCM token.
        """
        ...

    # --- Health ------------------------------------------------------------------

    async def health(self) -> tuple[HealthState, str]:
        """Return (HealthState, detail_string) — used by /health rollup."""
        ...
