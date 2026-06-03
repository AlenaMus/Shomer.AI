from __future__ import annotations

import json
import re

from .schemas import Category

VALID_CATEGORIES: set[Category] = {
    "abusive", "hate", "violence", "pornographic", "non_offensive",
}


def build_user_prompt(text: str) -> str:
    return f'סווג את הטקסט הבא: "{text}"'


def parse_model_output(raw: str) -> dict:
    """Parse Ollama's JSON-formatted reply into a normalized dict.

    Falls back gracefully on slightly malformed JSON by extracting the first {...} block.
    """
    candidate = raw.strip()
    if not candidate.startswith("{"):
        m = re.search(r"\{.*\}", candidate, re.DOTALL)
        if not m:
            raise ValueError(f"No JSON object found in model output: {raw[:200]!r}")
        candidate = m.group(0)

    obj = json.loads(candidate)

    category = str(obj.get("category", "")).strip().lower().replace("-", "_")
    if category not in VALID_CATEGORIES:
        category = "non_offensive"

    is_offensive = obj.get("is_offensive")
    if not isinstance(is_offensive, bool):
        is_offensive = category != "non_offensive"

    try:
        confidence = float(obj.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    return {
        "is_offensive": is_offensive,
        "category": category,
        "confidence": confidence,
    }
