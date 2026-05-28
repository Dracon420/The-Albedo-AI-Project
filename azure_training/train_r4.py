"""
train_r4.py — Round 4 QLoRA fine-tune on Qwen2.5-7B-Instruct.

Differences from R3:
  - Rank 64 (vs 32) — denser persona embedding, better factual retention
  - 15 epochs (vs 12) — more training on larger dataset
  - Trained on v5/v4 datasets (larger, better coverage)
  - Seq length 2048 (vs 1024) — handles longer technical queries without truncation

Usage:
    PERSONA=cortana python3 train_r4.py
    PERSONA=jarvis  python3 train_r4.py
"""

import os, gc, json, math
import torch
from pathlib import Path
from datasets import Dataset
from transformers import (
    AutoTokenizer, AutoModelForCausalLM, TrainingArguments,
    Trainer, DataCollatorForSeq2Seq, BitsAndBytesConfig,
)
from peft import LoraConfig, get_peft_model, TaskType

# ── Config ────────────────────────────────────────────────────────────────────
PERSONA    = os.environ.get("PERSONA", "cortana").lower()
BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"
HF_HOME    = os.environ.get("HF_HOME", "/data/hf_cache")
os.environ["HF_HOME"] = HF_HOME

LORA_RANK    = int(os.environ.get("LORA_RANK",    "64"))
LORA_ALPHA   = LORA_RANK * 2
LORA_DROPOUT = 0.05
EPOCHS       = int(os.environ.get("EPOCHS",       "15"))
BATCH_SIZE   = int(os.environ.get("BATCH_SIZE",   "1"))
GRAD_ACCUM   = int(os.environ.get("GRAD_ACCUM",   "16"))
MAX_SEQ_LEN  = int(os.environ.get("MAX_SEQ_LEN",  "2048"))
LR           = 1.5e-4   # slightly lower LR for rank 64 stability
OUTPUT_DIR   = f"/data/outputs/lora_adapter_{PERSONA}_r4"

# Use latest available dataset — v5 for cortana, v4 for jarvis
# Falls back to previous version if new one not ready
DATASET_MAP = {
    "cortana": [
        "/data/albedo_dataset_v5_combined.jsonl",  # merged v4+v5
        "/data/albedo_dataset_v5.jsonl",
        "/data/albedo_dataset_v4.jsonl",
    ],
    "jarvis": [
        "/data/jarvis_dataset_v4_combined.jsonl",  # merged v3+v4
        "/data/jarvis_dataset_v4.jsonl",
        "/data/jarvis_dataset_v3.jsonl",
    ],
}

print(f"\n{'='*60}")
print(f"  Round 4 Training — {PERSONA.upper()} persona")
print(f"  Base: {BASE_MODEL}")
print(f"  Rank: {LORA_RANK}  Alpha: {LORA_ALPHA}")
print(f"  Epochs: {EPOCHS}  SeqLen: {MAX_SEQ_LEN}  LR: {LR}")
print(f"  Output: {OUTPUT_DIR}")
print(f"{'='*60}\n")

assert PERSONA in DATASET_MAP, f"Unknown PERSONA: {PERSONA}"

# Pick the first existing dataset
dataset_path = None
for candidate in DATASET_MAP[PERSONA]:
    if Path(candidate).exists():
        dataset_path = candidate
        break
assert dataset_path, f"No dataset found for {PERSONA}. Run generate_all_datasets.py first."
print(f"Dataset: {dataset_path}")

# ── GPU ───────────────────────────────────────────────────────────────────────
if torch.cuda.is_available():
    props = torch.cuda.get_device_properties(0)
    print(f"GPU: {props.name} | VRAM: {props.total_memory/1e9:.1f} GB | CC: {props.major}.{props.minor}")
    USE_FP16 = props.major < 8
    USE_BF16 = not USE_FP16
    print(f"Precision: {'BF16' if USE_BF16 else 'FP16'}")
else:
    USE_FP16 = USE_BF16 = False

# ── Tokenizer ─────────────────────────────────────────────────────────────────
tokenizer = AutoTokenizer.from_pretrained(
    BASE_MODEL, trust_remote_code=True, padding_side="right"
)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

# ── Model ─────────────────────────────────────────────────────────────────────
print("Loading base model in 4-bit QLoRA...")
bnb = BitsAndBytesConfig(
    load_in_4bit=True, bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16, bnb_4bit_use_double_quant=True,
)
model = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL, quantization_config=bnb, device_map="auto", trust_remote_code=True
)
model.config.use_cache = False
model.enable_input_require_grads()
print(f"VRAM: {torch.cuda.memory_allocated()/1e9:.2f} GB")

lora_cfg = LoraConfig(
    r=LORA_RANK, lora_alpha=LORA_ALPHA, lora_dropout=LORA_DROPOUT,
    bias="none", task_type=TaskType.CAUSAL_LM,
    target_modules=["q_proj","k_proj","v_proj","o_proj",
                    "gate_proj","up_proj","down_proj"],
)
model = get_peft_model(model, lora_cfg)
model.print_trainable_parameters()

# ── Dataset ───────────────────────────────────────────────────────────────────
raw = []
with open(dataset_path, encoding="utf-8") as f:
    for line in f:
        if line.strip():
            raw.append(json.loads(line))
print(f"{len(raw)} examples loaded from {dataset_path}")

dataset = Dataset.from_list(raw)
dataset = dataset.map(
    lambda ex: {"text": tokenizer.apply_chat_template(
        ex["messages"], tokenize=False, add_generation_prompt=False
    )},
    remove_columns=["messages"]
)

def tokenize(ex):
    out = tokenizer(ex["text"], truncation=True, max_length=MAX_SEQ_LEN, padding=False)
    out["labels"] = out["input_ids"].copy()
    return out

dataset = dataset.map(tokenize, remove_columns=["text"])
print(f"Tokenized. Training on {len(dataset)} examples.")

# ── Training ──────────────────────────────────────────────────────────────────
steps_per_epoch = max(1, math.ceil(len(dataset) / (BATCH_SIZE * GRAD_ACCUM)))
save_steps      = max(steps_per_epoch * 3, 75)

args = TrainingArguments(
    output_dir=OUTPUT_DIR, num_train_epochs=EPOCHS,
    per_device_train_batch_size=BATCH_SIZE,
    gradient_accumulation_steps=GRAD_ACCUM,
    gradient_checkpointing=True, learning_rate=LR,
    lr_scheduler_type="cosine", warmup_ratio=0.05,
    optim="paged_adamw_8bit", fp16=USE_FP16, bf16=USE_BF16,
    logging_steps=5, save_steps=save_steps, save_total_limit=2,
    dataloader_num_workers=0, group_by_length=True, report_to="none",
)

trainer = Trainer(
    model=model, args=args, train_dataset=dataset,
    data_collator=DataCollatorForSeq2Seq(tokenizer, model, padding=True, pad_to_multiple_of=8),
)

print(f"\nStarting R4 — {EPOCHS} epochs, {steps_per_epoch} steps/epoch")
print(f"Effective batch: {BATCH_SIZE * GRAD_ACCUM}")
trainer.train()

print(f"\nSaving adapter to {OUTPUT_DIR}...")
model.save_pretrained(OUTPUT_DIR)
tokenizer.save_pretrained(OUTPUT_DIR)
print(f"Final loss: {trainer.state.log_history[-1].get('train_loss', 'n/a')}")
print("Done. Run merge step for r4.")

del model
gc.collect()
torch.cuda.empty_cache()
