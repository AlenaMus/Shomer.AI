"""Diagnose what drives poor_spelling and children_mistakes slice gaps.

Characterizes:
1. Label-level breakdown within each slice (which true labels fail most)
2. Linguistic feature profile of the slice texts vs training data
3. Kid-register coverage in training data
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parents[2]
eval_path = ROOT / "data" / "stylistic_eval.jsonl"
train_path = ROOT / "data" / "train.jsonl"

eval_rows = []
with open(eval_path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            eval_rows.append(json.loads(line))

train_rows = []
with open(train_path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            train_rows.append(json.loads(line))

# ---- Feature analysis helpers ----

def count_final_form_errors(text: str) -> int:
    """Count words ending in medial form where final expected (e.g. ending in מ instead of ם)."""
    medial_at_end = set("מנכפצ")
    count = 0
    for word in text.split():
        word_strip = word.rstrip("!?.,;:")
        if word_strip and word_strip[-1] in medial_at_end:
            count += 1
    return count

def count_phonetic_substitutions(text: str) -> int:
    """Count likely phonetic substitutions (ת→ט, ה→א, etc.)"""
    # Check for common kid substitutions
    patterns = ["טמול", "אטמ", "אטה", "טמיד", "מא ", " מא", "איה", "פיצע", "מסחק", "מסאו",
                "בגדימ", "לכא", "אתנ", "סחקו", "ספאר", "סאפר"]
    count = 0
    for p in patterns:
        if p in text:
            count += 1
    return count

def fraction_non_heb(text: str) -> float:
    """Fraction of characters that are non-Hebrew (proxy for code-switching)."""
    heb_chars = sum(1 for c in text if "א" <= c <= "ת")
    total_alpha = sum(1 for c in text if c.isalpha())
    if total_alpha == 0:
        return 0.0
    return 1 - heb_chars / total_alpha

def avg_word_length(text: str) -> float:
    words = text.split()
    if not words:
        return 0.0
    return sum(len(w) for w in words) / len(words)

# ---- Analyze slices ----

for style in ["poor_spelling", "children_mistakes"]:
    style_rows = [r for r in eval_rows if r.get("style") == style]
    print(f"\n{'='*70}")
    print(f"STYLE: {style}  ({len(style_rows)} total)")

    lbl_dist = Counter(r["label"] for r in style_rows)
    print(f"Label distribution: {dict(lbl_dist)}")

    # Feature profile
    all_final = sum(count_final_form_errors(r["text"]) for r in style_rows)
    all_phonetic = sum(count_phonetic_substitutions(r["text"]) for r in style_rows)
    avg_wl = sum(avg_word_length(r["text"]) for r in style_rows) / len(style_rows)
    print(f"\nFeature profile:")
    print(f"  Avg words ending in medial form (per sentence): {all_final/len(style_rows):.2f}")
    print(f"  Avg phonetic sub markers (per sentence): {all_phonetic/len(style_rows):.2f}")
    print(f"  Avg word length (chars): {avg_wl:.2f}")

    # Per-label breakdown
    print(f"\nPer-label feature breakdown:")
    for lbl in ["non_offensive", "abusive", "hate", "violence", "pornographic"]:
        lbl_rows = [r for r in style_rows if r["label"] == lbl]
        if not lbl_rows:
            continue
        fin = sum(count_final_form_errors(r["text"]) for r in lbl_rows) / len(lbl_rows)
        phon = sum(count_phonetic_substitutions(r["text"]) for r in lbl_rows) / len(lbl_rows)
        wl = sum(avg_word_length(r["text"]) for r in lbl_rows) / len(lbl_rows)
        print(f"  {lbl} (n={len(lbl_rows)}): final_form_errs={fin:.2f} phonetic={phon:.2f} avg_word_len={wl:.2f}")

# ---- Compare to training data kid-register ----
print(f"\n{'='*70}")
print("TRAINING DATA — Kid-register vs clean profile")

kid_train = [r for r in train_rows if "kids" in r.get("source", "")]
clean_train = [r for r in train_rows if r.get("source") == "sinalab"]

print(f"Kid-register train rows: {len(kid_train)}")
print(f"Clean SinaLab train rows: {len(clean_train)}")

kid_by_label = Counter(r["label"] for r in kid_train)
print(f"\nKid train by label: {dict(kid_by_label)}")

# What fraction of offensive kid-register rows have final-form errors?
for lbl in ["abusive", "hate", "violence"]:
    lbl_kid = [r for r in kid_train if r["label"] == lbl]
    if lbl_kid:
        fin_avg = sum(count_final_form_errors(r["text"]) for r in lbl_kid) / len(lbl_kid)
        phon_avg = sum(count_phonetic_substitutions(r["text"]) for r in lbl_kid) / len(lbl_kid)
        print(f"  {lbl} kids (n={len(lbl_kid)}): avg_final_form={fin_avg:.2f} avg_phonetic={phon_avg:.2f}")

# Compare to what the slices look like
print(f"\n-- poor_spelling offensive rows: what kids train shows --")
ps_abusive = [r for r in eval_rows if r.get("style") == "poor_spelling" and r["label"] == "abusive"]
fin_ps = sum(count_final_form_errors(r["text"]) for r in ps_abusive) / max(len(ps_abusive), 1)
phon_ps = sum(count_phonetic_substitutions(r["text"]) for r in ps_abusive) / max(len(ps_abusive), 1)
print(f"  poor_spelling abusive (n={len(ps_abusive)}): avg_final_form={fin_ps:.2f} avg_phonetic={phon_ps:.2f}")
for r in ps_abusive[:4]:
    print(f"    {r['text'][:100]}")

# Count how many training abusive kids rows have these patterns
kid_abusive = [r for r in kid_train if r["label"] == "abusive"]
print(f"\n  kid_train abusive (n={len(kid_abusive)}) — sample:")
for r in kid_abusive[:4]:
    print(f"    {r['text'][:100]}")
