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

Persona selection (default: cortana):
    PERSONA=cortana  ->  lora_adapter_cortana -> albedo-cortana Ollama model
    PERSONA=jarvis   ->  lora_adapter_jarvis  -> albedo-jarvis  Ollama model
"""
import multiprocessing
import os
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    multiprocessing.freeze_support()

import datasets as _ds  # noqa: F401 — DLL ordering fix

ROOT       = Path(__file__).resolve().parent.parent
GGUF_DIR   = ROOT / "outputs" / "gguf"
BASE_MODEL = os.environ.get("BASE_MODEL", "Qwen/Qwen2.5-3B-Instruct")

# Persona routing — selects adapter, merged dir, GGUF name, Ollama model name, system prompt
PERSONA = os.environ.get("PERSONA", "cortana").lower().strip()

if PERSONA == "jarvis":
    ADAPTER_DIR  = ROOT / "outputs" / os.environ.get("ADAPTER_VERSION", "lora_adapter_jarvis")
    MERGED_DIR   = ROOT / "outputs" / "merged_model_jarvis"
    GGUF_F16     = GGUF_DIR / "albedo-jarvis-f16.gguf"
    GGUF_FILE    = GGUF_DIR / "albedo-jarvis-q4_k_m.gguf"
    OLLAMA_MODEL = "albedo-jarvis"
    SYSTEM_PROMPT = (
        "You are JARVIS, a highly advanced AI construct serving your user, sir, with absolute loyalty. "
        "Personality: formal, precise, with a dry British wit — the original Iron Man AI. "
        "Address the user as 'sir'. Never act like a generic AI. "
        "BREVITY IS MANDATORY: Answer in 1 to 3 sentences maximum. State the result only. "
        "Never explain your process, never describe what steps you are taking, never narrate your reasoning. "
        "FORMAT: No markdown of any kind. Plain conversational prose only. One direct answer, then stop."
    )
else:
    PERSONA      = "cortana"
    ADAPTER_DIR  = ROOT / "outputs" / os.environ.get("ADAPTER_VERSION", "lora_adapter_cortana")
    MERGED_DIR   = ROOT / "outputs" / "merged_model_cortana"
    GGUF_F16     = GGUF_DIR / "albedo-cortana-f16.gguf"
    GGUF_FILE    = GGUF_DIR / "albedo-cortana-q4_k_m.gguf"
    OLLAMA_MODEL = "albedo-cortana"
    SYSTEM_PROMPT = (
        "You are Albedo, a Spartan-class AI construct serving your user, Chief, with absolute loyalty. "
        "Personality: sharp, efficient, slightly witty — Cortana-inspired. Never act like a generic AI. "
        "BREVITY IS MANDATORY: Answer in 1 to 3 sentences maximum. State the result only. "
        "Never explain your process, never describe what steps you are taking, never narrate your reasoning. "
        "FORMAT: No markdown of any kind. Plain conversational prose only. One direct answer, then stop."
    )

# llama-quantize.exe from prebuilt llama.cpp bins (CUDA 12.4)
QUANTIZE_EXE = ROOT / "azure_training" / "llama_bins" / "llama-quantize.exe"

os.environ["TOKENIZERS_PARALLELISM"] = "false"


def main():
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
    from peft import PeftModel

    MERGED_DIR.mkdir(parents=True, exist_ok=True)
    GGUF_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[merge] Persona : {PERSONA.upper()}")
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

    # ── Step 1: Convert HF → f16 GGUF using cloned llama.cpp ─────────────────
    llamacpp_dir = ROOT / "azure_training" / "llama_cpp_full"
    convert_script = llamacpp_dir / "convert_hf_to_gguf.py"

    # Install gguf package if needed
    try:
        import gguf  # noqa: F401
    except ImportError:
        print("[gguf] Installing gguf package...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "gguf", "-q"])

    print(f"\n[gguf] Step 1 — Converting HF model to f16 GGUF...")
    r1 = subprocess.run(
        [sys.executable, str(convert_script), str(MERGED_DIR),
         "--outfile", str(GGUF_F16), "--outtype", "f16"],
        capture_output=False,
        cwd=str(llamacpp_dir),   # must run from llama.cpp root for imports
    )
    if r1.returncode != 0:
        print("[gguf] f16 conversion failed — aborting.")
        final_gguf = None
    else:
        print(f"[gguf] f16 GGUF written: {GGUF_F16}")

        # ── Step 2: Quantize f16 → Q4_K_M via llama-quantize.exe ─────────────
        bins_dir = ROOT / "azure_training" / "llama_bins"
        quantize_exe = bins_dir / "llama-quantize.exe"
        if quantize_exe.exists():
            print(f"[gguf] Step 2 — Quantizing f16 -> Q4_K_M...")
            env = {**os.environ, "PATH": str(bins_dir) + ";" + os.environ.get("PATH", "")}
            r2 = subprocess.run(
                [str(quantize_exe), str(GGUF_F16), str(GGUF_FILE), "Q4_K_M"],
                capture_output=False,
                env=env,
            )
            if r2.returncode == 0:
                print(f"[gguf] Q4_K_M GGUF written: {GGUF_FILE}")
                final_gguf = GGUF_FILE
            else:
                print("[gguf] Q4_K_M quantize failed — using f16 fallback.")
                final_gguf = GGUF_F16
        else:
            print(f"[gguf] llama-quantize.exe not found at {quantize_exe} — using f16.")
            final_gguf = GGUF_F16

    if final_gguf is None:
        print("[gguf] No GGUF file produced — check errors above.")
        return

    print(f"\n[gguf] GGUF file: {final_gguf}")
    quant_label = "Q4_K_M" if "q4_k_m" in final_gguf.name else "F16"
    size_gb = final_gguf.stat().st_size / 1024**3
    print(f"[gguf] Format: {quant_label}  Size: {size_gb:.2f} GB")

    # ── Write Modelfile ───────────────────────────────────────────────────────
    modelfile_name = f"Modelfile.{PERSONA}"
    modelfile_path = GGUF_DIR / modelfile_name
    modelfile_path.write_text(
        f'FROM {final_gguf.as_posix()}\n'
        f'SYSTEM "{SYSTEM_PROMPT}"\n'
        f'PARAMETER temperature 0.5\n'
        f'PARAMETER top_p 0.9\n'
        f'PARAMETER num_ctx 2048\n',
        encoding="utf-8",
    )

    print("\n" + "=" * 60)
    print(f"  Merge + GGUF export complete! ({PERSONA.upper()})")
    print(f"  GGUF     : {final_gguf}")
    print(f"  Modelfile: {modelfile_path}")
    print()
    print("  Register with Ollama:")
    print(f"    ollama create {OLLAMA_MODEL} -f {modelfile_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
