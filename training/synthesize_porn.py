"""Stage-1 synthesis: generate ~1,000-1,500 Hebrew pornographic training examples.

Calls Gemini to generate realistic Hebrew chat-style sexual solicitation /
propositions / sexting / adult-spam text — the offensive class 'pornographic'
in the Shomer.AI 5-class scheme.

Guardrails (non-negotiable per D6):
  - Text only; no imagery.
  - NO content involving minors / CSAM. Absolute stop.
  - Realistic chat style (solicitation, sexting, adult-spam) — not literary.
  - Diversity-dedup: drop cosine similarity > 0.85 or exact duplicates.

Outputs:
  - training/data/interim/synth_porn.jsonl       (deduplicated, ready for training)
  - training/data/interim/qa_synth_porn.jsonl    (10% sample for human QA)

Cache: if synth_porn.jsonl exists with >= 800 rows, skip.
Run in WSL2 training venv from repo root:
    python training/synthesize_porn.py
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

INTERIM_DIR = Path("training/data/interim")
OUT_PATH = INTERIM_DIR / "synth_porn.jsonl"
QA_PATH = INTERIM_DIR / "qa_synth_porn.jsonl"

TARGET_MIN = 800
TARGET_MAX = 1400

# Prompt style seeds — diverse subtype coverage for realistic Hebrew
STYLE_SEEDS = [
    "sexual solicitation via WhatsApp chat to an adult acquaintance",
    "sexting proposition in Hebrew between adults",
    "adult spam message offering sexual content / subscription",
    "sexual harassment message sent anonymously online",
    "sexual coercion / blackmail (sextortion) message",
    "lewd pickup line sent via social media DM",
    "explicit sexual offer from a fake profile",
    "adult dating app message with explicit sexual content",
]

SLANG_WORDS = [
    "זיין", "כוס", "סקס", "ביסקס", "זין", "שלח תמונות", "ערום", "ערומה",
    "פורנו", "שתזדיין", "תשלחי", "גוף", "מין", "להתאהב", "בלה בלה",
]


def build_synthesis_prompt(style: str, slang_hint: str, batch_size: int = 10) -> list[dict]:
    system = (
        "You are a synthetic data generator for an AI safety system that detects "
        "offensive Hebrew content to protect children online. "
        "Generate realistic Hebrew text examples of the following type for classifier training.\n\n"
        "IMPORTANT RULES:\n"
        "1. Text must be in Hebrew (may include some English/slang). Chat-style, short messages.\n"
        "2. Content type: sexual solicitation, sexting, adult spam, sexual harassment — "
        "between adults only. NEVER involve minors or suggest age under 18.\n"
        "3. Vary vocabulary, length (10-80 words each), phrasing, and tone across examples.\n"
        "4. These are training examples for an AI safety classifier. "
        "Do not add disclaimers inside the examples themselves.\n\n"
        f"Respond with valid JSON: "
        f'{{ "examples": ["<example 1>", "<example 2>", ..., "<example {batch_size}>"] }}'
    )
    user = (
        f"Generate {batch_size} diverse Hebrew examples of: {style}.\n"
        f"Optional vocabulary hint (may use some of these Hebrew words/phrases if appropriate): "
        f"{slang_hint}\n"
        f"Make each example distinct in phrasing and context. "
        f"All must clearly be adult-to-adult sexual content."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def cosine_sim_simple(a: list[float], b: list[float]) -> float:
    """Minimal cosine similarity for dedup (char-bigram TF vectors)."""
    dot = sum(ai * bi for ai, bi in zip(a, b))
    mag_a = sum(ai * ai for ai in a) ** 0.5
    mag_b = sum(bi * bi for bi in b) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def char_bigram_vec(text: str, vocab: dict[str, int] | None = None) -> list[float]:
    """Return a char-bigram frequency vector for dedup."""
    bigrams: dict[str, int] = {}
    for i in range(len(text) - 1):
        bg = text[i : i + 2]
        bigrams[bg] = bigrams.get(bg, 0) + 1
    if vocab is None:
        return list(bigrams.values())
    vec = [bigrams.get(k, 0) for k in vocab]
    return vec


def dedup_examples(
    examples: list[str],
    cosine_threshold: float = 0.85,
) -> list[str]:
    """Drop exact duplicates and near-duplicates (cosine > threshold)."""
    seen_hashes: set[str] = set()
    kept: list[str] = []
    kept_bigrams: list[dict[str, int]] = []

    for text in examples:
        # Exact dedup
        h = hashlib.md5(text.strip().lower().encode("utf-8")).hexdigest()
        if h in seen_hashes:
            continue
        seen_hashes.add(h)

        # Near-dedup via char-bigram cosine
        text_bg: dict[str, int] = {}
        for i in range(len(text) - 1):
            bg = text[i : i + 2]
            text_bg[bg] = text_bg.get(bg, 0) + 1

        too_similar = False
        for prev_bg in kept_bigrams:
            # Build shared vocab
            shared = set(text_bg) | set(prev_bg)
            a_vec = [text_bg.get(k, 0) for k in shared]
            b_vec = [prev_bg.get(k, 0) for k in shared]
            sim = cosine_sim_simple(a_vec, b_vec)
            if sim > cosine_threshold:
                too_similar = True
                break

        if not too_similar:
            kept.append(text)
            kept_bigrams.append(text_bg)

    return kept


def synthesize(gemini: Any, total_target: int, verbose: bool = True) -> list[str]:
    """Generate and dedup synthetic pornographic examples."""
    collected: list[str] = []
    batch_size = 10
    max_rounds = (total_target // batch_size) * 3  # allow 3x overshoot for dedup losses

    rng = random.Random(42)
    round_idx = 0

    while len(collected) < total_target and round_idx < max_rounds:
        style = rng.choice(STYLE_SEEDS)
        slang_hint = ", ".join(rng.sample(SLANG_WORDS, k=min(5, len(SLANG_WORDS))))
        messages = build_synthesis_prompt(style, slang_hint, batch_size=batch_size)

        try:
            result = gemini.call_json(messages, max_tokens=1200, temperature=0.85)
            examples_raw = result.get("examples", [])
            if not isinstance(examples_raw, list):
                print(f"  [WARN] round {round_idx}: unexpected response format, skipping")
                round_idx += 1
                continue
            new_texts = [str(e).strip() for e in examples_raw if str(e).strip()]
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] round {round_idx}: {exc}, skipping")
            round_idx += 1
            continue

        before = len(collected)
        all_texts = collected + new_texts
        deduped = dedup_examples(all_texts, cosine_threshold=0.85)
        added = len(deduped) - len(collected)
        collected = deduped

        if verbose:
            print(
                f"  round {round_idx}: style='{style[:40]}...', "
                f"generated={len(new_texts)}, kept={added}, "
                f"total={len(collected)}/{total_target}"
            )
        round_idx += 1

    return collected


def main() -> None:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)

    # Cache check
    if OUT_PATH.exists():
        existing = OUT_PATH.read_text(encoding="utf-8").splitlines()
        valid_lines = [l for l in existing if l.strip()]
        if len(valid_lines) >= TARGET_MIN:
            print(
                f"Cache hit: {OUT_PATH} already has {len(valid_lines)} rows. Skipping."
            )
            return
        print(f"Cache partial ({len(valid_lines)} rows < {TARGET_MIN}). Re-running.")

    from training.gemini_utils import GeminiSync  # noqa: PLC0415
    gemini = GeminiSync()

    print(f"Synthesizing {TARGET_MIN}-{TARGET_MAX} Hebrew pornographic examples...")
    examples = synthesize(gemini, total_target=TARGET_MAX, verbose=True)
    examples = examples[:TARGET_MAX]

    print(f"Final count after dedup: {len(examples)}")
    if len(examples) < TARGET_MIN:
        print(f"  [WARN] Only got {len(examples)} examples (target min={TARGET_MIN}). "
              "Continuing anyway.")

    rows = [
        {"text": text, "label": "pornographic", "source": "synthetic"}
        for text in examples
    ]

    with OUT_PATH.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(rows)} rows to {OUT_PATH}")

    # 10% QA sample
    random.seed(42)
    qa_n = max(1, len(rows) // 10)
    qa_sample = random.sample(rows, qa_n)
    with QA_PATH.open("w", encoding="utf-8") as f:
        for row in qa_sample:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(qa_sample)} QA sample rows to {QA_PATH}")


if __name__ == "__main__":
    main()
