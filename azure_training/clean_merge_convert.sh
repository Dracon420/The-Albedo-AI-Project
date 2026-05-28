#!/usr/bin/env bash
# clean_merge_convert.sh — Merge LoRA onto clean FP16 base, then GGUF Q4_K_M.
#
# Loads Qwen2.5-7B-Instruct in FP16 on CPU (no BnB), applies saved LoRA adapter,
# merges cleanly, saves FP16 safetensors, then converts to GGUF Q4_K_M.
# The NC4as_T4_v3 has 28GB RAM — 14GB FP16 model fits comfortably.
set -e
export PATH="$HOME/.local/bin:/usr/bin:/usr/local/bin:$PATH"
export HF_HOME=/data/hf_cache

QUANTIZE=/data/llama_cpp_full/build/bin/llama-quantize

echo "=== Clean Merge + GGUF Conversion ==="
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
    adapter_dir = f"/data/outputs/lora_adapter_{persona}_8b"
    clean_dir   = f"/data/outputs/merged_clean/{persona}-8b"

    if Path(f"{clean_dir}/model.safetensors.index.json").exists():
        print(f"[{persona}] Clean merge already exists — skip.")
        continue

    print(f"\n[{persona}] Loading base model in FP16 on CPU...")
    model = AutoModelForCausalLM.from_pretrained(
        BASE,
        torch_dtype   = torch.float16,
        device_map    = "cpu",          # pure CPU — no BnB, no GPU
        trust_remote_code = True,
    )
    print(f"[{persona}] Base model loaded. Applying LoRA adapter...")

    model = PeftModel.from_pretrained(model, adapter_dir)
    print(f"[{persona}] LoRA loaded. Merging...")

    model = model.merge_and_unload()
    print(f"[{persona}] Merge done. Saving clean FP16 weights...")

    Path(clean_dir).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(clean_dir, safe_serialization=True, max_shard_size="4GB")

    tokenizer = AutoTokenizer.from_pretrained(adapter_dir, trust_remote_code=True)
    tokenizer.save_pretrained(clean_dir)

    print(f"[{persona}] Clean FP16 saved to {clean_dir}")

    # Free memory before next model
    del model
    gc.collect()
    torch.cuda.empty_cache()
    print(f"[{persona}] Memory freed.")

print("\nAll clean merges done.")
PYEOF

echo ""
echo "=== Converting to GGUF ==="

do_model() {
    local name="$1"
    local src="/data/outputs/merged_clean/$name"
    local f16="/data/outputs/gguf/${name}/model-f16.gguf"
    local q4="/data/outputs/gguf/${name}/model-q4_k_m.gguf"
    mkdir -p "/data/outputs/gguf/$name"

    if [ -f "$q4" ]; then
        echo "[$name] Q4_K_M exists — skip."
        return
    fi

    echo "[$name] -> FP16 GGUF..."
    cd /data/llama_cpp_full
    python3 convert_hf_to_gguf.py "$src" --outfile "$f16" --outtype f16
    echo "[$name] FP16: $(du -sh $f16 | cut -f1)"

    echo "[$name] -> Q4_K_M..."
    "$QUANTIZE" "$f16" "$q4" Q4_K_M
    rm -f "$f16"
    echo "[$name] Q4_K_M: $(du -sh $q4 | cut -f1)"
}

do_model "cortana-8b"
do_model "jarvis-8b"

echo ""
echo "=== All Done === $(date)"
find /data/outputs/gguf -name "*.gguf" | while read f; do du -sh "$f"; done
echo "Download: scp -r azureuser@20.42.21.217:/data/outputs/gguf/ ./"
