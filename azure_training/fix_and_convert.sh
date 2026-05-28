#!/usr/bin/env bash
# fix_and_convert.sh — Strip BnB quantization metadata, then run GGUF conversion.
set -e
export PATH="$HOME/.local/bin:/usr/bin:/usr/local/bin:$PATH"

QUANTIZE=/data/llama_cpp_full/build/bin/llama-quantize

echo "=== Fix metadata + GGUF convert ==="
echo "$(date)"

# ── Strip quantization_config from merged model configs ───────────────────────
echo "[1/3] Cleaning config.json for both models..."
python3 << 'PYEOF'
import json

for name in ("cortana-8b", "jarvis-8b"):
    path = f"/data/outputs/merged/{name}/config.json"
    with open(path) as f:
        cfg = json.load(f)
    if "quantization_config" in cfg:
        print(f"  [{name}] Removing quantization_config: {cfg['quantization_config']}")
        del cfg["quantization_config"]
        with open(path, "w") as f:
            json.dump(cfg, f, indent=2)
        print(f"  [{name}] config.json cleaned.")
    else:
        print(f"  [{name}] No quantization_config found — nothing to strip.")
PYEOF

# ── Convert each model ────────────────────────────────────────────────────────
echo "[2/3] Converting to GGUF..."

do_model() {
    local name="$1"
    local src="/data/outputs/merged/$name"
    local f16="/data/outputs/gguf/${name}/model-f16.gguf"
    local q4="/data/outputs/gguf/${name}/model-q4_k_m.gguf"
    mkdir -p "/data/outputs/gguf/$name"

    if [ -f "$q4" ]; then
        echo "  [$name] Q4_K_M exists — skip."
        return
    fi

    echo "  [$name] -> FP16 GGUF..."
    cd /data/llama_cpp_full
    python3 convert_hf_to_gguf.py "$src" --outfile "$f16" --outtype f16
    echo "  [$name] FP16: $(du -sh $f16 | cut -f1)"

    echo "  [$name] -> Q4_K_M..."
    "$QUANTIZE" "$f16" "$q4" Q4_K_M
    rm -f "$f16"
    echo "  [$name] Q4_K_M: $(du -sh $q4 | cut -f1)"
}

do_model "cortana-8b"
do_model "jarvis-8b"

echo ""
echo "[3/3] Results:"
find /data/outputs/gguf -name "*.gguf" | while read f; do du -sh "$f"; done
echo ""
echo "=== Done === $(date)"
