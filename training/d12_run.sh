#!/usr/bin/env bash
# D12 retrain runner — kid-style misspelling/slang augmentation.
# Stages are guarded: a failure aborts before the next stage so we never
# train/evaluate on stale data.
set -uo pipefail

REPO=/mnt/c/AIDevelopmentCourse/Shomer.AI
source ~/shomer-training-venv/bin/activate

echo "=== PREFLIGHT $(date -u +%H:%M:%S) ==="
python -c "import datasketch" 2>/dev/null && echo "datasketch OK" || { echo "installing datasketch"; pip install -q datasketch || { echo "DATASKETCH_INSTALL_FAILED"; exit 10; }; }
python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())" || { echo "TORCH_IMPORT_FAILED"; exit 10; }
cd "$REPO" || { echo "REPO_CD_FAILED"; exit 10; }
if [ -f training/data/interim/synth_kids_noised_d12.jsonl ]; then
  echo "D12 source rows: $(wc -l < training/data/interim/synth_kids_noised_d12.jsonl)"
else
  echo "D12_FILE_MISSING"; exit 10
fi

echo "=== PREPARE DATA $(date -u +%H:%M:%S) ==="
python training/prepare_data_dictabert.py || { echo "PREPARE_FAILED"; exit 11; }

echo "=== VALIDATE SPLITS $(date -u +%H:%M:%S) ==="
python training/scripts/validate_splits.py || { echo "VALIDATE_FAILED"; exit 12; }

echo "=== TRAIN + EVAL $(date -u +%H:%M:%S) ==="
python training/train_dictabert.py || { echo "TRAIN_FAILED"; exit 13; }

echo "=== DONE $(date -u +%H:%M:%S) ==="
