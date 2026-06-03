"""Evaluate a trained LoRA adapter on the test split.

Computes macro-F1, per-class precision/recall, and a confusion matrix.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml
from sklearn.metrics import classification_report, confusion_matrix
from unsloth import FastLanguageModel

CATEGORIES = ["non_offensive", "abusive", "hate", "violence", "pornographic"]


def parse_json_label(text: str) -> str:
    """Pull the category out of a JSON-ish model response. Falls back to non_offensive."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return "non_offensive"
    try:
        obj = json.loads(match.group(0))
        cat = str(obj.get("category", "non_offensive")).lower().strip()
        return cat if cat in CATEGORIES else "non_offensive"
    except json.JSONDecodeError:
        return "non_offensive"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/train.yaml")
    ap.add_argument("--adapter", required=True, help="Path to saved LoRA adapter dir")
    ap.add_argument("--test-file", default="data/test.jsonl")
    ap.add_argument("--limit", type=int, default=0, help="Optional cap for fast iteration")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.adapter,
        max_seq_length=cfg["max_seq_length"],
        load_in_4bit=cfg["load_in_4bit"],
    )
    FastLanguageModel.for_inference(model)

    y_true, y_pred = [], []
    with open(args.test_file, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if args.limit and i >= args.limit:
                break
            row = json.loads(line)
            msgs = row["messages"]
            gold = json.loads(msgs[-1]["content"])["category"]

            prompt = tokenizer.apply_chat_template(
                msgs[:-1], tokenize=False, add_generation_prompt=True
            )
            inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
            out = model.generate(
                **inputs, max_new_tokens=64, do_sample=False, temperature=0.0,
                pad_token_id=tokenizer.eos_token_id,
            )
            decoded = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
            pred = parse_json_label(decoded)

            y_true.append(gold)
            y_pred.append(pred)
            if (i + 1) % 50 == 0:
                print(f"  evaluated {i+1} examples")

    print("\n=== Classification report ===")
    print(classification_report(y_true, y_pred, labels=CATEGORIES, zero_division=0, digits=3))

    print("=== Confusion matrix ===")
    cm = confusion_matrix(y_true, y_pred, labels=CATEGORIES)
    header = "          " + "  ".join(f"{c[:6]:>6}" for c in CATEGORIES)
    print(header)
    for row_lbl, row_vals in zip(CATEGORIES, cm):
        print(f"{row_lbl[:8]:>8}  " + "  ".join(f"{v:>6d}" for v in row_vals))


if __name__ == "__main__":
    main()
