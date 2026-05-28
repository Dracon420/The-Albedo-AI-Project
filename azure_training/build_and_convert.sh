#!/usr/bin/env bash
# build_and_convert.sh — Full llama.cpp clone + build + GGUF conversion
set -e
export PATH="$HOME/.local/bin:/usr/bin:/usr/local/bin:$PATH"

echo "=== GGUF Conversion Pipeline ==="
echo "$(date)"

# ── 1. Clone llama.cpp (shallow, full tree needed for CMake) ──────────────────
if [ ! -f "/data/llama_cpp_full/CMakeLists.txt" ]; then
    echo "[1/5] Cloning llama.cpp..."
    git clone --depth 1 https://github.com/ggerganov/llama.cpp /data/llama_cpp_full
else
    echo "[1/5] llama.cpp already cloned."
fi

# ── 2. Install Python gguf package from repo ──────────────────────────────────
echo "[2/5] Installing gguf Python package..."
python3 -m pip install /data/llama_cpp_full/gguf-py --quiet 2>/dev/null \
    || python3 -m pip install gguf --quiet

# ── 3. Build llama-quantize (CPU only) ───────────────────────────────────────
QUANTIZE=/data/llama_cpp_full/build/bin/llama-quantize
if [ ! -f "$QUANTIZE" ]; then
    echo "[3/5] Building llama-quantize (CPU, release mode)..."
    mkdir -p /data/llama_cpp_full/build
    cd /data/llama_cpp_full/build
    cmake .. \
        -DCMAKE_BUILD_TYPE=Release \
        -DLLAMA_BUILD_TESTS=OFF \
        -DGGML_CUDA=OFF \
        -DGGML_METAL=OFF \
        > /tmp/cmake.log 2>&1 || { echo "cmake FAILED:"; cat /tmp/cmake.log; exit 1; }
    make llama-quantize -j4 > /tmp/make.log 2>&1 || { echo "make FAILED:"; cat /tmp/make.log; exit 1; }
    cd -
    echo "[3/5] llama-quantize built: $QUANTIZE"
else
    echo "[3/5] llama-quantize already built."
fi

# ── 4. Convert + quantize ─────────────────────────────────────────────────────
echo "[4/5] Converting models..."

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
    echo "  [$name] FP16 size: $(du -sh $f16 | cut -f1)"

    echo "  [$name] -> Q4_K_M..."
    "$QUANTIZE" "$f16" "$q4" Q4_K_M
    rm -f "$f16"
    echo "  [$name] Q4_K_M size: $(du -sh $q4 | cut -f1)"
}

do_model "cortana-8b"
do_model "jarvis-8b"

# ── 5. Summary ────────────────────────────────────────────────────────────────
echo ""
echo "=== Done === $(date)"
find /data/outputs/gguf -name "*.gguf" | while read f; do du -sh "$f"; done
echo "Download: scp -r azureuser@20.42.21.217:/data/outputs/gguf/ ./"
