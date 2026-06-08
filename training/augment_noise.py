"""augment_noise.py — Deterministic character-level Hebrew typo-noise augmentation.

Decision D9.2(a): label-preserving noise ops targeting the weak stylistic slices
(poor_spelling=0.47, children_mistakes=0.57 from D8 eval).

Decision D11: intensity/density parameter added so a "heavy" mode corrupts ~60-80%
of words per sentence (matching the poor_spelling eval slice density).  The existing
light mode (~2 ops per text, ~28% of examples) is unchanged for backward compat.

Noise operations implemented:
  N1  Adjacent-key swaps (Hebrew keyboard layout)
  N2  Dropped / doubled letters
  N3  Phonetic / homophone confusions kids make:
        ת↔ט  כ↔ק  ח↔כ  א↔ע↔ה  ס↔שׁ/שׂ  (shimush / shinui letters)
        EXTENDED (D11): כ↔ח↔ק triangle, ו↔ב, צ↔ס, ג↔ד also added
  N4  Final-form errors (non-final form used at word-end or vice-versa):
        ם↔מ  ן↔נ  ך↔כ  ף↔פ  ץ↔צ
        EXTENDED (D11): at word-end, write medial as regular + append trailing letter
        (e.g. לך → לכא, ים → ימ) matching the slice pattern
  N5  Matres-lectionis variation (drop/add vav or yod plene spelling):
        כותב → כתב, כתב → כותב style (simple: drop/insert ו or י in mid-word)
  N6  Run-on words / stray spaces (merge two adjacent words or insert mid-word space)
  N7  (D11 new) Per-word phonetic sweep: for "heavy" mode, iterate every character in
        a word and independently decide whether to apply a phonetic substitution.

Usage (from prepare_data_dictabert.py):
    from augment_noise import add_noise_to_pool, add_noise_to_pool_heavy

    # Light mode (D9 unchanged):
    noisy = add_noise_to_pool(
        rows,
        fraction=0.28,
        seed=42,
        bias_toward_offensive=True,
    )

    # Heavy mode (D11 — ~60-80% of words corrupted):
    heavy = add_noise_to_pool_heavy(
        rows,
        fraction=0.22,        # fraction of pool that gets a heavy-noise twin
        seed=142,             # distinct seed from light to avoid RNG collision
        word_corrupt_prob=0.70,  # probability each word gets >=1 error
    )
    # Both return only NEW rows — caller appends to train pool.

Design constraints:
  - Deterministic (seed=42 for light, seed=142 for heavy throughout).
  - Label is NEVER changed (label-preserving by construction).
  - Applied only to train rows — caller must not pass val/test rows.
  - Bias toward minority + offensive classes (sample weight 2× vs non_offensive).
  - The `guardrail` parameter checks the resulting clear_hebrew slice (external eval
    responsibility of prepare_data_dictabert.py — not enforced here).

Run standalone for a quick smoke-test:
    python training/augment_noise.py
"""
from __future__ import annotations

import random
import re
import unicodedata
from pathlib import Path
from typing import Sequence


# ---------------------------------------------------------------------------
# Hebrew keyboard layout adjacency (standard Israeli keyboard, QWERTY base)
# Each key maps to 1–4 adjacent keys on the same or adjacent rows.
# ---------------------------------------------------------------------------
_HEB_KEYBOARD_ADJACENT: dict[str, str] = {
    # Top row (right-to-left physical layout maps to q-p row)
    "ק": "ר",
    "ר": "קא",
    "א": "רט",
    "ט": "אוש",
    "ו": "טנ",
    "נ": "ומ",
    "מ": "נצ",
    "צ": "מ",
    # Home row
    "ש": "ד",
    "ד": "שג",
    "ג": "דכ",
    "כ": "גע",
    "ע": "כי",
    "י": "עח",
    "ח": "יל",
    "ל": "חף",
    "ף": "לפ",
    "פ": "ף",
    # Bottom row
    "ז": "ס",
    "ס": "זב",
    "ב": "סה",
    "ה": "בנ",
    "ת": "הז",
    # Extra
    "ן": "ל",
    "ם": "פ",
    "ך": "ל",
    "ץ": "מ",
}


# ---------------------------------------------------------------------------
# Phonetic / homophone confusions (N3)
# Bidirectional substitution sets — any pair within a set can be swapped.
# D11 extended: added כ↔ח↔ק triangle, צ↔ס, ג↔ד, and explicit שׁ/שׂ both map
# to ס (since both sound like samech in kids' phonetic writing).
# ---------------------------------------------------------------------------
_PHONETIC_GROUPS: list[list[str]] = [
    ["ת", "ט"],              # tet/tav — PERVASIVE in poor_spelling (אטמול/אטה/טמיד)
    ["כ", "ק", "ח"],         # D11: full triangle — kaf/qof/chet all confusion zone
    ["א", "ע", "ה"],         # alef/ayin/he (silent letters kids confuse: פיצע/מא/איה)
    ["ס", "ש"],              # samech vs shin (same phoneme in spoken Hebrew)
    ["ב", "ו"],              # bet/vav (after vowels, interchangeable in speech)
    ["צ", "ס"],              # D11: tzadi vs samech (ס↔צ, e.g. מצחיק/מסחיק)
    ["ג", "ד"],              # D11: gimel/dalet (kids' handwriting confusion)
    ["ר", "ד"],              # D11: resh/dalet (similar shape in handwriting)
]
# Flatten to a fast lookup: char -> list of replacement chars
_PHONETIC_MAP: dict[str, list[str]] = {}
for _group in _PHONETIC_GROUPS:
    for _ch in _group:
        _alts = [c for c in _group if c != _ch]
        if _alts:
            if _ch in _PHONETIC_MAP:
                # merge if a char appears in multiple groups (e.g. כ in two groups)
                _PHONETIC_MAP[_ch] = list(dict.fromkeys(_PHONETIC_MAP[_ch] + _alts))
            else:
                _PHONETIC_MAP[_ch] = _alts


# ---------------------------------------------------------------------------
# Final-form errors (N4)
# ---------------------------------------------------------------------------
_FINAL_TO_MEDIAL: dict[str, str] = {
    "ם": "מ",
    "ן": "נ",
    "ך": "כ",
    "ף": "פ",
    "ץ": "צ",
}
_MEDIAL_TO_FINAL: dict[str, str] = {v: k for k, v in _FINAL_TO_MEDIAL.items()}

# All final-form chars for quick membership test
_FINAL_CHARS: set[str] = set(_FINAL_TO_MEDIAL.keys())
_MEDIAL_WITH_FINAL: set[str] = set(_MEDIAL_TO_FINAL.keys())


# ---------------------------------------------------------------------------
# Matres-lectionis helpers (N5)
# ---------------------------------------------------------------------------
_MATER_CHARS = frozenset("וי")


def _drop_mater(word: str, rng: random.Random) -> str:
    """Drop one vav or yod from the middle of the word (not first/last char)."""
    candidates = [
        i for i, ch in enumerate(word)
        if ch in _MATER_CHARS and 0 < i < len(word) - 1
    ]
    if not candidates:
        return word
    idx = rng.choice(candidates)
    return word[:idx] + word[idx + 1:]


def _insert_mater(word: str, rng: random.Random) -> str:
    """Insert a vav or yod after a consonant in the middle of a word."""
    if len(word) < 2:
        return word
    # Insert after a random position in [1, len-2] (not before first / after last char)
    candidates = list(range(1, len(word) - 1))
    if not candidates:
        return word
    idx = rng.choice(candidates)
    ch = rng.choice(["ו", "י"])
    return word[:idx] + ch + word[idx:]


# ---------------------------------------------------------------------------
# Core character-level operations
# ---------------------------------------------------------------------------

def _apply_adj_key_swap(text: str, rng: random.Random, p: float = 0.12) -> str:
    """N1: swap one character to an adjacent keyboard key."""
    chars = list(text)
    candidates = [
        i for i, ch in enumerate(chars)
        if ch in _HEB_KEYBOARD_ADJACENT
    ]
    if not candidates or rng.random() > p * len(candidates) / max(len(text), 1):
        return text
    idx = rng.choice(candidates)
    alts = _HEB_KEYBOARD_ADJACENT[chars[idx]]
    if alts:
        chars[idx] = rng.choice(list(alts))
    return "".join(chars)


def _apply_drop_or_double(text: str, rng: random.Random, p_drop: float = 0.08, p_double: float = 0.06) -> str:
    """N2: drop or double a single Hebrew letter."""
    chars = list(text)
    heb_indices = [i for i, ch in enumerate(chars) if "א" <= ch <= "ת"]
    if not heb_indices:
        return text

    r = rng.random()
    idx = rng.choice(heb_indices)
    if r < p_drop:
        chars.pop(idx)
    elif r < p_drop + p_double:
        chars.insert(idx, chars[idx])
    return "".join(chars)


def _apply_phonetic(text: str, rng: random.Random, p: float = 0.15) -> str:
    """N3: replace one letter with a phonetically similar one."""
    chars = list(text)
    candidates = [i for i, ch in enumerate(chars) if ch in _PHONETIC_MAP]
    if not candidates:
        return text
    if rng.random() > p:
        return text
    idx = rng.choice(candidates)
    alts = _PHONETIC_MAP[chars[idx]]
    chars[idx] = rng.choice(alts)
    return "".join(chars)


def _apply_final_form_error_word(word: str, rng: random.Random) -> str:
    """N4 word-level: unconditionally try to introduce a final-form error into word.

    D11 extended pattern: the poor_spelling slice writes final letters as medial
    AND appends an extra vowel-letter (e.g. לכא for לך, בגדימ for בגדים, אתנ for אתן).
    We model both directions:
      - medial at word-end where final expected (just swap last char)
      - final at non-end (swap inner final char to medial)
      - D11: medial at word-end + append א or א-like char (~20% of the time)
    """
    if not word:
        return word
    chars = list(word)
    changed = False

    # Direction 1: last char is medial-with-final-twin -> should be final (swap to medial is already default)
    # We reverse: keep it medial (which IS the error — it should be final)
    # That's already what happens when we write מ at end instead of ם — so we DON'T change here.
    # Instead swap FINAL → MEDIAL at end (the slice shows medial forms at end of word)
    last = chars[-1]
    if last in _FINAL_TO_MEDIAL:
        # Correct final → noisy medial
        chars[-1] = _FINAL_TO_MEDIAL[last]
        changed = True
        # 20% chance: also append א (e.g. לכא pattern from the slice)
        if rng.random() < 0.20:
            chars.append("א")
    elif last in _MEDIAL_WITH_FINAL:
        # Already medial at end — this IS the error (non-final form). leave.
        # But 15% chance: insert a final in the middle (opposite error)
        if len(chars) > 2 and rng.random() < 0.15:
            mid = rng.randint(1, len(chars) - 1)
            medial = chars[mid]
            if medial in _MEDIAL_WITH_FINAL:
                chars[mid] = _MEDIAL_TO_FINAL[medial]
                changed = True
    elif len(chars) > 1:
        # Try to swap an inner final char to medial
        for i, ch in enumerate(chars[:-1]):
            if ch in _FINAL_CHARS and rng.random() < 0.5:
                chars[i] = _FINAL_TO_MEDIAL[ch]
                changed = True
                break

    if changed:
        return "".join(chars)
    return word


def _apply_final_form_error(text: str, rng: random.Random, p: float = 0.15) -> str:
    """N4: swap a final/medial form — use medial where final expected, or vice-versa.

    Strategy: pick one character that is final OR medial-with-final-twin and swap it.
    """
    words = text.split()
    if not words:
        return text
    word_idx = rng.randint(0, len(words) - 1)
    word = words[word_idx]
    if not word:
        return text

    r = rng.random()
    if r > p:
        return text

    chars = list(word)
    changed = False

    # Try to flip the last char if it's a medial-with-final (should be final)
    last = chars[-1]
    if last in _MEDIAL_WITH_FINAL and rng.random() < 0.5:
        chars[-1] = _MEDIAL_TO_FINAL[last]
        changed = True
    # Or flip a final char that's NOT at the end (should be medial)
    elif len(chars) > 1:
        for i, ch in enumerate(chars[:-1]):
            if ch in _FINAL_CHARS and rng.random() < 0.4:
                chars[i] = _FINAL_TO_MEDIAL[ch]
                changed = True
                break

    if changed:
        words[word_idx] = "".join(chars)
        return " ".join(words)
    return text


def _apply_mater_variation(text: str, rng: random.Random, p: float = 0.12) -> str:
    """N5: drop or insert a vav/yod plene in a random word."""
    if rng.random() > p:
        return text
    words = text.split()
    if not words:
        return text
    # Pick a word with Hebrew chars that is longer than 2 chars
    candidates = [
        i for i, w in enumerate(words)
        if len(w) > 2 and any("א" <= ch <= "ת" for ch in w)
    ]
    if not candidates:
        return text
    idx = rng.choice(candidates)
    if rng.random() < 0.5:
        words[idx] = _drop_mater(words[idx], rng)
    else:
        words[idx] = _insert_mater(words[idx], rng)
    return " ".join(words)


def _apply_runon_or_space(text: str, rng: random.Random, p: float = 0.10) -> str:
    """N6: merge two adjacent words OR insert a stray space inside a word."""
    if rng.random() > p:
        return text
    words = text.split()
    if len(words) < 2:
        return text

    if rng.random() < 0.5:
        # Run-on: merge two adjacent words
        idx = rng.randint(0, len(words) - 2)
        merged = words[idx] + words[idx + 1]
        words = words[:idx] + [merged] + words[idx + 2:]
    else:
        # Stray space: split one word at a random position
        idx = rng.randint(0, len(words) - 1)
        word = words[idx]
        if len(word) > 2:
            split_pos = rng.randint(1, len(word) - 1)
            words = words[:idx] + [word[:split_pos], word[split_pos:]] + words[idx + 1:]

    return " ".join(words)


# ---------------------------------------------------------------------------
# D11: Heavy per-word corruption (N7)
# Corrupts each word independently at `word_corrupt_prob` probability.
# This matches the poor_spelling eval slice where nearly EVERY word is corrupted.
# ---------------------------------------------------------------------------

def _corrupt_word_heavy(word: str, rng: random.Random) -> str:
    """Apply 1-3 character-level ops to a single word deterministically.

    Op selection is random per word to get diverse error profiles.
    """
    if len(word) < 2:
        return word

    # Choose 1-2 ops per word (occasionally 3 for longer words)
    n_ops = 1
    if len(word) >= 4 and rng.random() < 0.50:
        n_ops = 2
    if len(word) >= 6 and rng.random() < 0.25:
        n_ops = 3

    op_pool = ["phonetic", "final_form", "drop_double", "mater"]
    chosen_ops = rng.sample(op_pool, min(n_ops, len(op_pool)))

    for op in chosen_ops:
        if op == "phonetic":
            # Per-character phonetic sweep on the word — more thorough than sentence-level
            chars = list(word)
            for i, ch in enumerate(chars):
                if ch in _PHONETIC_MAP and rng.random() < 0.55:
                    chars[i] = rng.choice(_PHONETIC_MAP[ch])
            word = "".join(chars)
        elif op == "final_form":
            word = _apply_final_form_error_word(word, rng)
        elif op == "drop_double":
            # Drop or double a single Hebrew letter
            heb_idx = [i for i, ch in enumerate(word) if "א" <= ch <= "ת"]
            if heb_idx:
                idx = rng.choice(heb_idx)
                r = rng.random()
                chars = list(word)
                if r < 0.50:
                    chars.pop(idx)
                else:
                    chars.insert(idx, chars[idx])
                word = "".join(chars)
        elif op == "mater":
            rng_tmp = random.Random(rng.randint(0, 2**31))
            if rng.random() < 0.5:
                word = _drop_mater(word, rng_tmp)
            else:
                word = _insert_mater(word, rng_tmp)

    return word


def apply_noise_heavy(text: str, rng: random.Random, word_corrupt_prob: float = 0.70) -> str:
    """D11 heavy-mode: corrupt ~word_corrupt_prob fraction of words in the sentence.

    Matches the poor_spelling eval slice (nearly every word misspelled).
    Also has a small probability of merging adjacent words (run-on) or adding
    a stray space — same as N6 in light mode but applied after per-word corruption.

    Args:
        text:               Input text string.
        rng:                Seeded random.Random instance for determinism.
        word_corrupt_prob:  Probability each word gets corrupted. D11 target: 0.60-0.80.

    Returns:
        Heavily noised variant of text. Label-preserving.
    """
    words = text.split()
    if not words:
        return text

    corrupted = []
    for word in words:
        if rng.random() < word_corrupt_prob:
            corrupted.append(_corrupt_word_heavy(word, rng))
        else:
            corrupted.append(word)

    result = " ".join(corrupted)

    # Small chance of run-on or stray space at sentence level (N6)
    if rng.random() < 0.08 and len(corrupted) >= 2:
        idx = rng.randint(0, len(corrupted) - 2)
        words2 = corrupted[:]
        words2[idx] = words2[idx] + words2[idx + 1]
        del words2[idx + 1]
        result = " ".join(words2)

    return result.strip()


# ---------------------------------------------------------------------------
# One complete noisy variant of a text (light mode — unchanged from D9)
# ---------------------------------------------------------------------------

def apply_noise(text: str, rng: random.Random, n_ops: int = 2) -> str:
    """Apply n_ops randomly chosen noise operations to text. Label-preserving."""
    ops = [
        _apply_adj_key_swap,
        _apply_drop_or_double,
        _apply_phonetic,
        _apply_final_form_error,
        _apply_mater_variation,
        _apply_runon_or_space,
    ]
    chosen = rng.sample(ops, min(n_ops, len(ops)))
    for op in chosen:
        text = op(text, rng)
    return text.strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

LABEL_NAMES = ["non_offensive", "abusive", "hate", "violence", "pornographic"]
LABEL2ID = {l: i for i, l in enumerate(LABEL_NAMES)}
_OFFENSIVE_LABELS = {"abusive", "hate", "violence", "pornographic"}


def add_noise_to_pool(
    rows: list[dict],
    fraction: float = 0.28,
    seed: int = 42,
    bias_toward_offensive: bool = True,
    n_ops: int = 2,
) -> list[dict]:
    """Generate noisy twins for a fraction of rows in `rows`.

    Args:
        rows:                    Train rows. MUST be train only — never pass val/test.
        fraction:                Fraction of pool rows that get a noisy twin.
                                 D9 spec: 25–30%, default 0.28.
        seed:                    RNG seed (default 42 for determinism).
        bias_toward_offensive:   If True, offensive-class rows are 2× more likely to
                                 be selected for noisy copying.
        n_ops:                   Number of noise ops applied per text (default 2).

    Returns:
        Only the NEW noisy rows (originals are not included). Caller appends to pool.
    """
    rng = random.Random(seed)

    # Build a sampling weight list: offensive rows weighted 2× non_offensive
    if bias_toward_offensive:
        weights = [
            2.0 if r.get("label") in _OFFENSIVE_LABELS else 1.0
            for r in rows
        ]
    else:
        weights = [1.0] * len(rows)

    # Target total noisy rows
    n_total = int(len(rows) * fraction)
    if n_total == 0:
        return []

    # Weighted sample (with replacement) — we may pick the same original multiple times
    # to generate distinct noisy variants
    selected_indices = rng.choices(range(len(rows)), weights=weights, k=n_total)

    noisy_rows: list[dict] = []
    for pick_idx, orig_idx in enumerate(selected_indices):
        orig = rows[orig_idx]
        orig_text = orig.get("text", "")
        if not orig_text.strip():
            continue
        # Use a unique sub-seed per pick so variants are diverse
        pick_rng = random.Random(seed + pick_idx + orig_idx * 1000)
        noisy_text = apply_noise(orig_text, pick_rng, n_ops=n_ops)
        if not noisy_text.strip() or noisy_text == orig_text:
            # Degenerate: noise was a no-op; try once more with one extra op
            noisy_text = apply_noise(orig_text, random.Random(seed + pick_idx + 1), n_ops=n_ops + 1)
        if not noisy_text.strip():
            continue
        label = orig["label"]
        noisy_rows.append({
            "text": noisy_text,
            "label": label,
            "label_id": LABEL2ID.get(label, -1),
            "source": f"{orig.get('source', 'unknown')}_noise",
        })

    return noisy_rows


def add_noise_to_pool_heavy(
    rows: list[dict],
    fraction: float = 0.22,
    seed: int = 142,
    word_corrupt_prob: float = 0.70,
) -> list[dict]:
    """D11: Generate heavily-corrupted twins for a fraction of rows in `rows`.

    Unlike `add_noise_to_pool` (light mode, ~2 ops per text), this applies
    `apply_noise_heavy` which corrupts `word_corrupt_prob` fraction of EACH WORD,
    matching the density of the `poor_spelling` eval slice.

    Selection is uniform across ALL 5 classes (NOT offensive-biased) because the
    poor_spelling slice is 52% non_offensive — we need noisy non_offensive too.

    Args:
        rows:                Train rows. MUST be train only — never pass val/test.
        fraction:            Fraction of pool rows that get a heavy-noisy twin.
                             D11 spec: ~20-25%, default 0.22.
        seed:                RNG seed (default 142 — distinct from light-noise seed=42).
        word_corrupt_prob:   Per-word corruption probability (default 0.70 for ~70%).

    Returns:
        Only the NEW heavily-noised rows (originals NOT included).
        Caller appends to train pool (keeping clean originals too).
    """
    rng = random.Random(seed)

    # Uniform weights — sample across all classes equally (slice is ~50/50)
    weights = [1.0] * len(rows)

    n_total = int(len(rows) * fraction)
    if n_total == 0:
        return []

    selected_indices = rng.choices(range(len(rows)), weights=weights, k=n_total)

    heavy_rows: list[dict] = []
    for pick_idx, orig_idx in enumerate(selected_indices):
        orig = rows[orig_idx]
        orig_text = orig.get("text", "")
        if not orig_text.strip():
            continue
        pick_rng = random.Random(seed + pick_idx + orig_idx * 997)
        noisy_text = apply_noise_heavy(orig_text, pick_rng, word_corrupt_prob=word_corrupt_prob)
        if not noisy_text.strip() or noisy_text == orig_text:
            # Try again with a slightly different seed
            noisy_text = apply_noise_heavy(
                orig_text,
                random.Random(seed + pick_idx + orig_idx * 997 + 1),
                word_corrupt_prob=min(word_corrupt_prob + 0.1, 1.0),
            )
        if not noisy_text.strip():
            continue
        label = orig["label"]
        heavy_rows.append({
            "text": noisy_text,
            "label": label,
            "label_id": LABEL2ID.get(label, -1),
            "source": f"{orig.get('source', 'unknown')}_heavy_noise",
        })

    return heavy_rows


# ---------------------------------------------------------------------------
# Smoke-test (run standalone)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    samples = [
        {"text": "אתה אידיוט מוחלט שלא יודע כלום", "label": "abusive", "label_id": 1, "source": "test"},
        {"text": "כל הערבים צריכים להיות מגורשים מהארץ", "label": "hate", "label_id": 2, "source": "test"},
        {"text": "היום הוא יום יפה לטיול בפארק", "label": "non_offensive", "label_id": 0, "source": "test"},
        {"text": "אני אשבור לך את הרגליים אם תמשיך", "label": "violence", "label_id": 3, "source": "test"},
        {"text": "שלום חבר, מה שלומך היום?", "label": "non_offensive", "label_id": 0, "source": "test"},
    ]

    print("=== augment_noise.py smoke-test ===\n")
    noisy = add_noise_to_pool(samples, fraction=1.0, seed=42, bias_toward_offensive=True)
    print(f"Generated {len(noisy)} noisy rows from {len(samples)} originals")
    # Show first 5 noisy rows with the source label to confirm label preservation
    label_set = {r["label"] for r in samples}
    for i, noisy_row in enumerate(noisy[:5]):
        print(f"\n[{i+1}] NOISY: {noisy_row['text']}")
        print(f"     label: {noisy_row['label']} (in valid set: {'YES' if noisy_row['label'] in label_set else 'NO'})")

    # Verify all labels are valid (label-preserving means label stays one of the 5 valid labels)
    # The noise augmentor copies the label from the original row — it never modifies it.
    valid_labels = {r["label"] for r in samples}
    bad = [r for r in noisy if r["label"] not in LABEL_NAMES]
    if bad:
        print(f"\n[FAIL] {len(bad)} noisy rows have invalid labels!")
        raise AssertionError(f"Label corruption: {bad[:2]}")
    print(f"\n[PASS] All {len(noisy)} noisy rows have valid labels. Label-preservation invariant holds.")

    # ---- D11 heavy-mode smoke test ----
    print("\n=== D11 heavy-mode test ===\n")
    heavy = add_noise_to_pool_heavy(samples, fraction=1.0, seed=142, word_corrupt_prob=0.70)
    print(f"Generated {len(heavy)} heavy-noise rows from {len(samples)} originals")
    for i, hr in enumerate(heavy[:5]):
        print(f"\n[{i+1}] HEAVY: {hr['text']}")
        print(f"     label: {hr['label']}  source: {hr['source']}")
        # Estimate corruption density
        orig_words = samples[i % len(samples)]["text"].split()
        new_words = hr["text"].split()
        changed = sum(1 for a, b in zip(orig_words, new_words) if a != b)
        if orig_words:
            pct = changed / len(orig_words) * 100
            print(f"     approx word-level corruption: {changed}/{len(orig_words)} = {pct:.0f}%")

    bad_heavy = [r for r in heavy if r["label"] not in LABEL_NAMES]
    if bad_heavy:
        print(f"\n[FAIL] {len(bad_heavy)} heavy rows have invalid labels!")
        raise AssertionError(f"Label corruption in heavy mode: {bad_heavy[:2]}")
    print(f"\n[PASS] All {len(heavy)} heavy-noise rows have valid labels. D11 invariant holds.")
