"""
train_3b.py — QLoRA fine-tune for Qwen2.5-3B-Instruct persona models.

Produces lightweight (~1.8GB Q4_K_M) Cortana and JARVIS models that run in
~1.5GB VRAM on the RTX 2060 — fast local fallback for conversational queries
when the 7B model is busy or cloud is unavailable.

Usage:
    PERSONA=cortana python3 train_3b.py
    PERSONA=jarvis  python3 train_3b.py

Env overrides:
    LORA_RANK   (default 16 — 3B needs less capacity than 7B)
    EPOCHS      (default 12)
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
BASE_MODEL = "Qwen/Qwen2.5-3B-Instruct"
HF_HOME    = os.environ.get("HF_HOME", "/data/hf_cache")
os.environ["HF_HOME"] = HF_HOME

LORA_RANK    = int(os.environ.get("LORA_RANK",    "16"))
LORA_ALPHA   = LORA_RANK * 2
LORA_DROPOUT = 0.05
EPOCHS       = int(os.environ.get("EPOCHS",       "12"))
BATCH_SIZE   = int(os.environ.get("BATCH_SIZE",   "1"))
GRAD_ACCUM   = int(os.environ.get("GRAD_ACCUM",   "16"))
MAX_SEQ_LEN  = int(os.environ.get("MAX_SEQ_LEN",  "1024"))
LR           = 2e-4
OUTPUT_DIR   = f"/data/outputs/lora_adapter_{PERSONA}_3b"

# Use the latest dataset for each persona
DATASET_MAP = {
    "cortana": "/data/albedo_dataset_v4.jsonl",   # upgraded to v5 if available
    "jarvis":  "/data/jarvis_dataset_v3.jsonl",   # upgraded to v4 if available
}

# Prefer newer dataset if it exists
for persona, path in DATASET_MAP.items():
    newer = path.replace("v4", "v5").replace("v3", "v4")
    if Path(newer).exists():
        DATASET_MAP[persona] = newer

print(f"\n{'='*60}")
print(f"  3B Training — {PERSONA.upper()} persona")
print(f"  Base: {BASE_MODEL}")
print(f"  Rank: {LORA_RANK}  Alpha: {LORA_ALPHA}  Epochs: {EPOCHS}")
print(f"  Output: {OUTPUT_DIR}")
print(f"{'='*60}\n")

assert PERSONA in DATASET_MAP, f"Unknown PERSONA: {PERSONA}"
dataset_path = DATASET_MAP[PERSONA]
assert Path(dataset_path).exists(), f"Dataset not found: {dataset_path}"
print(f"Dataset: {dataset_path}")

# ── GPU ───────────────────────────────────────────────────────────────────────
if torch.cuda.is_available():
    props = torch.cuda.get_device_properties(0)
    print(f"GPU: {props.name} | VRAM: {props.total_memory/1e9:.1f} GB")
    USE_FP16 = props.major < 8
    USE_BF16 = not USE_FP16
else:
    USE_FP16 = USE_BF16 = False

# ── Tokenizer ─────────────────────────────────────────────────────────────────
tokenizer = AutoTokenizer.from_pretrained(
    BASE_MODEL, trust_remote_code=True, padding_side="right"
)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

# ── Model ─────────────────────────────────────────────────────────────────────
bnb = BitsAndBytesConfig(
    load_in_4bit=True, bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16, bnb_4bit_use_double_quant=True,
)
model = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL, quantization_config=bnb, device_map="auto", trust_remote_code=True
)
model.config.use_cache = False
model.enable_input_require_grads()

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
print(f"{len(raw)} examples loaded")

dataset = Dataset.from_list(raw)
dataset = dataset.map(
    lambda ex: {"text": tokenizer.apply_chat_template(
        ex["messages"], tokenize=False, add_generation_prompt=False
    )},
    remove_columns=["messages"]
)
dataset = dataset.map(
    lambda ex: {**tokenizer(
        ex["text"], truncation=True, max_length=MAX_SEQ_LEN, padding=False
    ), "labels": tokenizer(
        ex["text"], truncation=True, max_length=MAX_SEQ_LEN, padding=False
    )["input_ids"]},
    remove_columns=["text"]
)
print(f"Tokenized. Training on {len(dataset)} examples.")

# ── Training ──────────────────────────────────────────────────────────────────
steps_per_epoch = max(1, math.ceil(len(dataset) / (BATCH_SIZE * GRAD_ACCUM)))
save_steps      = max(steps_per_epoch * 2, 50)

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

print(f"\nStarting {PERSONA.upper()} 3B training — {EPOCHS} epochs, {steps_per_epoch} steps/epoch")
trainer.train()

model.save_pretrained(OUTPUT_DIR)
tokenizer.save_pretrained(OUTPUT_DIR)
print(f"Adapter saved to {OUTPUT_DIR}")
print(f"Final loss: {trainer.state.log_history[-1].get('train_loss', 'n/a')}")

del model
gc.collect()
torch.cuda.empty_cache()
