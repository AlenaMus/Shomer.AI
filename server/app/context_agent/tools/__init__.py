"""Context Agent tool sub-package.

Each tool has:
  - ``name``              — unique identifier
  - ``description``       — shown in logs / prompt
  - ``async run(args)``   — executes the tool and returns a dict
"""

from .base import ToolBase
from .read_history import ReadHistoryTool
from .lookup_slang import LookupSlangTool
from .check_age import CheckAgeAppropriatenessTool

__all__ = [
    "ToolBase",
    "ReadHistoryTool",
    "LookupSlangTool",
    "CheckAgeAppropriatenessTool",
]
