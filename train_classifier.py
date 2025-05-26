import pandas as pd
import numpy as np
from datasets import Dataset
from transformers import (
    AutoTokenizer, AutoModelForSequenceClassification,
    TrainingArguments, Trainer, EarlyStoppingCallback,
    TrainerCallback
)
import evaluate
from datetime import datetime
from sklearn.metrics import accuracy_score
import os
import csv
import torch

DATASET_SIZE = 4000

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Using device: {device}")

# === File path ===
train_data_path = "data/train/grooming_train_dataset.csv"

# === Load and split dataset ===
train_df_full = pd.read_csv(train_data_path)
n_per_class = DATASET_SIZE // 2

# Stratified sampling
train_df = (
    train_df_full
    .groupby("label", group_keys=False)
    .apply(lambda x: x.sample(n=n_per_class, random_state=42))
    .reset_index(drop=True)
)

hf_dataset = Dataset.from_pandas(train_df[["text", "label"]])
split_dataset = hf_dataset.train_test_split(test_size=0.2, seed=42)
train_dataset = split_dataset["train"]
val_dataset = split_dataset["test"]

# === Tokenization ===
tokenizer = AutoTokenizer.from_pretrained("distilbert-base-uncased")

def tokenize(example):
    return tokenizer(example["text"], truncation=True, padding="max_length", max_length=512)

train_dataset = train_dataset.map(tokenize, batched=True)
val_dataset = val_dataset.map(tokenize, batched=True)
train_dataset = train_dataset.rename_column("label", "labels")
val_dataset = val_dataset.rename_column("label", "labels")
train_dataset.set_format("torch")
val_dataset.set_format("torch")

# === Model ===
model = AutoModelForSequenceClassification.from_pretrained("distilbert-base-uncased", num_labels=2)
model.to(device)

# === Metrics ===
accuracy = evaluate.load("accuracy")
f1 = evaluate.load("f1")

def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = logits.argmax(axis=-1)
    return {
        "accuracy": accuracy.compute(predictions=preds, references=labels)["accuracy"],
        "f1": f1.compute(predictions=preds, references=labels, average="binary")["f1"],
    }

# === Timestamped output directory ===
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
save_dir = f"models/grooming-detector-{timestamp}"
metrics_file = f"{save_dir}/training_metrics.csv"
os.makedirs(save_dir, exist_ok=True)

# === Training Args ===
training_args = TrainingArguments(
    output_dir=save_dir,
    eval_strategy="epoch",
    save_strategy="epoch",
    logging_strategy="epoch",
    per_device_train_batch_size=8,
    per_device_eval_batch_size=8,
    num_train_epochs=10,
    learning_rate=2e-5,
    weight_decay=0.01,
    load_best_model_at_end=True,
    metric_for_best_model="f1",
    greater_is_better=True,
    logging_dir=f"{save_dir}/logs",
    report_to="none",
    save_total_limit=1,
)

# === Custom callback to write metrics to CSV ===
class CSVLoggerCallback(TrainerCallback):
    def __init__(self, filename):
        self.filename = filename
        with open(self.filename, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["epoch", "train_loss", "eval_loss", "eval_accuracy", "eval_f1"])

    def on_log(self, args, state, control, logs=None, **kwargs):
        if logs is None or "eval_loss" not in logs:
            return
        with open(self.filename, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                state.epoch,
                logs.get("loss", ""),
                logs.get("eval_loss", ""),
                logs.get("eval_accuracy", ""),
                logs.get("eval_f1", "")
            ])

    # Add this to avoid the AttributeError
    def on_init_end(self, args, state, control, **kwargs):
        return control
    
# === Trainer ===
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=val_dataset,
    tokenizer=tokenizer,
    compute_metrics=compute_metrics,
    callbacks=[
        EarlyStoppingCallback(early_stopping_patience=2),
        CSVLoggerCallback(metrics_file)
    ],
)

# === Train and save ===
trainer.train()
trainer.save_model(save_dir)
tokenizer.save_pretrained(save_dir)

print(f"Model saved to: {save_dir}")

# === Evaluate final train accuracy ===
train_predictions = trainer.predict(train_dataset)
train_preds = np.argmax(train_predictions.predictions, axis=-1)
train_labels = train_predictions.label_ids
train_accuracy = accuracy_score(train_labels, train_preds)
print(f"Final Train Accuracy: {train_accuracy:.4f}")