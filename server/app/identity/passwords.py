"""Password hashing and verification utilities for the identity module.

Uses stdlib only: ``hashlib.pbkdf2_hmac`` with SHA-256, 600 000 iterations,
and a per-user random 16-byte salt.

Stored format:  ``pbkdf2$<iterations>$<salt_hex>$<hash_hex>``

Verify with ``hmac.compare_digest`` to guard against timing attacks.
"""

from __future__ import annotations

import hashlib
import hmac
import os

_ALGORITHM = "sha256"
_ITERATIONS = 600_000
_SALT_BYTES = 16
_PREFIX = "pbkdf2"


def hash_password(password: str) -> str:
    """Hash ``password`` and return the portable encoded string.

    The returned value is safe to store in a database column.
    """
    salt = os.urandom(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(_ALGORITHM, password.encode(), salt, _ITERATIONS)
    return f"{_PREFIX}${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Return True if ``password`` matches ``stored_hash``.

    Uses ``hmac.compare_digest`` for constant-time comparison.
    Returns False for any malformed stored_hash.
    """
    try:
        parts = stored_hash.split("$")
        if len(parts) != 4 or parts[0] != _PREFIX:
            return False
        _prefix, iterations_str, salt_hex, expected_hex = parts
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(expected_hex)
    except (ValueError, TypeError):
        return False

    dk = hashlib.pbkdf2_hmac(_ALGORITHM, password.encode(), salt, iterations)
    return hmac.compare_digest(dk, expected)
