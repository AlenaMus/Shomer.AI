"""LookupSlangTool — matches words in the input text against the slang lexicon.

Loads ``slang_lexicon.json`` once at construction. If the file is missing the
lexicon is treated as empty (graceful degradation — not a hard failure at the
tool level; callers that need fail-fast should check at startup).

Reference: docs/design/context_agent/design.md §3.3.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class LookupSlangTool:
    """In-memory slang lexicon lookup; no external calls, zero LLM cost."""

    name = "lookup_slang"
    description = "Look up words in the text against the Hebrew slang lexicon."
    parameters_schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Input text to scan for slang words."},
        },
        "required": ["text"],
    }

    def __init__(self, slang_lexicon_path: str) -> None:
        path = Path(slang_lexicon_path)
        if path.exists():
            try:
                self._lexicon: dict = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._lexicon = {}
        else:
            # Graceful degradation — tool returns no matches if lexicon missing
            self._lexicon = {}

    async def run(self, args: dict[str, Any]) -> dict[str, Any]:
        text: str = args.get("text", "")
        matches = []
        for word, meta in self._lexicon.items():
            if word in text:
                matches.append(
                    {
                        "word": word,
                        "meaning": meta.get("meaning", ""),
                        "common_use": meta.get("common_use", ""),
                        "valence": meta.get("valence", ""),
                        "age_group": meta.get("age_group", ""),
                    }
                )
        return {
            "tool": self.name,
            "result": {"matches": matches},
        }
