"""Convert the SinaLab/Offensive-Hebrew dataset into instruction JSONL for SFT.

Each row becomes a chat message list:
    [{"role": "system", "content": <classifier system prompt>},
     {"role": "user",   "content": "סווג את הטקסט הבא: <tweet>"},
     {"role": "assistant", "content": '{"is_offensive": bool, "category": str, "confidence": 1.0}'}]
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import yaml
from datasets import load_dataset

CATEGORIES = ["abusive", "hate", "violence", "pornographic"]


def row_to_label(row: dict, label_cols: list[str]) -> tuple[bool, str]:
    """Pick the dominant offensive category, or non_offensive if none."""
    flagged = [c for c in label_cols if int(row.get(c, 0)) == 1]
    if not flagged:
        return False, "non_offensive"
    # Priority order matches the paper: hate > violence > abusive > pornographic.
    for c in ["hate", "violence", "abusive", "pornographic"]:
        if c in flagged:
            return True, c
    return True, flagged[0]


def format_example(text: str, is_offensive: bool, category: str, system_prompt: str) -> dict:
    assistant_json = json.dumps(
        {"is_offensive": is_offensive, "category": category, "confidence": 1.0},
        ensure_ascii=False,
    )
    return {
        "messages": [
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": f'סווג את הטקסט הבא: "{text}"'},
            {"role": "assistant", "content": assistant_json},
        ]
    }


def write_jsonl(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def balance_subset(examples: list[dict], seed: int = 42) -> list[dict]:
    """Keep all offensive examples and downsample non-offensive to ~equal count."""
    offensive = [e for e in examples if e["_is_offensive"]]
    non_off = [e for e in examples if not e["_is_offensive"]]
    target_non = min(len(non_off), int(len(offensive) * 1.1))
    rng = random.Random(seed)
    rng.shuffle(non_off)
    out = offensive + non_off[:target_non]
    rng.shuffle(out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/train.yaml")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    ds_cfg = cfg["dataset"]
    sys_prompt = cfg["system_prompt"]

    print(f"Loading dataset: {ds_cfg['name']}")
    ds = load_dataset(ds_cfg["name"])
    print({split: len(ds[split]) for split in ds.keys()})

    data_dir = Path(ds_cfg["data_dir"])

    for split in ds.keys():
        raw_rows = []
        for row in ds[split]:
            text = row.get(ds_cfg["text_column"]) or row.get("tweet") or row.get("Tweet")
            if not text:
                continue
            is_off, category = row_to_label(row, ds_cfg["label_columns"])
            rec = format_example(text, is_off, category, sys_prompt)
            rec["_is_offensive"] = is_off
            raw_rows.append(rec)

        if ds_cfg.get("use_balanced_subset", True) and split == "train":
            raw_rows = balance_subset(raw_rows)

        for r in raw_rows:
            r.pop("_is_offensive", None)

        out_path = data_dir / f"{split}.jsonl"
        write_jsonl(raw_rows, out_path)
        print(f"  wrote {len(raw_rows):>6} examples -> {out_path}")

    print("Done.")


if __name__ == "__main__":
    main()
