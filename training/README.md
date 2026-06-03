# Training pipeline

Fine-tune a Hebrew-capable base LLM with QLoRA on [SinaLab/Offensive-Hebrew](https://huggingface.co/SinaLab/Offensive-Hebrew), then export to GGUF for Ollama.

## Why WSL2

Unsloth + bitsandbytes is Linux-first. CUDA passthrough from Windows to WSL2 Ubuntu works well — install the NVIDIA Windows driver, then `nvidia-smi` inside WSL2 should show your GPU.

## Setup (one time)

```bash
# in WSL2 Ubuntu
sudo apt update && sudo apt install -y python3.11 python3.11-venv build-essential git
cd /mnt/c/Users/Dima/Projects/offensive-hebrew/training
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# llama.cpp for GGUF conversion
cd ..
git clone https://github.com/ggerganov/llama.cpp.git ../llama.cpp
pip install -r ../../llama.cpp/requirements.txt
```

## Run the pipeline

```bash
huggingface-cli login           # if base model is gated (DictaLM is not, Qwen is not)
python prepare_data.py
python train_lora.py --config configs/train.yaml
python evaluate.py --adapter outputs/offensive-hebrew-lora
python export_gguf.py --adapter outputs/offensive-hebrew-lora \
                      --out ../server/offensive-hebrew.gguf \
                      --llama-cpp-dir ../../llama.cpp
```

## What good looks like

- `evaluate.py` reports macro-F1. Target ≥ 0.70 on the balanced split. If lower:
  - Try the full imbalanced set (`use_balanced_subset: false` in `configs/train.yaml`).
  - Try DictaLM 2.0: `base_model: "dicta-il/dictalm2.0-instruct"`.
  - Train more epochs (5–8) with the same learning rate.

## VRAM notes

QLoRA 4-bit on 7B fits in ~9 GB with `batch_size=2, seq_len=512`. If you OOM:
- Drop `per_device_train_batch_size` to 1, bump `gradient_accumulation_steps` to 8.
- Drop `max_seq_length` to 384 (tweets are short).
- Disable `bf16` and use `fp16` if your GPU pre-dates Ampere (Turing).
