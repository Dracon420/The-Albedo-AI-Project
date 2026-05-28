"""
train_azure_t4.py — Albedo/JARVIS QLoRA fine-tune for Azure NCas_T4_v3.

Hardware target: NVIDIA Tesla T4 (16 GB VRAM, Turing / sm_75).
  • T4 is Turing — NO bfloat16 support.  fp16=True is forced.
  • 16 GB gives comfortable headroom for Llama-3.1-8B in 4-bit + rank-32 LoRA.
  • Unsloth is used for speed (≈ 2× faster than vanilla HF on T4).

Persona routing (PERSONA env var):
    PERSONA=cortana  →  albedo_dataset_v3.jsonl  → outputs/lora_adapter_cortana_8b
    PERSONA=jarvis   →  jarvis_dataset_v2.jsonl   → outputs/lora_adapter_jarvis_8b

Usage on Azure VM (after running setup_vm.sh):
    PERSONA=cortana python train_azure_t4.py
    PERSONA=jarvis  python train_azure_t4.py

All config overridable via env vars — see Config block below.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import sys
import time
from pathlib import Path

# ── Windows/Linux multiprocessing guard ──────────────────────────────────────
if __name__ == "__main__":
    multiprocessing.freeze_support()

# ── Config ────────────────────────────────────────────────────────────────────
# Paths relative to this script's parent (azure_training/)
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT   = _SCRIPT_DIR.parent
_DATA_DIR    = _REPO_ROOT / "training_data"
_OUTPUT_DIR  = Path(os.environ.get("OUTPUT_DIR", str(_REPO_ROOT / "outputs")))

PERSONA = os.environ.get("PERSONA", "cortana").lower().strip()
if PERSONA == "jarvis":
    DATA_FILE   = _DATA_DIR / "jarvis_dataset_v2.jsonl"
    ADAPTER_DIR = _OUTPUT_DIR / "lora_adapter_jarvis_8b"
    MODEL_TAG   = "jarvis-8b"
else:
    PERSONA     = "cortana"
    DATA_FILE   = _DATA_DIR / "albedo_dataset_v3.jsonl"
    ADAPTER_DIR = _OUTPUT_DIR / "lora_adapter_cortana_8b"
    MODEL_TAG   = "cortana-8b"

# T4 sweet spot: Llama-3.1-8B in 4-bit ≈ 5 GB base weights + ~3 GB activations
# + rank-32 LoRA ≈ 1.5 GB → total ≈ 10–11 GB → fits in 16 GB with breathing room.
BASE_MODEL  = os.environ.get(
    "BASE_MODEL",
    "Qwen/Qwen2.5-7B-Instruct",   # official repo — BnB handles 4-bit loading
)
MAX_SEQ_LEN = int(os.environ.get("MAX_SEQ_LEN", "2048"))
EPOCHS      = int(os.environ.get("EPOCHS",      "10"))
BATCH_SIZE  = int(os.environ.get("BATCH_SIZE",  "4"))
GRAD_ACCUM  = int(os.environ.get("GRAD_ACCUM",  "8"))   # effective batch = 32
LR          = float(os.environ.get("LR",        "2e-4"))
LORA_RANK   = int(os.environ.get("LORA_RANK",   "32"))
HF_TOKEN    = os.environ.get("HF_TOKEN", "")

os.environ["TOKENIZERS_PARALLELISM"] = "false"

_t0 = time.time()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _elapsed() -> str:
    s = int(time.time() - _t0)
    return f"{s // 60}m {s % 60:02d}s"


def log(msg: str) -> None:
    print(f"[t4-train | {_elapsed()}] {msg}", flush=True)


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        log(f"ERROR: dataset not found: {path}")
        sys.exit(1)
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def format_example(example: dict, tokenizer) -> str:  # noqa: ANN001
    """Convert messages list → Llama-3 chat format using the tokenizer's template."""
    messages = example.get("messages", [])
    try:
        # apply_chat_template handles system/user/assistant roles correctly
        return tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=False,
        )
    except Exception:
        # Fallback: manual Llama-3 format
        text = ""
        for msg in messages:
            role, content = msg["role"], msg["content"]
            if role == "system":
                text += f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{content}<|eot_id|>"
            elif role == "user":
                text += f"<|start_header_id|>user<|end_header_id|>\n\n{content}<|eot_id|>"
            elif role == "assistant":
                text += f"<|start_header_id|>assistant<|end_header_id|>\n\n{content}<|eot_id|>"
        return text + tokenizer.eos_token


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    log("=" * 60)
    log(f"Albedo T4 Training — {PERSONA.upper()} persona")
    log("=" * 60)
    log(f"Base model  : {BASE_MODEL}")
    log(f"Dataset     : {DATA_FILE}")
    log(f"Adapter out : {ADAPTER_DIR}")
    log(f"Epochs      : {EPOCHS}")
    log(f"Batch size  : {BATCH_SIZE} x {GRAD_ACCUM} grad_accum = eff. {BATCH_SIZE * GRAD_ACCUM}")
    log(f"LoRA rank   : {LORA_RANK}  (alpha={LORA_RANK * 2})")
    log(f"Max seq len : {MAX_SEQ_LEN}")
    log(f"LR          : {LR}")

    import torch

    if not torch.cuda.is_available():
        log("ERROR: CUDA not available — aborting.")
        sys.exit(1)

    gpu_name = torch.cuda.get_device_name(0)
    vram_gb  = torch.cuda.get_device_properties(0).total_memory / 1024 ** 3
    sm_major = torch.cuda.get_device_properties(0).major
    log(f"GPU         : {gpu_name} ({vram_gb:.1f} GB VRAM, sm_{sm_major}x)")

    # T4 = sm_75; warn if BF16 accidentally requested
    if sm_major < 8:
        log("NOTE: sm < 8 detected (Turing/Volta) — BF16 disabled, using FP16.")

    # ── Load model + tokenizer (Unsloth preferred, vanilla HF fallback) ─────────
    _use_unsloth = False
    try:
        from unsloth import FastLanguageModel as _FLM
        _use_unsloth = True
        log("Unsloth available — using fast path.")
    except ImportError:
        log("Unsloth not installed — using vanilla HuggingFace (slower but correct).")

    if _use_unsloth:
        model, tokenizer = _FLM.from_pretrained(
            model_name     = BASE_MODEL,
            max_seq_length = MAX_SEQ_LEN,
            dtype          = torch.float16,   # Force FP16 — T4 has no BF16
            load_in_4bit   = True,
            token          = HF_TOKEN or None,
        )
        log("Model loaded via Unsloth.")
        model = _FLM.get_peft_model(
            model,
            r              = LORA_RANK,
            lora_alpha     = LORA_RANK * 2,
            target_modules = [
                "q_proj", "k_proj", "v_proj", "o_proj",
                "gate_proj", "up_proj", "down_proj",
            ],
            lora_dropout              = 0.05,
            bias                      = "none",
            use_gradient_checkpointing = "unsloth",
            random_state              = 3407,
            use_rslora                = True,
            loftq_config              = None,
        )
    else:
        # Vanilla HF path (same quality, ~2x slower on T4)
        from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
        from peft import LoraConfig, get_peft_model, TaskType

        bnb_config = BitsAndBytesConfig(
            load_in_4bit              = True,
            bnb_4bit_quant_type       = "nf4",
            bnb_4bit_compute_dtype    = torch.float16,
            bnb_4bit_use_double_quant = True,
        )
        tokenizer = AutoTokenizer.from_pretrained(
            BASE_MODEL, token=HF_TOKEN or None, trust_remote_code=True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL,
            quantization_config = bnb_config,
            device_map          = {"": 0},
            token               = HF_TOKEN or None,
            trust_remote_code   = True,
        )
        model.config.use_cache = False
        model.enable_input_require_grads()
        lora_cfg = LoraConfig(
            task_type      = TaskType.CAUSAL_LM,
            r              = LORA_RANK,
            lora_alpha     = LORA_RANK * 2,
            target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                              "gate_proj", "up_proj", "down_proj"],
            lora_dropout   = 0.05,
            bias           = "none",
        )
        model = get_peft_model(model, lora_cfg)
        log("Model loaded via vanilla HuggingFace.")

    model.print_trainable_parameters()

    # ── Build dataset ─────────────────────────────────────────────────────────
    log(f"Loading dataset: {DATA_FILE.name}")
    raw = load_jsonl(DATA_FILE)
    log(f"{len(raw)} examples loaded.")

    tokenizer.pad_token    = tokenizer.eos_token
    tokenizer.padding_side = "right"

    from datasets import Dataset

    formatted = [{"text": format_example(ex, tokenizer)} for ex in raw]
    dataset   = Dataset.from_list(formatted)
    log(f"{len(dataset)} examples formatted.")

    # ── Trainer ───────────────────────────────────────────────────────────────
    from trl import SFTTrainer
    from transformers import TrainingArguments

    warmup_steps = max(10, len(dataset) // (BATCH_SIZE * GRAD_ACCUM) // 5)

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ckpt_dir = _OUTPUT_DIR / "checkpoints" / MODEL_TAG

    trainer = SFTTrainer(
        model              = model,
        tokenizer          = tokenizer,
        train_dataset      = dataset,
        dataset_text_field = "text",
        max_seq_length     = MAX_SEQ_LEN,
        dataset_num_proc   = 4,
        packing            = True,
        args = TrainingArguments(
            per_device_train_batch_size   = BATCH_SIZE,
            gradient_accumulation_steps   = GRAD_ACCUM,
            warmup_steps                  = warmup_steps,
            num_train_epochs              = EPOCHS,
            learning_rate                 = LR,
            fp16                          = True,   # FORCED for T4
            bf16                          = False,  # FORCED off for T4
            logging_steps                 = 10,
            optim                         = "adamw_8bit",
            weight_decay                  = 0.01,
            lr_scheduler_type             = "cosine",
            seed                          = 3407,
            output_dir                    = str(ckpt_dir),
            save_strategy                 = "epoch",
            save_total_limit              = 3,
            report_to                     = "none",
            dataloader_num_workers        = 4,
            dataloader_pin_memory         = True,
            group_by_length               = True,
            gradient_checkpointing        = not _use_unsloth,  # Unsloth handles it internally
        ),
    )

    log("Starting training…")
    trainer_stats = trainer.train()
    train_loss    = trainer_stats.training_loss
    train_time    = trainer_stats.metrics.get("train_runtime", 0)
    log(f"Training complete — loss: {train_loss:.4f}  time: {train_time:.0f}s")

    # ── Save LoRA adapter ─────────────────────────────────────────────────────
    ADAPTER_DIR.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(ADAPTER_DIR))
    tokenizer.save_pretrained(str(ADAPTER_DIR))
    log(f"LoRA adapter saved → {ADAPTER_DIR}")

    # ── Merge + export ────────────────────────────────────────────────────────
    merged_dir = _OUTPUT_DIR / "merged" / MODEL_TAG
    gguf_dir   = _OUTPUT_DIR / "gguf"   / MODEL_TAG
    merged_dir.mkdir(parents=True, exist_ok=True)
    gguf_dir.mkdir(parents=True, exist_ok=True)

    if _use_unsloth:
        log("Merging LoRA into base weights (Unsloth 16-bit)…")
        model.save_pretrained_merged(str(merged_dir), tokenizer, save_method="merged_16bit")
        log(f"Merged weights saved → {merged_dir}")

        log("Exporting GGUF Q4_K_M via Unsloth…")
        model.save_pretrained_gguf(str(gguf_dir), tokenizer, quantization_method="q4_k_m")
        log(f"GGUF exported → {gguf_dir}")
    else:
        # Vanilla HF merge using PEFT's merge_and_unload
        log("Merging LoRA via PEFT merge_and_unload…")
        merged_model = model.merge_and_unload()
        merged_model.save_pretrained(str(merged_dir))
        tokenizer.save_pretrained(str(merged_dir))
        log(f"Merged weights saved → {merged_dir}")

        # GGUF conversion using llama.cpp convert script
        log("Converting to GGUF Q4_K_M via llama.cpp…")
        import subprocess
        # Try to use llama-quantize if available, else skip
        convert_py = Path("/usr/local/lib").glob("**/convert_hf_to_gguf.py")
        convert_script = next(convert_py, None)
        if convert_script:
            fp16_gguf = str(gguf_dir / "model-f16.gguf")
            subprocess.run([
                "python3", str(convert_script),
                str(merged_dir), "--outfile", fp16_gguf, "--outtype", "f16",
            ], check=True)
            q_gguf = str(gguf_dir / "model-q4_k_m.gguf")
            # Try llama-quantize from PATH
            try:
                subprocess.run(["llama-quantize", fp16_gguf, q_gguf, "Q4_K_M"], check=True)
                log(f"GGUF Q4_K_M → {q_gguf}")
            except FileNotFoundError:
                log(f"llama-quantize not found — F16 GGUF saved at {fp16_gguf}")
                log("Download llama-quantize and run: llama-quantize model-f16.gguf model-q4_k_m.gguf Q4_K_M")
        else:
            log("llama.cpp convert script not found — merged weights saved only.")
            log(f"To quantize manually: pip install llama-cpp-python then convert {merged_dir}")
        log(f"GGUF output dir → {gguf_dir}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print(f"  {PERSONA.upper()} training complete!")
    print(f"  Final loss    : {train_loss:.4f}")
    print(f"  Training time : {int(train_time // 60)}m {int(train_time % 60):02d}s")
    print(f"  LoRA adapter  : {ADAPTER_DIR}")
    print(f"  Merged 16-bit : {merged_dir}")
    print(f"  GGUF Q4_K_M   : {gguf_dir}")
    print()
    print("  Next steps:")
    print("  1. scp the GGUF to your local machine")
    print(f"     scp -r azureuser@<VM_IP>:{gguf_dir} ./")
    print("  2. Create an Ollama Modelfile and register it")
    print("     See azure_training/create_ollama_model.ps1")
    print("=" * 60)


if __name__ == "__main__":
    main()
