#!/usr/bin/env bash
# install_stack.sh — Install HF training stack with pip cache on /data
set -e
export PATH="$HOME/.local/bin:$PATH"
export HF_HOME=/data/hf_cache
export PIP_CACHE_DIR=/data/pip_cache

echo "[4/5] Installing training stack (transformers, trl, peft, bitsandbytes)..."
python3 -m pip install \
    "transformers==4.44.2" \
    "datasets==2.20.0" \
    "trl==0.10.1" \
    "peft==0.12.0" \
    "accelerate==0.33.0" \
    "bitsandbytes==0.43.3" \
    sentencepiece \
    protobuf \
    huggingface_hub \
    --quiet

echo "[5/5] Verifying GPU + PyTorch..."
python3 - <<'PYEOF'
import torch
assert torch.cuda.is_available(), "CUDA not available!"
name = torch.cuda.get_device_name(0)
vram = torch.cuda.get_device_properties(0).total_memory / 1024**3
print(f"  GPU  : {name}")
print(f"  VRAM : {vram:.1f} GB")
print("  CUDA : OK")
PYEOF

echo ""
echo "============================================================"
echo "  SETUP COMPLETE - VM ready to train!"
echo "  Run: bash ~/albedo/azure_training/run_all_training.sh"
echo "============================================================"
