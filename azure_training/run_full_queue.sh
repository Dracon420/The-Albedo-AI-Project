#!/usr/bin/env bash
# run_full_queue.sh — Full Albedo training queue for Azure T4.
# Runs automatically after R3 completes. All steps are idempotent (skipped if outputs exist).
#
# Queue:
#   1. Merge + GGUF: R3 Cortana + JARVIS (clean_merge_r3.sh)
#   2. Generate all datasets (Gemini API)
#   3. Merge new datasets with existing ones
#   4. Train JARVIS-Tech (7B Instruct base + tech dataset)
#   5. Merge + GGUF JARVIS-Tech
#   6. Train 3B Cortana persona LoRA
#   7. Merge + GGUF 3B Cortana
#   8. Train 3B JARVIS persona LoRA
#   9. Merge + GGUF 3B JARVIS
#  10. Train R4 Cortana (rank 64, 15 epochs, 2048 seq)
#  11. Merge + GGUF R4 Cortana
#  12. Train R4 JARVIS (rank 64, 15 epochs)
#  13. Merge + GGUF R4 JARVIS
#  14. Cleanup old R2 GGUFs, print download commands
#
# Usage:
#   GEMINI_API_KEY="AIza..." nohup bash /data/run_full_queue.sh > ~/albedo/queue.log 2>&1 &
#
set -e
export PATH="$HOME/.local/bin:/usr/bin:/usr/local/bin:$PATH"
export HF_HOME=/data/hf_cache
export PYTHONPATH=/data

QUANTIZE=/data/llama_cpp_full/build/bin/llama-quantize
SCRIPTS=/data
LOG_PREFIX="[QUEUE]"

log() { echo "$LOG_PREFIX $(date '+%H:%M:%S') — $*"; }

# ── Helpers ───────────────────────────────────────────────────────────────────

merge_and_gguf() {
    local persona="$1"          # e.g. cortana, jarvis, jarvis_tech_r1, cortana_3b
    local adapter_dir="$2"      # e.g. /data/outputs/lora_adapter_cortana_r4
    local label="$3"            # e.g. cortana-r4, jarvis-tech, cortana-3b
    local clean_dir="/data/outputs/merged_clean/${label}"
    local gguf_dir="/data/outputs/gguf/${label}"
    local f16="${gguf_dir}/model-f16.gguf"
    local q4="${gguf_dir}/model-q4_k_m.gguf"

    mkdir -p "$gguf_dir"

    if [ -f "$q4" ]; then
        log "${label}: Q4_K_M already exists — skip."
        return
    fi

    if [ ! -d "$adapter_dir" ]; then
        log "${label}: Adapter not found at ${adapter_dir} — skip."
        return
    fi

    log "${label}: Merging LoRA onto clean FP16 base..."
    python3 << PYEOF
import torch, gc, os
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel
from pathlib import Path

os.environ["HF_HOME"] = "/data/hf_cache"
BASE = "Qwen/Qwen2.5-7B-Instruct"

# 3B models need a different base
adapter = "$adapter_dir"
label   = "$label"
if "3b" in label.lower():
    BASE = "Qwen/Qwen2.5-3B-Instruct"

clean_dir = "$clean_dir"
Path(clean_dir).mkdir(parents=True, exist_ok=True)

print(f"Loading {BASE} in FP16 on CPU...")
model = AutoModelForCausalLM.from_pretrained(
    BASE, torch_dtype=torch.float16, device_map="cpu", trust_remote_code=True
)
model = PeftModel.from_pretrained(model, adapter)
print("Merging LoRA...")
model = model.merge_and_unload()
model.save_pretrained(clean_dir, safe_serialization=True, max_shard_size="4GB")
tokenizer = AutoTokenizer.from_pretrained(adapter, trust_remote_code=True)
tokenizer.save_pretrained(clean_dir)
print(f"Saved to {clean_dir}")
del model; gc.collect()
PYEOF

    log "${label}: Converting to F16 GGUF..."
    cd /data/llama_cpp_full
    python3 convert_hf_to_gguf.py "$clean_dir" --outfile "$f16" --outtype f16

    # Free merged weights immediately
    rm -rf "$clean_dir"
    log "${label}: F16 GGUF: $(du -sh $f16 | cut -f1) — merged weights freed"

    log "${label}: Quantizing to Q4_K_M..."
    "$QUANTIZE" "$f16" "$q4" Q4_K_M
    rm -f "$f16"
    log "${label}: Done — Q4_K_M: $(du -sh $q4 | cut -f1)"
}

merge_datasets() {
    # Merge two JSONL files into a combined file (skip if combined already exists)
    local out="$1"; shift
    local inputs=("$@")
    if [ -f "$out" ]; then
        log "$(basename $out) already merged — skip."
        return
    fi
    log "Merging datasets into $(basename $out)..."
    > "$out"
    for f in "${inputs[@]}"; do
        if [ -f "$f" ]; then
            cat "$f" >> "$out"
            log "  + $(basename $f): $(wc -l < $f) examples"
        fi
    done
    log "  Total: $(wc -l < $out) examples in $(basename $out)"
}

# ── Wait for R3 to finish ─────────────────────────────────────────────────────

log "Waiting for R3 training to complete..."
while pgrep -f "train_r3.py" > /dev/null 2>&1 || pgrep -f "run_r3.sh" > /dev/null 2>&1; do
    sleep 30
done
log "R3 training complete."
sleep 5  # let filesystem settle

# ── Step 1: Merge + GGUF R3 ──────────────────────────────────────────────────

log "=== Step 1: R3 Merge + GGUF ==="
merge_and_gguf "cortana" "/data/outputs/lora_adapter_cortana_r3" "cortana-r3"
merge_and_gguf "jarvis"  "/data/outputs/lora_adapter_jarvis_r3"  "jarvis-r3"

# ── Step 2: Generate datasets ─────────────────────────────────────────────────

log "=== Step 2: Generate all datasets via Gemini ==="
if [ -z "$GEMINI_API_KEY" ]; then
    log "ERROR: GEMINI_API_KEY not set — skipping dataset generation."
    log "Set it with: export GEMINI_API_KEY='AIza...'"
    log "Then re-run from Step 2 onward."
else
    if [ ! -f "/data/jarvis_tech_dataset_v1.jsonl" ] || \
       [ $(wc -l < /data/jarvis_tech_dataset_v1.jsonl 2>/dev/null || echo 0) -lt 50 ]; then
        log "Running generate_all_datasets.py..."
        GEMINI_API_KEY="$GEMINI_API_KEY" python3 "$SCRIPTS/generate_all_datasets.py"
    else
        log "Datasets already generated — skip."
    fi
fi

# ── Step 3: Merge datasets ────────────────────────────────────────────────────

log "=== Step 3: Merge datasets ==="
merge_datasets "/data/albedo_dataset_v5_combined.jsonl" \
    "/data/albedo_dataset_v4.jsonl" "/data/albedo_dataset_v5.jsonl"

merge_datasets "/data/jarvis_dataset_v4_combined.jsonl" \
    "/data/jarvis_dataset_v3.jsonl" "/data/jarvis_dataset_v4.jsonl"

# ── Step 4: Train JARVIS-Tech ─────────────────────────────────────────────────

log "=== Step 4: JARVIS-Tech LoRA training ==="
if [ ! -d "/data/outputs/lora_adapter_jarvis_tech_r1" ]; then
    python3 "$SCRIPTS/train_jarvis_tech.py"
else
    log "JARVIS-Tech adapter already exists — skip."
fi

# ── Step 5: Merge + GGUF JARVIS-Tech ─────────────────────────────────────────

log "=== Step 5: JARVIS-Tech Merge + GGUF ==="
merge_and_gguf "jarvis_tech" "/data/outputs/lora_adapter_jarvis_tech_r1" "jarvis-tech"

# ── Step 6-7: 3B Cortana ─────────────────────────────────────────────────────

log "=== Step 6: 3B Cortana LoRA ==="
if [ ! -d "/data/outputs/lora_adapter_cortana_3b" ]; then
    PERSONA=cortana python3 "$SCRIPTS/train_3b.py"
else
    log "3B Cortana adapter exists — skip."
fi

log "=== Step 7: 3B Cortana Merge + GGUF ==="
merge_and_gguf "cortana_3b" "/data/outputs/lora_adapter_cortana_3b" "cortana-3b"

# ── Step 8-9: 3B JARVIS ──────────────────────────────────────────────────────

log "=== Step 8: 3B JARVIS LoRA ==="
if [ ! -d "/data/outputs/lora_adapter_jarvis_3b" ]; then
    PERSONA=jarvis python3 "$SCRIPTS/train_3b.py"
else
    log "3B JARVIS adapter exists — skip."
fi

log "=== Step 9: 3B JARVIS Merge + GGUF ==="
merge_and_gguf "jarvis_3b" "/data/outputs/lora_adapter_jarvis_3b" "jarvis-3b"

# ── Step 10-11: R4 Cortana ────────────────────────────────────────────────────

log "=== Step 10: R4 Cortana (rank 64, 15 epochs, 2048 seq) ==="
if [ ! -d "/data/outputs/lora_adapter_cortana_r4" ]; then
    PERSONA=cortana python3 "$SCRIPTS/train_r4.py"
else
    log "R4 Cortana adapter exists — skip."
fi

log "=== Step 11: R4 Cortana Merge + GGUF ==="
merge_and_gguf "cortana_r4" "/data/outputs/lora_adapter_cortana_r4" "cortana-r4"

# ── Step 12-13: R4 JARVIS ─────────────────────────────────────────────────────

log "=== Step 12: R4 JARVIS (rank 64, 15 epochs) ==="
if [ ! -d "/data/outputs/lora_adapter_jarvis_r4" ]; then
    PERSONA=jarvis python3 "$SCRIPTS/train_r4.py"
else
    log "R4 JARVIS adapter exists — skip."
fi

log "=== Step 13: R4 JARVIS Merge + GGUF ==="
merge_and_gguf "jarvis_r4" "/data/outputs/lora_adapter_jarvis_r4" "jarvis-r4"

# ── Step 14: Cleanup + Summary ────────────────────────────────────────────────

log "=== Step 14: Cleanup old R2 GGUFs ==="
# R2 models are superseded by R4 — delete from VM (you already downloaded them)
for old in cortana-8b jarvis-8b; do
    if [ -d "/data/outputs/gguf/$old" ]; then
        rm -rf "/data/outputs/gguf/$old"
        log "Removed $old (R2, superseded by R4)"
    fi
done

log ""
log "=== ALL TRAINING COMPLETE ==="
log ""
log "GGUFs ready for download:"
find /data/outputs/gguf -name "*.gguf" | sort | while read f; do
    echo "  $(du -sh $f | cut -f1)  $f"
done

log ""
log "Download commands (run from your local machine):"
echo "mkdir -p outputs/gguf_azure/{cortana-r3,jarvis-r3,jarvis-tech,cortana-3b,jarvis-3b,cortana-r4,jarvis-r4}"
echo "scp -r azureuser@20.42.21.217:/data/outputs/gguf/cortana-r3/ outputs/gguf_azure/"
echo "scp -r azureuser@20.42.21.217:/data/outputs/gguf/jarvis-r3/  outputs/gguf_azure/"
echo "scp -r azureuser@20.42.21.217:/data/outputs/gguf/jarvis-tech/ outputs/gguf_azure/"
echo "scp -r azureuser@20.42.21.217:/data/outputs/gguf/cortana-3b/  outputs/gguf_azure/"
echo "scp -r azureuser@20.42.21.217:/data/outputs/gguf/jarvis-3b/   outputs/gguf_azure/"
echo "scp -r azureuser@20.42.21.217:/data/outputs/gguf/cortana-r4/  outputs/gguf_azure/"
echo "scp -r azureuser@20.42.21.217:/data/outputs/gguf/jarvis-r4/   outputs/gguf_azure/"
log ""
log "DEALLOCATE THE VM after downloading. az vm deallocate --name <vm> --resource-group <rg>"
