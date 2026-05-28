#!/usr/bin/env bash
# convert_to_gguf.sh — Convert merged HF weights -> GGUF Q4_K_M
set -e
export PATH="$HOME/.local/bin:/usr/bin:/usr/local/bin:$PATH"

MERGED_DIR=/data/outputs/merged
GGUF_DIR=/data/outputs/gguf
LLAMA_DIR=/data/llama_cpp

echo "============================================================"
echo "  GGUF Conversion  $(date)"
echo "============================================================"

# ── Step 1: Install Python deps ───────────────────────────────────────────────
echo "[1/5] Installing Python deps..."
python3 -m pip install gguf sentencepiece transformers --quiet

# ── Step 2: Clone llama.cpp (shallow — just for the convert scripts) ──────────
echo "[2/5] Getting llama.cpp convert tools..."
if [ ! -d "$LLAMA_DIR" ]; then
    git clone --depth 1 --filter=blob:none --sparse \
        https://github.com/ggerganov/llama.cpp "$LLAMA_DIR"
    cd "$LLAMA_DIR"
    git sparse-checkout set convert_hf_to_gguf.py convert_hf_to_gguf_update.py \
        examples/convert_legacy_llama.py gguf-py
    cd -
fi
CONVERT="$LLAMA_DIR/convert_hf_to_gguf.py"

# ── Step 3: Build llama-quantize from source (small build, fast) ──────────────
echo "[3/5] Building llama-quantize..."
LLAMA_BUILD=/data/llama_build
if [ ! -f "$LLAMA_BUILD/llama-quantize" ]; then
    sudo apt-get install -y cmake build-essential -q
    mkdir -p "$LLAMA_BUILD"
    cd "$LLAMA_BUILD"
    cmake "$LLAMA_DIR" -DCMAKE_BUILD_TYPE=Release \
        -DLLAMA_BUILD_TESTS=OFF \
        -DLLAMA_BUILD_EXAMPLES=OFF \
        -DBUILD_SHARED_LIBS=OFF \
        -DGGML_CUDA=OFF \
        > /dev/null 2>&1
    make llama-quantize -j4 > /dev/null 2>&1
    echo "  llama-quantize built: $LLAMA_BUILD/llama-quantize"
    cd -
fi
QUANTIZE="$LLAMA_BUILD/llama-quantize"

# ── Step 4: Convert each model ────────────────────────────────────────────────
echo "[4/5] Converting models..."

convert_model() {
    local name="$1"
    local src="$MERGED_DIR/$name"
    local dst="$GGUF_DIR/$name"
    mkdir -p "$dst"

    local f16="$dst/model-f16.gguf"
    local q4="$dst/model-q4_k_m.gguf"

    if [ -f "$q4" ]; then
        echo "  [$name] Q4_K_M already exists — skipping."
        return
    fi

    echo "  [$name] Converting to FP16 GGUF..."
    cd "$LLAMA_DIR"
    python3 convert_hf_to_gguf.py "$src" --outfile "$f16" --outtype f16
    cd -
    echo "  [$name] FP16: $(du -sh $f16 | cut -f1)"

    echo "  [$name] Quantizing to Q4_K_M..."
    "$QUANTIZE" "$f16" "$q4" Q4_K_M
    echo "  [$name] Q4_K_M: $(du -sh $q4 | cut -f1)"

    # Remove FP16 to save disk after Q4 is done
    rm -f "$f16"
    echo "  [$name] Done."
}

convert_model "cortana-8b"
convert_model "jarvis-8b"

# ── Step 5: Summary ───────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  Conversion Complete  $(date)"
find $GGUF_DIR -name "*.gguf" | while read f; do
    echo "  $(du -sh $f)"
done
echo ""
echo "  Download:"
echo "  scp -r azureuser@20.42.21.217:/data/outputs/gguf/ ./"
echo "============================================================"
