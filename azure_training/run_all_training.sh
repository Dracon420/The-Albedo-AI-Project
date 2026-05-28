#!/usr/bin/env bash
# run_all_training.sh — Sequential training launcher for all 4 persona variants.
# Runs on the Azure T4 VM. Logs each job separately.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
TRAIN="$SCRIPT_DIR/train_azure_t4.py"
LOG_DIR="$REPO_DIR/logs"

# Use /data for model downloads and outputs (128 GB data disk)
export HF_HOME=/data/hf_cache
export TRANSFORMERS_CACHE=/data/hf_cache
export OUTPUT_DIR=/data/outputs
export PATH="$HOME/.local/bin:$PATH"

mkdir -p "$LOG_DIR" /data/outputs

nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null || true

run_job() {
    local label="$1"
    local persona="$2"
    local rank="$3"
    local epochs="$4"
    local batch="$5"
    local log="$LOG_DIR/train_${persona}_r${rank}_e${epochs}.log"

    echo ""
    echo "============================================================"
    echo "  JOB: $label"
    echo "  Persona=$persona | Rank=$rank | Epochs=$epochs | Batch=$batch"
    echo "  Log: $log"
    echo "  Started: $(date)"
    echo "============================================================"

    PERSONA="$persona" \
    LORA_RANK="$rank" \
    EPOCHS="$epochs" \
    BATCH_SIZE="$batch" \
    GRAD_ACCUM="${GRAD_ACCUM:-8}" \
    MAX_SEQ_LEN="${MAX_SEQ_LEN:-2048}" \
    OUTPUT_DIR="/data/outputs" \
    python3 "$TRAIN" 2>&1 | tee "$log"

    echo "  Finished: $(date)"
}

echo "============================================================"
echo "  Albedo T4 Full Training Run  $(date)"
echo "  4 jobs will run sequentially"
echo "============================================================"

# batch=1 + seq_len=1024 required for Qwen2.5-7B on T4:
# 152K vocab causes logits.float() to need 1.5 GB/batch at seq=1024
# grad_accum=16 gives effective batch of 16

# Job 1: Cortana primary (rank 32, 10 epochs)
GRAD_ACCUM=16 MAX_SEQ_LEN=1024 run_job "Cortana Primary" "cortana" "32" "10" "1"

# Job 2: JARVIS primary (rank 32, 10 epochs)
GRAD_ACCUM=16 MAX_SEQ_LEN=1024 run_job "JARVIS Primary" "jarvis" "32" "10" "1"

# Job 3: Cortana extended (rank 64, 15 epochs)
GRAD_ACCUM=16 MAX_SEQ_LEN=1024 run_job "Cortana Extended" "cortana" "64" "15" "1"

# Job 4: JARVIS extended (rank 64, 15 epochs)
GRAD_ACCUM=16 MAX_SEQ_LEN=1024 run_job "JARVIS Extended" "jarvis" "64" "15" "1"

echo ""
echo "============================================================"
echo "  ALL 4 TRAINING JOBS COMPLETE  $(date)"
ls -lh /data/outputs/gguf/ 2>/dev/null || echo "(no gguf dir yet)"
PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "VM_IP")
echo ""
echo "  Download to your local machine:"
echo "  scp -r azureuser@${PUBLIC_IP}:/data/outputs/gguf/ ./"
echo "============================================================"
