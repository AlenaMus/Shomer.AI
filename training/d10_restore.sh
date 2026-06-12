#!/usr/bin/env bash
# Restore D10: D12 source file has been renamed away, so prepare_data's
# warn-if-missing guard skips it and regenerates the D10 splits. Deterministic
# (seed=42), so this reproduces the D10 model + data exactly.
set -uo pipefail

REPO=/mnt/c/AIDevelopmentCourse/Shomer.AI
source ~/shomer-training-venv/bin/activate

echo "=== PREFLIGHT $(date -u +%H:%M:%S) ==="
python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())" || { echo "TORCH_IMPORT_FAILED"; exit 10; }
cd "$REPO" || { echo "REPO_CD_FAILED"; exit 10; }
if [ -f training/data/interim/synth_kids_noised_d12.jsonl ]; then
  echo "WARN: D12 file still present — revert will NOT be clean"; exit 10
else
  echo "D12 source absent (good) — regenerating D10 splits"
fi

echo "=== PREPARE DATA $(date -u +%H:%M:%S) ==="
python training/prepare_data_dictabert.py || { echo "PREPARE_FAILED"; exit 11; }

echo "=== VALIDATE SPLITS $(date -u +%H:%M:%S) ==="
python training/scripts/validate_splits.py || { echo "VALIDATE_FAILED"; exit 12; }

echo "=== TRAIN + EVAL $(date -u +%H:%M:%S) ==="
python training/train_dictabert.py || { echo "TRAIN_FAILED"; exit 13; }

echo "=== DONE $(date -u +%H:%M:%S) ==="
