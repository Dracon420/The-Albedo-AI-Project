#!/usr/bin/env bash
# clean_merge_r3.sh — Merge Round 3 LoRA adapters onto clean FP16 base, then GGUF Q4_K_M.
set -e
export PATH="$HOME/.local/bin:/usr/bin:/usr/local/bin:$PATH"
export HF_HOME=/data/hf_cache

QUANTIZE=/data/llama_cpp_full/build/bin/llama-quantize

echo "=== Round 3 Clean Merge + GGUF Conversion ==="
echo "$(date)"
echo "RAM available: $(free -gh | grep Mem | awk '{print $7}')"

python3 << 'PYEOF'
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel
from pathlib import Path
import gc, os

os.environ["HF_HOME"] = "/data/hf_cache"
BASE = "Qwen/Qwen2.5-7B-Instruct"

for persona in ("cortana", "jarvis"):
    adapter_dir = f"/data/outputs/lora_adapter_{persona}_r3"
    clean_dir   = f"/data/outputs/merged_clean/{persona}-r3"

    if Path(f"{clean_dir}/model.safetensors.index.json").exists():
        print(f"[{persona}] Clean merge already exists — skip.")
        continue

    if not Path(adapter_dir).exists():
        print(f"[{persona}] Adapter not found at {adapter_dir} — skip.")
        continue

    print(f"\n[{persona}] Loading base model in FP16 on CPU...")
    model = AutoModelForCausalLM.from_pretrained(
        BASE,
        torch_dtype=torch.float16,
        device_map="cpu",
        trust_remote_code=True,
    )
    print(f"[{persona}] Applying R3 LoRA adapter from {adapter_dir}...")

    model = PeftModel.from_pretrained(model, adapter_dir)
    print(f"[{persona}] LoRA loaded. Merging...")

    model = model.merge_and_unload()
    print(f"[{persona}] Merge done. Saving clean FP16 weights...")

    Path(clean_dir).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(clean_dir, safe_serialization=True, max_shard_size="4GB")

    tokenizer = AutoTokenizer.from_pretrained(adapter_dir, trust_remote_code=True)
    tokenizer.save_pretrained(clean_dir)

    print(f"[{persona}] Clean FP16 saved to {clean_dir}")

    del model
    gc.collect()
    torch.cuda.empty_cache()
    print(f"[{persona}] Memory freed.")

print("\nAll R3 clean merges done.")
PYEOF

echo ""
echo "=== Converting R3 to GGUF ==="

do_model() {
    local persona="$1"
    local src="/data/outputs/merged_clean/${persona}-r3"
    local f16="/data/outputs/gguf/${persona}-r3/model-f16.gguf"
    local q4="/data/outputs/gguf/${persona}-r3/model-q4_k_m.gguf"
    mkdir -p "/data/outputs/gguf/${persona}-r3"

    if [ -f "$q4" ]; then
        echo "[${persona}-r3] Q4_K_M exists — skip."
        return
    fi

    if [ ! -d "$src" ]; then
        echo "[${persona}-r3] Merged weights not found — skip."
        return
    fi

    echo "[${persona}-r3] -> FP16 GGUF..."
    cd /data/llama_cpp_full
    python3 convert_hf_to_gguf.py "$src" --outfile "$f16" --outtype f16

    # Free merged weights immediately after F16 is written
    rm -rf "$src"
    echo "[${persona}-r3] FP16: $(du -sh $f16 | cut -f1) — source weights freed"

    echo "[${persona}-r3] -> Q4_K_M..."
    "$QUANTIZE" "$f16" "$q4" Q4_K_M
    rm -f "$f16"
    echo "[${persona}-r3] Q4_K_M: $(du -sh $q4 | cut -f1)"
}

do_model "cortana"
do_model "jarvis"

echo ""
echo "=== R3 Done === $(date)"
find /data/outputs/gguf -name "*.gguf" | while read f; do du -sh "$f"; done
echo "Download: scp -r azureuser@20.42.21.217:/data/outputs/gguf/*-r3/ ./"
