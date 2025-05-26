import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datasets import Dataset
from transformers import AutoTokenizer, AutoModelForSequenceClassification, Trainer
from sklearn.metrics import confusion_matrix, ConfusionMatrixDisplay

DATASET_SIZE = 100

# === Load test data ===
test_data_path = "data/test/grooming_test_dataset.csv"
test_df_full = pd.read_csv(test_data_path)

# Determine number of examples per class
n_per_class = DATASET_SIZE // 2

# Stratified sampling
test_df = (
    test_df_full
    .groupby("label", group_keys=False)
    .apply(lambda x: x.sample(n=n_per_class, random_state=42))
    .reset_index(drop=True)
)
test_dataset = Dataset.from_pandas(test_df[["text", "label"]])

# === Load tokenizer and model ===
model_path = "models/grooming-detector-20250525_164721"  # <-- Replace with actual timestamped path
tokenizer = AutoTokenizer.from_pretrained(model_path)
model = AutoModelForSequenceClassification.from_pretrained(model_path)

# === Tokenize test set ===
def tokenize(example):
    return tokenizer(example["text"], truncation=True, padding="max_length", max_length=512)

test_dataset = test_dataset.map(tokenize, batched=True)
test_dataset = test_dataset.rename_column("label", "labels")
test_dataset.set_format("torch")

# === Evaluate ===
trainer = Trainer(model=model, tokenizer=tokenizer)
predictions_output = trainer.predict(test_dataset)

preds = np.argmax(predictions_output.predictions, axis=-1)
labels = predictions_output.label_ids

cm = confusion_matrix(labels, preds)
disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=["Not Grooming", "Grooming"])
disp.plot(cmap=plt.cm.Blues)
plt.title("Confusion Matrix")
plt.show()