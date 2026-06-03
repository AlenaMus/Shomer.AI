"""QLoRA fine-tune via Unsloth + TRL SFTTrainer.

Run after prepare_data.py has produced data/train.jsonl and data/validation.jsonl
(or data/val.jsonl — both names handled).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml
from datasets import load_dataset
from transformers import TrainingArguments
from trl import SFTTrainer
from unsloth import FastLanguageModel
from unsloth.chat_templates import train_on_responses_only


def find_split(data_dir: Path, candidates: list[str]) -> Path | None:
    for name in candidates:
        p = data_dir / f"{name}.jsonl"
        if p.exists():
            return p
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/train.yaml")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    data_dir = Path(cfg["dataset"]["data_dir"])

    train_path = find_split(data_dir, ["train"])
    val_path = find_split(data_dir, ["validation", "val", "valid", "dev"])
    if train_path is None:
        raise SystemExit(f"No train.jsonl in {data_dir}. Run prepare_data.py first.")

    print(f"Loading base model: {cfg['base_model']}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=cfg["base_model"],
        max_seq_length=cfg["max_seq_length"],
        load_in_4bit=cfg["load_in_4bit"],
        dtype=None,
    )

    model = FastLanguageModel.get_peft_model(
        model,
        r=cfg["lora"]["r"],
        lora_alpha=cfg["lora"]["alpha"],
        lora_dropout=cfg["lora"]["dropout"],
        target_modules=cfg["lora"]["target_modules"],
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=cfg["training"]["seed"],
    )

    def format_chat(example):
        return {"text": tokenizer.apply_chat_template(
            example["messages"], tokenize=False, add_generation_prompt=False
        )}

    train_ds = load_dataset("json", data_files=str(train_path), split="train").map(format_chat)
    eval_ds = None
    if val_path is not None:
        eval_ds = load_dataset("json", data_files=str(val_path), split="train").map(format_chat)

    targs = TrainingArguments(
        output_dir=cfg["training"]["output_dir"],
        num_train_epochs=cfg["training"]["num_train_epochs"],
        per_device_train_batch_size=cfg["training"]["per_device_train_batch_size"],
        gradient_accumulation_steps=cfg["training"]["gradient_accumulation_steps"],
        learning_rate=cfg["training"]["learning_rate"],
        lr_scheduler_type=cfg["training"]["lr_scheduler_type"],
        warmup_ratio=cfg["training"]["warmup_ratio"],
        weight_decay=cfg["training"]["weight_decay"],
        logging_steps=cfg["training"]["logging_steps"],
        save_steps=cfg["training"]["save_steps"],
        eval_steps=cfg["training"]["eval_steps"] if eval_ds is not None else None,
        eval_strategy="steps" if eval_ds is not None else "no",
        bf16=cfg["training"]["bf16"],
        seed=cfg["training"]["seed"],
        report_to="none",
        save_total_limit=2,
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        dataset_text_field="text",
        max_seq_length=cfg["max_seq_length"],
        packing=False,
        args=targs,
    )

    trainer = train_on_responses_only(
        trainer,
        instruction_part="<|im_start|>user\n",
        response_part="<|im_start|>assistant\n",
    )

    print("Starting training...")
    trainer.train()

    out_dir = cfg["training"]["output_dir"]
    print(f"Saving adapter to {out_dir}")
    model.save_pretrained(out_dir)
    tokenizer.save_pretrained(out_dir)
    print("Done.")


if __name__ == "__main__":
    main()
