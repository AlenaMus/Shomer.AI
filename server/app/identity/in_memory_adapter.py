"""InMemoryIdentityStore — fast adapter for tests and local dev.

No I/O, no persistence. Perfect for integration tests that don't want a
real SQLite file. Fully implements the ``IdentityStore`` Protocol.
"""

from __future__ import annotations

import secrets
import time
import uuid
from dataclasses import replace

import structlog

from ..schemas import HealthState
from .protocol import ChildRecord, DeviceContext, IdentityStore, PairingCode, ParentAuth
from .passwords import hash_password, verify_password

log = structlog.get_logger("shomer.identity.memory")


class InMemoryIdentityStore:
    """All state lives in plain dicts.  Thread-safe for single-process tests."""

    def __init__(self, pairing_code_ttl_s: int = 600) -> None:
        self._pairing_code_ttl_s = pairing_code_ttl_s
        # parent_id → (parent_token, display_name)
        self._parents: dict[str, tuple[str, str]] = {}
        # parent_token → parent_id
        self._parent_tokens: dict[str, str] = {}
        # email (lowercase) → parent_id (for login)
        self._emails: dict[str, str] = {}
        # parent_id → normalised email (for ParentAuth)
        self._parent_emails: dict[str, str] = {}
        # parent_id → password_hash
        self._password_hashes: dict[str, str] = {}
        # parent_id → display_name (separate for credential lookup)
        self._parent_display_names: dict[str, str] = {}
        # child_id → ChildRecord
        self._children: dict[str, ChildRecord] = {}
        # parent_id → list[child_id]
        self._parent_children: dict[str, list[str]] = {}
        # OTP code → PairingCode
        self._codes: dict[str, PairingCode] = {}
        # device_token → DeviceContext
        self._device_tokens: dict[str, DeviceContext] = {}
        # device_token → fcm_token (S3: FCM registration)
        self._fcm_tokens: dict[str, str] = {}
        # (parent_id, device_token, created_at) list for fcm_token_for_parent query
        self._parent_device_meta: list[tuple[str, str, float]] = []  # (parent_id, device_token, created_at)

    # --- Parent ------------------------------------------------------------------

    async def register_parent(
        self,
        display_name: str = "",
        email: str | None = None,
        password: str | None = None,
    ) -> tuple[str, str]:
        normalised_email = email.strip().lower() if email else None
        if normalised_email is not None and normalised_email in self._emails:
            raise ValueError("email_taken")
        parent_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(32)
        self._parents[parent_id] = (token, display_name)
        self._parent_tokens[token] = parent_id
        self._parent_display_names[parent_id] = display_name
        if normalised_email is not None:
            self._emails[normalised_email] = parent_id
            self._parent_emails[parent_id] = normalised_email
        if password is not None:
            self._password_hashes[parent_id] = hash_password(password)
        # Track parent token in device meta so fcm_token_for_parent can find it.
        self._parent_device_meta.append((parent_id, token, time.time()))
        log.info(
            "identity.parent_registered",
            parent_id=parent_id,
            token_prefix=token[:8],
            has_email=normalised_email is not None,
        )
        return parent_id, token

    async def authenticate_parent_credentials(
        self, email: str, password: str
    ) -> "ParentAuth | None":
        normalised_email = email.strip().lower() if email else ""
        parent_id = self._emails.get(normalised_email)
        if not parent_id:
            return None
        stored_hash = self._password_hashes.get(parent_id)
        if not stored_hash or not verify_password(password, stored_hash):
            return None
        token, display_name = self._parents[parent_id]
        return ParentAuth(
            parent_id=parent_id,
            parent_token=token,
            display_name=display_name,
            email=normalised_email,
        )

    async def authenticate_parent(self, token: str) -> DeviceContext | None:
        parent_id = self._parent_tokens.get(token)
        if not parent_id:
            return None
        return DeviceContext(
            device_token=token,
            child_id="",
            parent_id=parent_id,
            role="parent",
        )

    # --- Child -------------------------------------------------------------------

    async def issue_child(self, parent_id: str, display_name: str) -> ChildRecord:
        child_id = str(uuid.uuid4())
        record = ChildRecord(
            child_id=child_id,
            parent_id=parent_id,
            display_name=display_name,
            created_at=time.time(),
        )
        self._children[child_id] = record
        self._parent_children.setdefault(parent_id, []).append(child_id)
        log.info(
            "identity.child_issued",
            child_id=child_id,
            parent_id=parent_id,
        )
        return record

    async def list_children(self, parent_id: str) -> list[ChildRecord]:
        ids = self._parent_children.get(parent_id, [])
        return [self._children[cid] for cid in ids if cid in self._children]

    # --- Pairing -----------------------------------------------------------------

    async def create_pairing_code(self, parent_id: str, child_id: str) -> PairingCode:
        # Invalidate any existing unused codes for this (parent, child) pair.
        to_remove = [
            c
            for c, pc in self._codes.items()
            if pc.parent_id == parent_id
            and pc.child_id == child_id
            and not pc.redeemed
        ]
        for c in to_remove:
            del self._codes[c]

        # Mint a fresh 6-digit OTP (zero-padded so it is always 6 chars).
        raw = secrets.randbelow(1_000_000)
        code_str = f"{raw:06d}"
        pc = PairingCode(
            code=code_str,
            parent_id=parent_id,
            child_id=child_id,
            expires_at=time.time() + self._pairing_code_ttl_s,
        )
        self._codes[code_str] = pc
        log.info(
            "identity.pairing_code_created",
            child_id=child_id,
            parent_id=parent_id,
            expires_at=pc.expires_at,
        )
        return pc

    async def redeem_pairing_code(
        self,
        code: str,
        device_fingerprint: str,
    ) -> DeviceContext | None:
        pc = self._codes.get(code)
        if pc is None:
            log.warning("identity.redeem_failed", reason="not_found", code=code[:4])
            return None
        if pc.redeemed:
            log.warning("identity.redeem_failed", reason="already_redeemed", code=code[:4])
            return None
        if time.time() > pc.expires_at:
            log.warning("identity.redeem_failed", reason="expired", code=code[:4])
            return None

        # Mark redeemed.
        self._codes[code] = replace(pc, redeemed=True)

        # Mint a long-lived device token.
        token = secrets.token_urlsafe(32)
        ctx = DeviceContext(
            device_token=token,
            child_id=pc.child_id,
            parent_id=pc.parent_id,
            role="child",
        )
        self._device_tokens[token] = ctx
        self._parent_device_meta.append((pc.parent_id, token, time.time()))
        log.info(
            "identity.pairing_redeemed",
            child_id=pc.child_id,
            token_prefix=token[:8],
        )
        return ctx

    # --- Device token ------------------------------------------------------------

    async def authenticate_device(self, token: str) -> DeviceContext | None:
        return self._device_tokens.get(token)

    # --- Cross-module helpers ----------------------------------------------------

    async def parent_for_child(self, child_id: str) -> str | None:
        record = self._children.get(child_id)
        return record.parent_id if record else None

    async def get_parent_email(self, parent_id: str) -> str | None:
        """Return the stored email for a parent, or None."""
        return self._parent_emails.get(parent_id)

    # --- FCM token (S3) ----------------------------------------------------------

    async def set_fcm_token(self, device_token: str, fcm_token: str) -> bool:
        """Store or update the FCM token for a device_token.

        Works for both child and parent role tokens; for digest delivery the
        parent's token is the relevant one.
        Returns True if the device_token was found; False if unknown.
        """
        # The device_token can be either a parent token (in _parent_tokens) or
        # a child device token (in _device_tokens).
        is_parent = device_token in self._parent_tokens
        is_child = device_token in self._device_tokens
        if not is_parent and not is_child:
            log.warning(
                "identity.fcm_token_set_unknown_device",
                token_prefix=device_token[:8],
            )
            return False
        self._fcm_tokens[device_token] = fcm_token
        log.info(
            "identity.fcm_token_set",
            token_prefix=device_token[:8],
        )
        return True

    async def fcm_token_for_parent(self, parent_id: str) -> str | None:
        """Return the most-recently-registered FCM token for a parent-role device.

        Looks through _parent_device_meta (ordered by insertion, which corresponds
        to created_at) for the parent's device tokens, returns the most recent
        one that has an FCM token registered.
        """
        # Sort most-recently-created first.
        candidates = sorted(
            [(created_at, dt) for (pid, dt, created_at) in self._parent_device_meta if pid == parent_id],
            key=lambda x: x[0],
            reverse=True,
        )
        for _, device_token in candidates:
            fcm = self._fcm_tokens.get(device_token)
            if fcm:
                return fcm
        return None

    # --- Health ------------------------------------------------------------------

    async def health(self) -> tuple[HealthState, str]:
        return (HealthState.OK, f"in_memory: {len(self._children)} children")
