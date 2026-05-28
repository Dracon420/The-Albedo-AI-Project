#!/usr/bin/env bash
# Download pre-built llama.cpp Linux release and run GGUF conversion
set -e
cd /data

echo "[1/4] Getting latest llama.cpp Linux release..."
LATEST_URL=$(curl -s https://api.github.com/repos/ggerganov/llama.cpp/releases/latest \
    | python3 -c "
import json, sys
d = json.load(sys.stdin)
for a in d['assets']:
    name = a['name'].lower()
    if 'ubuntu' in name and 'x64' in name and name.endswith('.zip'):
        print(a['browser_download_url'])
        break
")
echo "URL: $LATEST_URL"
curl -L -o /data/llama_release.zip "$LATEST_URL"

echo "[2/4] Extracting..."
unzip -q llama_release.zip -d llama_release
QUANTIZE=$(find /data/llama_release -name "llama-quantize" -type f | head -1)
chmod +x "$QUANTIZE"
echo "llama-quantize: $QUANTIZE"

echo "[3/4] Getting full llama.cpp repo for convert script..."
if [ ! -d "/data/llama_cpp_full" ]; then
    git clone --depth 1 https://github.com/ggerganov/llama.cpp /data/llama_cpp_full
fi
python3 -m pip install /data/llama_cpp_full/gguf-py --quiet

echo "[4/4] Converting models to GGUF Q4_K_M..."

convert_model() {
    local name="$1"
    local src="/data/outputs/merged/$name"
    local dst="/data/outputs/gguf/$name"
    mkdir -p "$dst"
    local f16="$dst/model-f16.gguf"
    local q4="$dst/model-q4_k_m.gguf"

    if [ -f "$q4" ]; then
        echo "[$name] Q4_K_M already done."
        return
    fi

    echo "[$name] Converting to F16 GGUF..."
    cd /data/llama_cpp_full
    python3 convert_hf_to_gguf.py "$src" --outfile "$f16" --outtype f16
    echo "[$name] F16: $(du -sh $f16 | cut -f1)"

    echo "[$name] Quantizing to Q4_K_M..."
    "$QUANTIZE" "$f16" "$q4" Q4_K_M
    rm -f "$f16"
    echo "[$name] Q4_K_M: $(du -sh $q4 | cut -f1)"
}

convert_model "cortana-8b"
convert_model "jarvis-8b"

echo ""
echo "==================================================="
echo "GGUF conversion complete!"
find /data/outputs/gguf -name "*.gguf" -exec du -sh {} \;
echo "==================================================="
