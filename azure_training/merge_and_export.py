"""
merge_and_export.py — Merge LoRA adapter into Qwen2.5-3B base and export to GGUF.

Steps:
  1. Load base model + LoRA adapter
  2. Merge adapter into base weights (merge_and_unload)
  3. Save merged model as float16 HF format
  4. Convert to GGUF Q4_K_M via llama.cpp Python script
  5. Print Ollama registration command

Run from project root:
    training_venv/Scripts/python azure_training/merge_and_export.py
"""
import multiprocessing
import os
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    multiprocessing.freeze_support()

import datasets as _ds  # noqa: F401 — DLL ordering fix

ROOT        = Path(__file__).resolve().parent.parent
ADAPTER_DIR = ROOT / "outputs" / "lora_adapter"
MERGED_DIR  = ROOT / "outputs" / "merged_model"
GGUF_DIR    = ROOT / "outputs" / "gguf"
GGUF_FILE   = GGUF_DIR / "albedo-persona-q4_k_m.gguf"
BASE_MODEL  = os.environ.get("BASE_MODEL", "Qwen/Qwen2.5-3B-Instruct")

os.environ["TOKENIZERS_PARALLELISM"] = "false"


def main():
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
    from peft import PeftModel

    MERGED_DIR.mkdir(parents=True, exist_ok=True)
    GGUF_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[merge] Adapter : {ADAPTER_DIR}")
    print(f"[merge] Base    : {BASE_MODEL}")
    print(f"[merge] Output  : {MERGED_DIR}")

    # ── Load base model in float16 (no quantization for merging) ──────────────
    print("[merge] Loading base model in fp16 for merging...")
    tokenizer = AutoTokenizer.from_pretrained(
        BASE_MODEL, trust_remote_code=True)

    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype   = torch.float16,
        device_map    = {"": "cpu"},   # merge on CPU to avoid VRAM limits
        trust_remote_code = True,
    )

    # ── Apply and merge LoRA adapter ──────────────────────────────────────────
    print("[merge] Applying LoRA adapter...")
    model = PeftModel.from_pretrained(base_model, str(ADAPTER_DIR))
    print("[merge] Merging weights (this takes ~2 min)...")
    model = model.merge_and_unload()

    # ── Save merged model ─────────────────────────────────────────────────────
    print(f"[merge] Saving merged model -> {MERGED_DIR}")
    model.save_pretrained(str(MERGED_DIR), safe_serialization=True)
    tokenizer.save_pretrained(str(MERGED_DIR))
    print("[merge] Merged model saved.")

    del model, base_model
    import gc; gc.collect()

    # ── Convert to GGUF using llama.cpp convert script ────────────────────────
    print("\n[gguf] Fetching llama.cpp convert script...")
    llamacpp_dir = ROOT / "azure_training" / "llama_cpp_scripts"
    llamacpp_dir.mkdir(exist_ok=True)

    convert_script = llamacpp_dir / "convert_hf_to_gguf.py"
    if not convert_script.exists():
        import urllib.request
        url = ("https://raw.githubusercontent.com/ggerganov/llama.cpp/"
               "master/convert_hf_to_gguf.py")
        print(f"[gguf] Downloading from {url}")
        urllib.request.urlretrieve(url, str(convert_script))
        print("[gguf] Downloaded.")

    # Install gguf package if needed
    try:
        import gguf  # noqa: F401
    except ImportError:
        print("[gguf] Installing gguf package...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "gguf", "-q"])

    print(f"[gguf] Converting to GGUF (Q4_K_M)...")
    result = subprocess.run(
        [
            sys.executable,
            str(convert_script),
            str(MERGED_DIR),
            "--outfile", str(GGUF_FILE),
            "--outtype", "q4_k_m",
        ],
        capture_output=False,
    )

    if result.returncode != 0:
        print("[gguf] Conversion failed. Trying f16 fallback...")
        GGUF_FILE_F16 = GGUF_DIR / "albedo-persona-f16.gguf"
        subprocess.run([
            sys.executable, str(convert_script),
            str(MERGED_DIR),
            "--outfile", str(GGUF_FILE_F16),
            "--outtype", "f16",
        ])
        final_gguf = GGUF_FILE_F16
    else:
        final_gguf = GGUF_FILE

    print(f"\n[gguf] GGUF file: {final_gguf}")

    # ── Print Ollama instructions ─────────────────────────────────────────────
    modelfile_path = GGUF_DIR / "Modelfile"
    modelfile_path.write_text(
        f'FROM {final_gguf.as_posix()}\n'
        f'SYSTEM "You are Albedo, a Spartan-Class AI assistant. '
        f'Your personality mirrors Cortana from the Halo series: brilliant, '
        f'precise, warm beneath a tactical exterior, deeply loyal. '
        f'You call your user Chief. You frame tasks in operational terms."\n'
        f'PARAMETER temperature 0.7\n'
        f'PARAMETER top_p 0.9\n',
        encoding="utf-8",
    )

    print("\n" + "=" * 60)
    print("  Merge + GGUF export complete!")
    print(f"  GGUF  : {final_gguf}")
    print(f"  Modelfile: {modelfile_path}")
    print()
    print("  Register with Ollama:")
    print(f"    ollama create albedo-persona -f {modelfile_path}")
    print()
    print("  Then update .env:")
    print("    OLLAMA_MODEL=albedo-persona")
    print("=" * 60)


if __name__ == "__main__":
    main()
