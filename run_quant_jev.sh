#!/usr/bin/env bash
set -euo pipefail
export PYTHONUNBUFFERED=1
export TOKENIZERS_PARALLELISM=false
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export HF_HOME=/workspace/huggingface

echo "=== System GPU ==="
nvidia-smi

echo "=== Starting 4-Bit Quantized OpenJev Training ==="
python -u train_quantized_openjev.py
echo "=== Finished 4-Bit Quantized OpenJev ==="
