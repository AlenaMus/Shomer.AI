"""Base class / Protocol for all context_agent tools."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ToolBase(Protocol):
    """Every tool implements this interface."""

    name: str
    description: str
    parameters_schema: dict  # JSON Schema for the args dict

    async def run(self, args: dict[str, Any]) -> dict[str, Any]:
        """Execute the tool and return a JSON-serialisable result dict."""
        ...
