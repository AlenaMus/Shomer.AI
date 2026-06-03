"""Hebrew prompt builders for the context_agent module.

Two functions:
  - ``build_system_prompt()`` — role + output schema instructions (Hebrew).
  - ``build_user_prompt()``   — injects tool results + current message (Hebrew).

Reference: docs/design/context_agent/design.md §3.4.
"""

from __future__ import annotations

from ..schemas import ClassificationResult

# --------------------------------------------------------------------------- #
# System prompt                                                                #
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """\
אתה עוזר לזיהוי בריונות דיגיטלית בעברית.
תפקידך לנתח הודעה אחת בתוך הקשר שיחה ולהחליט: האם זהו איום אמיתי — או שיחה תמימה שנראית פוגענית מחוץ להקשר?

כללים:
- בדוק את כל ההיסטוריה לפני שאתה מחליט.
- סלנג נוער (לוזר, מטומטם, מפגר בהקשר ידידותי) הוא לרוב לא בריונות.
- איום חוזר, שנאה ממוקדת, או תוכן מיני — הם סיבה לסמן.
- ציין ONLY valid JSON, בלי טקסט נוסף.

סכמת הפלט הנדרשת:
{
  "is_real_threat": true | false,
  "severity": "none" | "low" | "medium" | "high",
  "explanation": "משפט הסבר אחד בעברית לטיפוס ההורה",
  "reasoning": "שרשרת הנמקה (לצורך audit) — אפשר באנגלית"
}\
"""


def build_system_prompt() -> str:
    """Return the static Hebrew system prompt."""
    return SYSTEM_PROMPT


# --------------------------------------------------------------------------- #
# User prompt                                                                  #
# --------------------------------------------------------------------------- #

def build_user_prompt(
    text: str,
    classifier_result: ClassificationResult,
    conversation_history: list[dict],   # list of ConversationTurn-like dicts
    slang_hits: dict,                    # from lookup_slang tool
    age_info: dict | None = None,        # from check_age tool
    child_age: int = 13,
) -> str:
    """Build the Hebrew user-turn prompt by injecting tool results.

    Parameters
    ----------
    text:
        The current (borderline) message.
    classifier_result:
        Frontline classification result.
    conversation_history:
        List of ConversationTurn-like objects (dicts with ``role``, ``text``).
    slang_hits:
        Result from the ``lookup_slang`` tool — dict with ``matches`` list.
    age_info:
        Result from the ``check_age_appropriateness`` tool.
    child_age:
        Child's age (years) for the age profile line.
    """
    history_block = _format_history(conversation_history)
    slang_block = _format_slang(slang_hits)
    sensitivity = (age_info or {}).get("sensitivity_level", "moderate")

    return (
        f"## הודעה לניתוח\n"
        f'"{text}"\n\n'
        f"## תוצאת המסווג הראשוני\n"
        f"קטגוריה: {classifier_result.label} | "
        f"ביטחון: {classifier_result.confidence:.2f}\n\n"
        f"## היסטוריית השיחה (עד 5 תורים אחרונים)\n"
        f"{history_block}\n\n"
        f"## מידע על מילות סלנג שזוהו\n"
        f"{slang_block}\n\n"
        f"## פרופיל גיל\n"
        f"גיל הילד: {child_age} שנים | רמת רגישות: {sensitivity}\n\n"
        f"הנח את ה-JSON בלבד בפלט:"
    )


# --------------------------------------------------------------------------- #
# Private helpers                                                              #
# --------------------------------------------------------------------------- #

def _format_history(turns: list[dict]) -> str:
    if not turns:
        return "(אין היסטוריה זמינה)"
    lines = []
    for t in turns:
        role = t.get("role", "unknown")
        txt = t.get("text", "")
        lines.append(f"[{role}]: {txt}")
    return "\n".join(lines)


def _format_slang(slang_hits: dict) -> str:
    matches = slang_hits.get("matches", [])
    if not matches:
        return "(לא זוהו מילות סלנג)"
    parts = []
    for m in matches:
        word = m.get("word", "")
        meaning = m.get("meaning", "")
        use = m.get("common_use", "")
        valence = m.get("valence", "")
        parts.append(f"• {word}: {meaning} | שימוש: {use} | ערכיות: {valence}")
    return "\n".join(parts)
