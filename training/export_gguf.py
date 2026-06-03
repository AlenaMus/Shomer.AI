"""Merge the LoRA adapter into the base model, then convert to GGUF via llama.cpp.

Prerequisites:
  - The adapter directory contains adapter_config.json + adapter weights.
  - A local clone of llama.cpp at LLAMA_CPP_DIR (defaults to ../../llama.cpp).
  - llama.cpp's Python requirements installed:
      pip install -r llama.cpp/requirements.txt
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


def merge(adapter_dir: Path, merged_dir: Path) -> None:
    print(f"Loading adapter config from {adapter_dir}")
    import json
    cfg = json.loads((adapter_dir / "adapter_config.json").read_text(encoding="utf-8"))
    base = cfg["base_model_name_or_path"]
    print(f"Base model: {base}")

    print("Loading base model in fp16 ...")
    model = AutoModelForCausalLM.from_pretrained(base, torch_dtype="float16", device_map="cpu")
    tokenizer = AutoTokenizer.from_pretrained(base)

    print("Loading adapter ...")
    model = PeftModel.from_pretrained(model, str(adapter_dir))

    print("Merging adapter into base ...")
    model = model.merge_and_unload()

    merged_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(merged_dir), safe_serialization=True)
    tokenizer.save_pretrained(str(merged_dir))
    print(f"Merged model saved to {merged_dir}")


def convert_to_gguf(merged_dir: Path, out_file: Path, llama_cpp_dir: Path, quant: str) -> None:
    convert_script = llama_cpp_dir / "convert_hf_to_gguf.py"
    if not convert_script.exists():
        raise SystemExit(f"convert_hf_to_gguf.py not found at {convert_script}. Clone llama.cpp first.")

    out_file.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, str(convert_script), str(merged_dir),
        "--outfile", str(out_file),
        "--outtype", quant,
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"GGUF written to {out_file}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", required=True, help="Path to LoRA adapter dir")
    ap.add_argument("--out", required=True, help="Output .gguf path (e.g. ../server/offensive-hebrew.gguf)")
    ap.add_argument("--merged-dir", default="outputs/merged")
    ap.add_argument("--llama-cpp-dir", default=os.environ.get("LLAMA_CPP_DIR", "../../llama.cpp"))
    ap.add_argument("--quant", default="q5_k_m", help="GGUF quantization type (e.g. q4_k_m, q5_k_m, q8_0, f16)")
    ap.add_argument("--keep-merged", action="store_true")
    args = ap.parse_args()

    adapter_dir = Path(args.adapter)
    merged_dir = Path(args.merged_dir)
    out_file = Path(args.out)
    llama_cpp_dir = Path(args.llama_cpp_dir)

    merge(adapter_dir, merged_dir)
    convert_to_gguf(merged_dir, out_file, llama_cpp_dir, args.quant)

    if not args.keep_merged:
        shutil.rmtree(merged_dir, ignore_errors=True)
        print(f"Cleaned up {merged_dir}")


if __name__ == "__main__":
    main()
