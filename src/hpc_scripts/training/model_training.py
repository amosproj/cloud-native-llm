from huggingface_hub import HfApi, login
import os
HF_TOKEN = os.getenv('HF_TOKEN', 'add_hf_token')
api = HfApi()
login(HF_TOKEN, add_to_git_credential=True)

from transformers import AutoTokenizer, AutoModelForCausalLM
import transformers
from datasets import load_dataset
import torch
import re
from tqdm import tqdm
import pandas as pd
from datasets import Dataset
from peft import LoraConfig, PeftConfig
import bitsandbytes as bnb
import accelerate
from trl import SFTTrainer
from transformers import (AutoModelForCausalLM,
                          AutoModelForQuestionAnswering,
                          AutoTokenizer,
                          BitsAndBytesConfig,
                          TrainingArguments,
                          )


# training pipeline taken from https://huggingface.co/blog/gemma-peft
model_id = "google/gemma-1.1-7b-it"

bnb_config = BitsAndBytesConfig(
    load_in_8bit=True,
    bnb_8bit_quant_type="nf4",
    bnb_8bit_compute_dtype=torch.bfloat16
)

tokenizer = AutoTokenizer.from_pretrained(model_id, padding_side = 'right')
# TODO: Check if this can be changed to AutoModelForQuestionAnswering with GEMMA
model = AutoModelForCausalLM.from_pretrained(model_id, quantization_config=bnb_config, device_map="auto")

# Training Data
dataset = load_dataset("Kubermatic/cncf-question-and-answer-dataset-for-llm-training", split="train")


# Training (hyper)parameters (initial config taken from: https://medium.com/@lucamassaron/sherlock-holmes-q-a-enhanced-with-gemma-2b-it-fine-tuning-2907b06d2645)
max_seq_length = 1024


output_dir = "output"


training_arguments = TrainingArguments(
    output_dir=output_dir,
    num_train_epochs=3,
    gradient_checkpointing=True,
    per_device_train_batch_size=16,
    gradient_accumulation_steps=8,
    optim="paged_adamw_32bit",
    save_steps=0,
    logging_steps=10,
    learning_rate=5e-4,
    weight_decay=0.001,
    fp16=True,
    bf16=False,
    max_grad_norm=0.3,
    max_steps=-1,
    warmup_ratio=0.03,
    group_by_length=False,
    lr_scheduler_type="cosine",
    report_to="tensorboard",
    disable_tqdm=False,
    # debug="underflow_overflow"
)

text = "### Question: How does the `ScaleWorkload` function facilitate the scaling of a workload to specified replicas?"
device = "cuda:0"
inputs = tokenizer(text, return_tensors="pt").to(device)

outputs = model.generate(**inputs, max_new_tokens=500)
print(tokenizer.decode(outputs[0], skip_special_tokens=True))

def formatting_func(example):
    output_texts = []
    for i in range(len(example['Question'])):
        text = f"### Question: {example['Question'][i]}\n ### Answer: {example['Answer'][i]}<eos>"
        output_texts.append(text)
    return output_texts

lora_config = LoraConfig(
    lora_alpha=16,
    lora_dropout=0,
    r=64,
    bias="none",
    target_modules=["q_proj", "o_proj", "k_proj", "v_proj", "gate_proj", "up_proj", "down_proj"],
    # TODO: Check if this can be changed to QUESTION_ANS with GEMMA
    task_type="CAUSAL_LM",
)


trainer = SFTTrainer(
    model=model,
    train_dataset=dataset,
    args=training_arguments,
    peft_config=lora_config,
    formatting_func=formatting_func,
    tokenizer=tokenizer,
    max_seq_length=max_seq_length,
)
trainer.train()
print("Model is trained")

text = "### Question: How does the `ScaleWorkload` function facilitate the scaling of a workload to specified replicas?"
device = "cuda:0"
inputs = tokenizer(text, return_tensors="pt").to(device)

outputs = model.generate(**inputs, max_new_tokens=500)
print(tokenizer.decode(outputs[0], skip_special_tokens=True))

# Save model
trainer.save_model()
tokenizer.save_pretrained(output_dir)
