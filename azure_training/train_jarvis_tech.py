"""
train_jarvis_tech.py — QLoRA fine-tune for JARVIS-Tech on Qwen2.5-7B-Instruct.

Uses the same base as Cortana/JARVIS but trained on the code + embedded + electronics
dataset. Produces a specialist technical agent with JARVIS-Tech persona baked in.

Base: Qwen/Qwen2.5-7B-Instruct (already cached from R3)
Dataset: /data/jarvis_tech_dataset_v1.jsonl
Output: /data/outputs/lora_adapter_jarvis_tech_r1

Usage:
    python3 train_jarvis_tech.py
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
BASE_MODEL   = "Qwen/Qwen2.5-7B-Instruct"
DATASET_PATH = "/data/jarvis_tech_dataset_v1.jsonl"
OUTPUT_DIR   = "/data/outputs/lora_adapter_jarvis_tech_r1"
HF_HOME      = os.environ.get("HF_HOME", "/data/hf_cache")
os.environ["HF_HOME"] = HF_HOME

LORA_RANK    = int(os.environ.get("LORA_RANK",    "32"))
LORA_ALPHA   = LORA_RANK * 2
LORA_DROPOUT = 0.05
EPOCHS       = int(os.environ.get("EPOCHS",       "10"))
BATCH_SIZE   = int(os.environ.get("BATCH_SIZE",   "1"))
GRAD_ACCUM   = int(os.environ.get("GRAD_ACCUM",   "16"))
MAX_SEQ_LEN  = int(os.environ.get("MAX_SEQ_LEN",  "1024"))
LR           = 2e-4

print(f"\n{'='*60}")
print(f"  JARVIS-Tech Training — Qwen2.5-7B-Instruct base")
print(f"  Rank: {LORA_RANK}  Alpha: {LORA_ALPHA}  Epochs: {EPOCHS}")
print(f"  Dataset: {DATASET_PATH}")
print(f"  Output: {OUTPUT_DIR}")
print(f"{'='*60}\n")

assert Path(DATASET_PATH).exists(), f"Dataset not found: {DATASET_PATH}"

# ── GPU check ─────────────────────────────────────────────────────────────────
if torch.cuda.is_available():
    props = torch.cuda.get_device_properties(0)
    print(f"GPU: {props.name} | VRAM: {props.total_memory/1e9:.1f} GB")
    USE_FP16 = props.major < 8
    USE_BF16 = not USE_FP16
else:
    print("WARNING: No GPU — training on CPU (slow)")
    USE_FP16 = USE_BF16 = False

# ── Tokenizer ─────────────────────────────────────────────────────────────────
print("Loading tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(
    BASE_MODEL, trust_remote_code=True, padding_side="right"
)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

# ── Model (4-bit QLoRA) ───────────────────────────────────────────────────────
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

lora_cfg = LoraConfig(
    r=LORA_RANK, lora_alpha=LORA_ALPHA, lora_dropout=LORA_DROPOUT,
    bias="none", task_type=TaskType.CAUSAL_LM,
    target_modules=["q_proj","k_proj","v_proj","o_proj",
                    "gate_proj","up_proj","down_proj"],
)
model = get_peft_model(model, lora_cfg)
model.print_trainable_parameters()
print(f"VRAM after model load: {torch.cuda.memory_allocated()/1e9:.2f} GB")

# ── Dataset ───────────────────────────────────────────────────────────────────
print(f"\nLoading dataset: {DATASET_PATH}")
raw = []
with open(DATASET_PATH, encoding="utf-8") as f:
    for line in f:
        if line.strip():
            raw.append(json.loads(line))
print(f"  {len(raw)} examples loaded")

def apply_template(ex):
    text = tokenizer.apply_chat_template(
        ex["messages"], tokenize=False, add_generation_prompt=False
    )
    return {"text": text}

dataset = Dataset.from_list(raw)
dataset = dataset.map(apply_template, remove_columns=["messages"])

def tokenize(ex):
    out = tokenizer(ex["text"], truncation=True, max_length=MAX_SEQ_LEN, padding=False)
    out["labels"] = out["input_ids"].copy()
    return out

dataset = dataset.map(tokenize, remove_columns=["text"])
print(f"  Tokenized. Training on {len(dataset)} examples.")

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

print(f"\nStarting JARVIS-Tech training — {EPOCHS} epochs, {steps_per_epoch} steps/epoch")
trainer.train()

print(f"\nSaving LoRA adapter to {OUTPUT_DIR}...")
model.save_pretrained(OUTPUT_DIR)
tokenizer.save_pretrained(OUTPUT_DIR)
print(f"Final loss: {trainer.state.log_history[-1].get('train_loss', 'n/a')}")
print("Done. Next: run merge step for jarvis-tech.")
