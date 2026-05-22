"""
train.py — Albedo LoRA fine-tune script using Unsloth.

Runs inside an Azure ML job on a GPU compute node.
Reads the dataset from ./data/albedo_dataset.jsonl,
fine-tunes the base model with LoRA, merges the adapter,
and exports a Q4_K_M GGUF file to ./outputs/.
"""
import os
import json
from pathlib import Path

# ── Config (overridable via env vars passed by Azure ML job) ──────────────
BASE_MODEL  = os.environ.get("BASE_MODEL",  "unsloth/llama-3.2-3b-instruct-bnb-4bit")
OUTPUT_DIR  = Path(os.environ.get("OUTPUT_DIR",  "./outputs"))
DATA_FILE   = Path(os.environ.get("DATA_FILE",   "./data/albedo_dataset.jsonl"))
MAX_SEQ_LEN = int(os.environ.get("MAX_SEQ_LEN",  "2048"))
EPOCHS      = int(os.environ.get("EPOCHS",       "3"))
BATCH_SIZE  = int(os.environ.get("BATCH_SIZE",   "2"))
GRAD_ACCUM  = int(os.environ.get("GRAD_ACCUM",   "4"))
LR          = float(os.environ.get("LR",         "2e-4"))

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print(f"[albedo-train] Base model : {BASE_MODEL}")
print(f"[albedo-train] Dataset    : {DATA_FILE}")
print(f"[albedo-train] Epochs     : {EPOCHS}")
print(f"[albedo-train] Output     : {OUTPUT_DIR}")

# ── Load model with Unsloth ───────────────────────────────────────────────
from unsloth import FastLanguageModel
import torch

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name       = BASE_MODEL,
    max_seq_length   = MAX_SEQ_LEN,
    dtype            = None,           # auto-detect (bf16 on A100/V100)
    load_in_4bit     = True,
)

model = FastLanguageModel.get_peft_model(
    model,
    r                     = 16,
    target_modules        = ["q_proj", "k_proj", "v_proj", "o_proj",
                              "gate_proj", "up_proj", "down_proj"],
    lora_alpha            = 16,
    lora_dropout          = 0,
    bias                  = "none",
    use_gradient_checkpointing = "unsloth",
    random_state          = 3407,
)

# ── Build dataset ─────────────────────────────────────────────────────────
from datasets import Dataset

def load_jsonl(path: Path) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records

raw = load_jsonl(DATA_FILE)

def format_example(example: dict) -> str:
    """Convert messages list to Llama-3 chat format."""
    messages = example.get("messages", [])
    text = ""
    for msg in messages:
        role    = msg["role"]
        content = msg["content"]
        if role == "system":
            text += f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{content}<|eot_id|>"
        elif role == "user":
            text += f"<|start_header_id|>user<|end_header_id|>\n\n{content}<|eot_id|>"
        elif role == "assistant":
            text += f"<|start_header_id|>assistant<|end_header_id|>\n\n{content}<|eot_id|>"
    return text + tokenizer.eos_token

formatted = [{"text": format_example(ex)} for ex in raw]
dataset   = Dataset.from_list(formatted)

print(f"[albedo-train] Dataset loaded — {len(dataset)} examples.")

# ── Train ─────────────────────────────────────────────────────────────────
from trl import SFTTrainer
from transformers import TrainingArguments
from unsloth import is_bfloat16_supported

trainer = SFTTrainer(
    model         = model,
    tokenizer     = tokenizer,
    train_dataset = dataset,
    dataset_text_field = "text",
    max_seq_length     = MAX_SEQ_LEN,
    dataset_num_proc   = 2,
    packing            = False,
    args = TrainingArguments(
        per_device_train_batch_size   = BATCH_SIZE,
        gradient_accumulation_steps   = GRAD_ACCUM,
        warmup_steps                  = 5,
        num_train_epochs              = EPOCHS,
        learning_rate                 = LR,
        fp16                          = not is_bfloat16_supported(),
        bf16                          = is_bfloat16_supported(),
        logging_steps                 = 10,
        optim                         = "adamw_8bit",
        weight_decay                  = 0.01,
        lr_scheduler_type             = "linear",
        seed                          = 3407,
        output_dir                    = str(OUTPUT_DIR / "checkpoints"),
        save_strategy                 = "epoch",
        report_to                     = "none",
    ),
)

print("[albedo-train] Starting training…")
trainer_stats = trainer.train()
print(f"[albedo-train] Training complete. Stats: {trainer_stats.metrics}")

# ── Save LoRA adapter ─────────────────────────────────────────────────────
adapter_path = OUTPUT_DIR / "lora_adapter"
model.save_pretrained(str(adapter_path))
tokenizer.save_pretrained(str(adapter_path))
print(f"[albedo-train] LoRA adapter saved → {adapter_path}")

# ── Merge + export GGUF ───────────────────────────────────────────────────
print("[albedo-train] Merging LoRA into base weights…")
model.save_pretrained_merged(
    str(OUTPUT_DIR / "merged"),
    tokenizer,
    save_method = "merged_16bit",
)
print("[albedo-train] Merge complete.")

print("[albedo-train] Exporting GGUF Q4_K_M…")
model.save_pretrained_gguf(
    str(OUTPUT_DIR / "gguf"),
    tokenizer,
    quantization_method = "q4_k_m",
)
print("[albedo-train] GGUF export complete.")
print(f"[albedo-train] ✓ All outputs in: {OUTPUT_DIR.resolve()}")
