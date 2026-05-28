"""
train_r3.py — Round 3 QLoRA fine-tuning on Qwen2.5-7B-Instruct.

Trains fresh from base model on the combined v4/v3 datasets.
Saves LoRA adapters to /data/outputs/lora_adapter_{persona}_r3.

Usage:
    PERSONA=cortana python3 train_r3.py
    PERSONA=jarvis  python3 train_r3.py

Environment variables:
    PERSONA         cortana | jarvis
    LORA_RANK       LoRA rank (default 32)
    EPOCHS          training epochs (default 12)
    BATCH_SIZE      per-device batch size (default 1)
    GRAD_ACCUM      gradient accumulation steps (default 16)
    MAX_SEQ_LEN     max sequence length (default 1024)
"""

import os, gc, sys, json, math
import torch
from pathlib import Path
from datasets import Dataset
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    TrainingArguments,
    Trainer,
    DataCollatorForSeq2Seq,
    BitsAndBytesConfig,
)
from peft import LoraConfig, get_peft_model, TaskType

# ── Config ────────────────────────────────────────────────────────────────────
PERSONA      = os.environ.get("PERSONA", "cortana").lower()
BASE_MODEL   = "Qwen/Qwen2.5-7B-Instruct"
LORA_RANK    = int(os.environ.get("LORA_RANK",   "32"))
LORA_ALPHA   = LORA_RANK * 2
LORA_DROPOUT = 0.05
EPOCHS       = int(os.environ.get("EPOCHS",      "12"))
BATCH_SIZE   = int(os.environ.get("BATCH_SIZE",  "1"))
GRAD_ACCUM   = int(os.environ.get("GRAD_ACCUM",  "16"))
MAX_SEQ_LEN  = int(os.environ.get("MAX_SEQ_LEN", "1024"))
LR           = 2e-4
OUTPUT_DIR   = f"/data/outputs/lora_adapter_{PERSONA}_r3"
HF_HOME      = os.environ.get("HF_HOME", "/data/hf_cache")

DATASET_MAP  = {
    "cortana": "/data/albedo_dataset_v4.jsonl",
    "jarvis":  "/data/jarvis_dataset_v3.jsonl",
}

print(f"\n{'='*60}")
print(f"  Round 3 Training — {PERSONA.upper()} persona")
print(f"  Base:     {BASE_MODEL}")
print(f"  Rank:     {LORA_RANK}  Alpha: {LORA_ALPHA}")
print(f"  Epochs:   {EPOCHS}  Batch: {BATCH_SIZE}  GradAccum: {GRAD_ACCUM}")
print(f"  SeqLen:   {MAX_SEQ_LEN}  LR: {LR}")
print(f"  Output:   {OUTPUT_DIR}")
print(f"{'='*60}\n")

assert PERSONA in DATASET_MAP, f"Unknown PERSONA: {PERSONA}"
dataset_path = DATASET_MAP[PERSONA]
assert Path(dataset_path).exists(), f"Dataset not found: {dataset_path}"

# ── T4 GPU check ──────────────────────────────────────────────────────────────
if torch.cuda.is_available():
    props = torch.cuda.get_device_properties(0)
    print(f"GPU: {props.name} | VRAM: {props.total_memory/1e9:.1f} GB | CC: {props.major}.{props.minor}")
    USE_BF16 = props.major >= 8  # Ampere+
    USE_FP16 = not USE_BF16
    print(f"Precision: {'BF16' if USE_BF16 else 'FP16'}")
else:
    print("WARNING: No GPU detected — training on CPU (extremely slow)")
    USE_BF16 = False
    USE_FP16 = False

# ── Load tokenizer ────────────────────────────────────────────────────────────
print("\nLoading tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(
    BASE_MODEL,
    trust_remote_code=True,
    padding_side="right",
)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

# ── Load model with QLoRA 4-bit ───────────────────────────────────────────────
print("Loading base model in 4-bit...")
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_use_double_quant=True,
)
model = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL,
    quantization_config=bnb_config,
    device_map="auto",
    trust_remote_code=True,
)
model.config.use_cache = False
model.enable_input_require_grads()
print(f"Model loaded. VRAM: {torch.cuda.memory_allocated()/1e9:.2f} GB")

# ── LoRA config ───────────────────────────────────────────────────────────────
lora_config = LoraConfig(
    r=LORA_RANK,
    lora_alpha=LORA_ALPHA,
    lora_dropout=LORA_DROPOUT,
    bias="none",
    task_type=TaskType.CAUSAL_LM,
    target_modules=[
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    ],
)
model = get_peft_model(model, lora_config)
model.print_trainable_parameters()

# ── Dataset ───────────────────────────────────────────────────────────────────
print(f"\nLoading dataset: {dataset_path}")
raw = []
with open(dataset_path, encoding="utf-8") as f:
    for line in f:
        if line.strip():
            raw.append(json.loads(line))
print(f"  {len(raw)} examples loaded")

def apply_chat_template(example):
    messages = example["messages"]
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=False,
    )
    return {"text": text}

dataset = Dataset.from_list(raw)
dataset = dataset.map(apply_chat_template, remove_columns=["messages"])

def tokenize(example):
    out = tokenizer(
        example["text"],
        truncation=True,
        max_length=MAX_SEQ_LEN,
        padding=False,
    )
    out["labels"] = out["input_ids"].copy()
    return out

dataset = dataset.map(tokenize, remove_columns=["text"])
print(f"  Tokenized. Training on {len(dataset)} examples.")

# ── Training ──────────────────────────────────────────────────────────────────
steps_per_epoch = max(1, math.ceil(len(dataset) / (BATCH_SIZE * GRAD_ACCUM)))
save_steps = max(steps_per_epoch * 2, 50)

training_args = TrainingArguments(
    output_dir=OUTPUT_DIR,
    num_train_epochs=EPOCHS,
    per_device_train_batch_size=BATCH_SIZE,
    gradient_accumulation_steps=GRAD_ACCUM,
    gradient_checkpointing=True,
    learning_rate=LR,
    lr_scheduler_type="cosine",
    warmup_ratio=0.05,
    optim="paged_adamw_8bit",
    fp16=USE_FP16,
    bf16=USE_BF16,
    logging_steps=5,
    save_steps=save_steps,
    save_total_limit=2,
    dataloader_num_workers=0,
    group_by_length=True,
    report_to="none",
)

data_collator = DataCollatorForSeq2Seq(
    tokenizer=tokenizer,
    model=model,
    padding=True,
    pad_to_multiple_of=8,
)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=dataset,
    data_collator=data_collator,
)

print(f"\nStarting training — {EPOCHS} epochs, {steps_per_epoch} steps/epoch")
print(f"Effective batch size: {BATCH_SIZE * GRAD_ACCUM} ({BATCH_SIZE} × {GRAD_ACCUM} accum)")
trainer.train()

# ── Save adapter ──────────────────────────────────────────────────────────────
print(f"\nSaving LoRA adapter to {OUTPUT_DIR}...")
model.save_pretrained(OUTPUT_DIR)
tokenizer.save_pretrained(OUTPUT_DIR)
print(f"Adapter saved. Training complete.")

final_loss = trainer.state.log_history[-1].get("train_loss", "unknown")
print(f"Final train loss: {final_loss}")
print(f"\nNext step: run clean_merge_r3.sh to merge and convert to GGUF.")
