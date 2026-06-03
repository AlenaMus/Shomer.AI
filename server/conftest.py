"""Root conftest for the server test suite.

Adds ``server/`` to ``sys.path`` so tests can do ``from app.ocr import ...``
without installing the package.
"""

from __future__ import annotations

import sys
import os

# Ensure the server/ directory is on sys.path so ``app`` is importable.
_SERVER_DIR = os.path.dirname(__file__)
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)
