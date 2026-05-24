"""
train_local.py — Albedo QLoRA fine-tune for local RTX 2060 (6 GB VRAM).

Uses standard HuggingFace transformers + PEFT + bitsandbytes (no Unsloth).
Reads ../training_data/albedo_dataset.jsonl, fine-tunes with QLoRA,
saves LoRA adapter to ../outputs/lora_adapter/.

Estimated time on RTX 2060: ~5-15 minutes for 49 examples x 3 epochs.

Run from project root:
    training_venv/Scripts/python azure_training/train_local.py
"""
import json
import multiprocessing
import os
import sys
from pathlib import Path

# ── Windows multiprocessing guard ─────────────────────────────────────────────
# MUST be at the top. On Windows, 'spawn' is the default start method.
# Without this, worker processes re-import this module and run everything again.
if __name__ == "__main__":
    multiprocessing.freeze_support()

# Windows DLL ordering fix: datasets (pyarrow) must load before bitsandbytes
# or the CUDA runtime conflicts cause a segfault.
import datasets as _datasets_preload  # noqa: F401 — side-effect import

# ── Config ────────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).resolve().parent.parent
DATA_FILE   = ROOT / "training_data" / "albedo_dataset.jsonl"
OUTPUT_DIR  = ROOT / "outputs"
ADAPTER_DIR = OUTPUT_DIR / "lora_adapter_v2"   # v2 — keep v1 for rollback

BASE_MODEL  = os.environ.get("BASE_MODEL", "Qwen/Qwen2.5-3B-Instruct")
MAX_SEQ_LEN = int(os.environ.get("MAX_SEQ_LEN", "512"))
EPOCHS      = int(os.environ.get("EPOCHS",      "5"))    # ↑ 3→5
BATCH_SIZE  = int(os.environ.get("BATCH_SIZE",  "1"))
GRAD_ACCUM  = int(os.environ.get("GRAD_ACCUM",  "8"))
LR          = float(os.environ.get("LR",        "1e-4"))  # ↓ 2e-4→1e-4 for rank-16
LORA_RANK   = int(os.environ.get("LORA_RANK",   "16"))   # ↑ 8→16
HF_TOKEN    = os.environ.get("HF_TOKEN", "")

os.environ["TOKENIZERS_PARALLELISM"] = "false"  # suppress tokenizer warnings


def load_jsonl(path: Path) -> list:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def format_example(example: dict) -> str:
    """Convert messages list to Qwen2.5 ChatML format."""
    messages = example.get("messages", [])
    text = ""
    for msg in messages:
        role    = msg["role"]
        content = msg["content"]
        text += f"<|im_start|>{role}\n{content}<|im_end|>\n"
    return text


def main():
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, TaskType
    from trl import SFTTrainer, SFTConfig
    from datasets import Dataset

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[albedo-train] Base model  : {BASE_MODEL}")
    print(f"[albedo-train] Dataset     : {DATA_FILE}")
    print(f"[albedo-train] Epochs      : {EPOCHS}")
    print(f"[albedo-train] Batch size  : {BATCH_SIZE} x {GRAD_ACCUM} grad accum = effective {BATCH_SIZE * GRAD_ACCUM}")
    print(f"[albedo-train] LoRA rank   : {LORA_RANK}")
    print(f"[albedo-train] Output      : {OUTPUT_DIR}")

    if not torch.cuda.is_available():
        print("[ERROR] CUDA not available.")
        sys.exit(1)

    gpu_name = torch.cuda.get_device_name(0)
    vram_gb  = torch.cuda.get_device_properties(0).total_memory / 1024**3
    print(f"[albedo-train] GPU         : {gpu_name} ({vram_gb:.1f} GB VRAM)")

    # ── Dataset ───────────────────────────────────────────────────────────────
    raw = load_jsonl(DATA_FILE)
    print(f"[albedo-train] Dataset loaded — {len(raw)} examples.")
    formatted = [{"text": format_example(ex)} for ex in raw]
    dataset   = Dataset.from_list(formatted)
    print(f"[albedo-train] {len(dataset)} examples formatted.")

    # ── Tokenizer ─────────────────────────────────────────────────────────────
    print("[albedo-train] Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(
        BASE_MODEL,
        token           = HF_TOKEN or None,
        trust_remote_code = True,
    )
    tokenizer.pad_token    = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # ── Model (4-bit QLoRA) ───────────────────────────────────────────────────
    # RTX 2060 (Turing) does not support bfloat16 — use float32 as compute dtype.
    # fp16 AMP is disabled in SFTConfig to avoid grad scaler conflicts with bnb.
    bnb_config = BitsAndBytesConfig(
        load_in_4bit              = True,
        bnb_4bit_quant_type       = "nf4",
        bnb_4bit_compute_dtype    = torch.float32,
        bnb_4bit_use_double_quant = True,
    )

    print("[albedo-train] Loading model (4-bit)...")
    # Force all layers onto GPU 0. device_map="auto" may offload to CPU
    # when other display processes are occupying VRAM — explicit map avoids that.
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        quantization_config = bnb_config,
        device_map          = {"": 0},
        token               = HF_TOKEN or None,
        trust_remote_code   = True,
    )
    model.config.use_cache      = False
    model.config.pretraining_tp = 1
    model.enable_input_require_grads()

    lora_config = LoraConfig(
        task_type      = TaskType.CAUSAL_LM,
        r              = LORA_RANK,
        lora_alpha     = LORA_RANK,     # alpha=rank is standard for rank-16
        target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                          "gate_proj", "up_proj", "down_proj"],
        lora_dropout   = 0.05,
        bias           = "none",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # ── Train ─────────────────────────────────────────────────────────────────
    sft_config = SFTConfig(
        dataset_text_field          = "text",
        max_length                  = MAX_SEQ_LEN,
        packing                     = False,
        dataset_num_proc            = 1,
        output_dir                  = str(OUTPUT_DIR / "checkpoints"),
        num_train_epochs            = EPOCHS,
        per_device_train_batch_size = BATCH_SIZE,
        gradient_accumulation_steps = GRAD_ACCUM,
        gradient_checkpointing      = True,
        optim                       = "adamw_8bit",
        learning_rate               = LR,
        weight_decay                = 0.01,
        fp16                        = False,
        bf16                        = False,
        warmup_steps                = 10,           # ↑ 5→10 for longer run
        lr_scheduler_type           = "cosine",     # cosine decay for rank-16
        logging_steps               = 5,
        save_strategy               = "epoch",
        report_to                   = "none",
        seed                        = 3407,
        dataloader_num_workers      = 0,
    )

    trainer = SFTTrainer(
        model            = model,
        processing_class = tokenizer,
        train_dataset    = dataset,
        args             = sft_config,
    )

    print("[albedo-train] Starting training...")
    trainer_stats = trainer.train()
    print(f"[albedo-train] Done. Loss: {trainer_stats.training_loss:.4f}  "
          f"Runtime: {trainer_stats.metrics.get('train_runtime', 0):.0f}s")

    # ── Save LoRA adapter ─────────────────────────────────────────────────────
    ADAPTER_DIR.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(ADAPTER_DIR))
    tokenizer.save_pretrained(str(ADAPTER_DIR))
    print(f"[albedo-train] LoRA adapter saved -> {ADAPTER_DIR}")
    print()
    print("=" * 60)
    print("  Training complete.")
    print(f"  Adapter: {ADAPTER_DIR}")
    print()
    print("  Next step: install adapter into Ollama")
    print("  See azure_training/create_ollama_model.ps1")
    print("=" * 60)


if __name__ == "__main__":
    main()
