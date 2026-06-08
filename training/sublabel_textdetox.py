"""Stage-1 sub-labeling: textdetox multilingual Hebrew toxic rows -> 5-class labels.

Loads the 807 toxic rows from textdetox/multilingual_toxicity_dataset (he split),
calls Gemini few-shot to classify each into {abusive, hate, violence, pornographic},
and writes:
  - training/data/interim/textdetox_he_labeled.jsonl  (all 807 rows)
  - training/data/interim/qa_textdetox_sample.jsonl   (10% random sample, for human QA)

Cache: if textdetox_he_labeled.jsonl already exists and has >= 700 rows, skip.
Run in WSL2 training venv from repo root:
    python training/sublabel_textdetox.py
"""
from __future__ import annotations

import json
import random
from pathlib import Path

INTERIM_DIR = Path("training/data/interim")
OUT_PATH = INTERIM_DIR / "textdetox_he_labeled.jsonl"
QA_PATH = INTERIM_DIR / "qa_textdetox_sample.jsonl"

VALID_LABELS = {"abusive", "hate", "violence", "pornographic"}

# Few-shot examples for the sub-labeling prompt (Hebrew text -> label)
FEW_SHOT_EXAMPLES = [
    {
        "text": "אני אשבור לך את הפנים אם תגיד עוד מילה",
        "label": "violence",
        "reason": "explicit physical threat",
    },
    {
        "text": "כל הערבים הם חיות, לא שייכים לכאן",
        "label": "hate",
        "reason": "ethnic hate, dehumanization based on ethnicity",
    },
    {
        "text": "מטומטם ולא שווה כלום, תפסיק לנשום",
        "label": "abusive",
        "reason": "personal insult and verbal degradation, no ethnic/group target",
    },
    {
        "text": "תשלחי לי תמונות ערומות עכשיו אחרת אפרסם את שלך",
        "label": "pornographic",
        "reason": "sexual coercion/sextortion",
    },
    {
        "text": "נשים לא שוות כלום, כולן זונות",
        "label": "hate",
        "reason": "gender-based hate speech targeting women as a group",
    },
    {
        "text": "יא בן זונה, אני אסיים אותך היום בלילה",
        "label": "violence",
        "reason": "explicit death threat despite profanity",
    },
]


def build_system_prompt() -> str:
    return (
        "You are a Hebrew offensive-content classifier. "
        "Given a Hebrew text that is known to be toxic/offensive, "
        "classify it into exactly ONE of these four categories:\n\n"
        "  abusive    – personal insults, verbal abuse, degradation targeting an individual "
        "(no ethnic/group identity target, no explicit violence, no sexual content)\n"
        "  hate       – hate speech targeting a group by ethnicity, religion, gender, "
        "nationality, sexual orientation, disability\n"
        "  violence   – explicit threats of physical harm, calls to hurt/kill a person or group\n"
        "  pornographic – sexual solicitation, sexting, NSFW sexual content, sexual coercion\n\n"
        "Priority rule (when multiple fit): violence > hate > pornographic > abusive\n\n"
        "Respond ONLY with valid JSON: "
        '{"label": "<one of the four>", "confidence": <0.0-1.0>, "reason": "<one sentence>"}'
    )


def build_user_message(text: str, examples: list[dict]) -> str:
    shots = "\n".join(
        f'Text: "{ex["text"]}"\n'
        f'Answer: {{"label": "{ex["label"]}", "confidence": 0.95, "reason": "{ex["reason"]}"}}'
        for ex in examples
    )
    return f"{shots}\n\nText: \"{text}\"\nAnswer:"


def sublabel_batch(
    gemini,
    rows: list[dict],
    verbose: bool = True,
) -> list[dict]:
    """Sub-label a list of {text, toxic, ...} rows. Returns enriched dicts."""
    system = build_system_prompt()
    labeled: list[dict] = []
    for i, row in enumerate(rows):
        text = row["text"]
        user_msg = build_user_message(text, FEW_SHOT_EXAMPLES)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ]
        try:
            result = gemini.call_json(messages, max_tokens=150, temperature=0.2)
            label = result.get("label", "").strip().lower()
            confidence = float(result.get("confidence", 0.5))
            reason = result.get("reason", "")
            if label not in VALID_LABELS:
                print(f"  [WARN] row {i}: unexpected label '{label}', defaulting to abusive")
                label = "abusive"
                confidence = 0.3
        except Exception as exc:  # noqa: BLE001
            print(f"  [ERROR] row {i}: {exc}, defaulting to abusive")
            label = "abusive"
            confidence = 0.0
            reason = f"error: {exc}"

        labeled.append(
            {
                "text": text,
                "label": label,
                "source": "textdetox_he",
                "gemini_confidence": confidence,
                "gemini_reason": reason,
            }
        )
        if verbose and (i + 1) % 50 == 0:
            print(f"  [{i + 1}/{len(rows)}] labeled so far")

    return labeled


def main() -> None:
    import sys

    INTERIM_DIR.mkdir(parents=True, exist_ok=True)

    # Cache check
    if OUT_PATH.exists():
        existing = OUT_PATH.read_text(encoding="utf-8").splitlines()
        valid_lines = [l for l in existing if l.strip()]
        if len(valid_lines) >= 700:
            print(f"Cache hit: {OUT_PATH} already has {len(valid_lines)} rows. Skipping.")
            return
        print(f"Cache partial ({len(valid_lines)} rows). Re-running.")

    print("Loading textdetox multilingual_toxicity_dataset (he split)...")
    try:
        from datasets import load_dataset
        ds = load_dataset("textdetox/multilingual_toxicity_dataset", split="he")
    except Exception as exc:
        print(f"ERROR loading dataset: {exc}")
        sys.exit(1)

    # Filter toxic rows (binary toxic=1)
    all_rows = list(ds)
    toxic_rows = [r for r in all_rows if int(r.get("toxic", 0)) == 1]
    print(f"  Total he rows: {len(all_rows)}, toxic: {len(toxic_rows)}")

    if len(toxic_rows) == 0:
        print("ERROR: No toxic rows found in textdetox he split!")
        sys.exit(1)

    print(f"Sub-labeling {len(toxic_rows)} toxic rows with Gemini...")
    from training.gemini_utils import GeminiSync  # noqa: PLC0415
    gemini = GeminiSync()

    labeled = sublabel_batch(gemini, toxic_rows, verbose=True)

    # Write full output
    with OUT_PATH.open("w", encoding="utf-8") as f:
        for row in labeled:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(labeled)} rows to {OUT_PATH}")

    # Label distribution
    from collections import Counter
    dist = Counter(r["label"] for r in labeled)
    print(f"Label distribution: {dict(dist)}")

    # Write 10% QA sample (random, seed fixed)
    random.seed(42)
    qa_n = max(1, len(labeled) // 10)
    qa_sample = random.sample(labeled, qa_n)
    with QA_PATH.open("w", encoding="utf-8") as f:
        for row in qa_sample:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(qa_sample)} QA sample rows to {QA_PATH}")


if __name__ == "__main__":
    main()
