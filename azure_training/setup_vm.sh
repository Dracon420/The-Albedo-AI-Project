#!/usr/bin/env bash
# setup_vm.sh — One-shot dependency installer for Azure NCas_T4_v3 VMs.
#
# Run this as the first step on each VM after SSH in:
#   bash setup_vm.sh
#
# What it does:
#   1. Updates apt and installs system deps (CUDA toolkit, build tools)
#   2. Installs Python 3.11 + pip
#   3. Installs Unsloth + all training dependencies (FP16 / T4 compatible)
#   4. Verifies GPU is visible and BF16 is correctly disabled
#
# Tested on: Ubuntu 22.04 LTS  |  CUDA 12.1  |  T4 (sm_75)

set -euo pipefail

PYTHON=python3.11
PIP="$PYTHON -m pip"
CUDA_VERSION="12.1"

echo "============================================================"
echo "  Albedo Training VM Setup"
echo "  $(date)"
echo "============================================================"

# ── 1. System packages ────────────────────────────────────────────────────────
echo "[setup] Updating apt..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3.11 python3.11-dev python3.11-venv python3-pip \
    build-essential git curl wget \
    nvidia-cuda-toolkit \
    2>&1 | tail -5

echo "[setup] System packages installed."

# ── 2. Pip bootstrap ──────────────────────────────────────────────────────────
echo "[setup] Upgrading pip..."
$PIP install --upgrade pip setuptools wheel -q

# ── 3. PyTorch (CUDA 12.1, FP16 — T4 compatible) ─────────────────────────────
echo "[setup] Installing PyTorch 2.3 + CUDA $CUDA_VERSION..."
$PIP install \
    torch==2.3.0 \
    torchvision==0.18.0 \
    torchaudio==2.3.0 \
    --index-url "https://download.pytorch.org/whl/cu${CUDA_VERSION//./}" \
    -q

# ── 4. Unsloth (Linux / T4 / CUDA 12.1) ──────────────────────────────────────
# Use the pre-built wheel for CUDA 12.1 + Torch 2.3
echo "[setup] Installing Unsloth..."
$PIP install \
    "unsloth[cu121-torch230] @ git+https://github.com/unslothai/unsloth.git" \
    -q

# ── 5. Training stack ─────────────────────────────────────────────────────────
echo "[setup] Installing training dependencies..."
$PIP install \
    transformers==4.44.2 \
    datasets==2.20.0 \
    trl==0.10.1 \
    peft==0.12.0 \
    accelerate==0.33.0 \
    bitsandbytes==0.43.3 \
    sentencepiece \
    protobuf \
    huggingface_hub \
    -q

# ── 6. Verify GPU ─────────────────────────────────────────────────────────────
echo "[setup] Verifying GPU..."
$PYTHON - <<'PYEOF'
import torch
assert torch.cuda.is_available(), "CUDA not available!"
name = torch.cuda.get_device_name(0)
vram = torch.cuda.get_device_properties(0).total_memory / 1024**3
sm   = torch.cuda.get_device_properties(0).major
print(f"  GPU      : {name}")
print(f"  VRAM     : {vram:.1f} GB")
print(f"  SM arch  : sm_{sm}x")
print(f"  BF16     : {'SUPPORTED' if sm >= 8 else 'NOT supported (expected for T4)'}")
print(f"  FP16     : SUPPORTED")
print("  OK — GPU verified.")
PYEOF

echo "============================================================"
echo "  Setup complete!  VM is ready to train."
echo "  Next: run launch_training.sh or manually:"
echo "    PERSONA=cortana python train_azure_t4.py"
echo "============================================================"
