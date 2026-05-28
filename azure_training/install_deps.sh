#!/usr/bin/env bash
# install_deps.sh — Install PyTorch + Unsloth + training stack on the T4 VM.
# Run once after setup_vm.sh completes.
set -e

export PATH="$HOME/.local/bin:$PATH"

echo "[1/5] Upgrading pip..."
python3 -m pip install --upgrade pip setuptools wheel --quiet

echo "[2/5] Installing PyTorch 2.3 (CUDA 12.1)..."
python3 -m pip install \
    torch==2.3.0 \
    torchvision==0.18.0 \
    torchaudio==2.3.0 \
    --index-url https://download.pytorch.org/whl/cu121 \
    --quiet

echo "[3/5] Installing Unsloth (PyPI)..."
# Install from PyPI — simpler dep graph, no git build overhead
python3 -m pip install unsloth --quiet || {
    echo "[3/5] WARNING: Unsloth PyPI install failed — training will use vanilla HuggingFace (slower but correct)."
}

echo "[4/5] Installing training stack..."
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

echo "[5/5] Verifying GPU + CUDA..."
python3 - <<'PYEOF'
import torch
assert torch.cuda.is_available(), "CUDA not available!"
name = torch.cuda.get_device_name(0)
vram = torch.cuda.get_device_properties(0).total_memory / 1024**3
sm   = torch.cuda.get_device_properties(0).major
print(f"  GPU   : {name}")
print(f"  VRAM  : {vram:.1f} GB")
print(f"  sm    : sm_{sm}x")
print(f"  FP16  : supported")
print(f"  BF16  : {'supported' if sm >= 8 else 'NOT supported (expected for T4)'}")
print("  CUDA  : OK")
PYEOF

echo ""
echo "============================================================"
echo "  VM setup complete — ready to train!"
echo "  Run: bash ~/albedo/azure_training/run_all_training.sh"
echo "============================================================"
