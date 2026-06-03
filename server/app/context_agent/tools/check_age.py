"""CheckAgeAppropriatenessTool — rule-based age sensitivity profile.

Returns a static sensitivity profile dict for the child's age band.
No external calls, no LLM cost.

Reference: docs/design/context_agent/design.md §3.3.
"""

from __future__ import annotations

from typing import Any

# Static age-band sensitivity table
_AGE_PROFILES: dict[str, dict] = {
    "under_10": {
        "sensitivity_level": "high",
        "notes": "Under 10: high sensitivity; any insult or exclusion language is flagged.",
    },
    "10_12": {
        "sensitivity_level": "moderate_high",
        "notes": "Age 10-12: elevated sensitivity; sustained insults always flagged.",
    },
    "13_15": {
        "sensitivity_level": "moderate",
        "notes": "Age 13-15: typical peer banter normalised; sustained or targeted insults still flagged.",
    },
    "16_18": {
        "sensitivity_level": "moderate_low",
        "notes": "Age 16-18: broader slang tolerance; sexual content and threats always flagged.",
    },
    "over_18": {
        "sensitivity_level": "low",
        "notes": "Over 18: adult content rules apply; explicit threats flagged.",
    },
}


def _age_band(child_age: int) -> str:
    if child_age < 10:
        return "under_10"
    if child_age <= 12:
        return "10_12"
    if child_age <= 15:
        return "13_15"
    if child_age <= 18:
        return "16_18"
    return "over_18"


class CheckAgeAppropriatenessTool:
    """Returns the age-sensitivity profile for a given child age."""

    name = "check_age"
    description = "Return the age-sensitivity profile for the child's age band."
    parameters_schema = {
        "type": "object",
        "properties": {
            "child_age": {
                "type": "integer",
                "description": "Age of the child in years.",
            },
        },
        "required": ["child_age"],
    }

    async def run(self, args: dict[str, Any]) -> dict[str, Any]:
        child_age: int = int(args.get("child_age", 13))
        band = _age_band(child_age)
        profile = _AGE_PROFILES[band].copy()
        profile["child_age"] = child_age
        return {"tool": self.name, "result": profile}
