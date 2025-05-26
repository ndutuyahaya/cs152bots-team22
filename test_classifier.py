import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datasets import Dataset
from transformers import AutoTokenizer, AutoModelForSequenceClassification, Trainer
from sklearn.metrics import confusion_matrix, ConfusionMatrixDisplay, classification_report, precision_recall_fscore_support

DATASET_SIZE = 1000
seed = 42
pos_split = 0.25
model_path = "models/grooming-detector-20250526_002419"
save_path = model_path + "/25_split_results"
test_data_path = "data/test/grooming_test_dataset.csv"

# === Load test data ===
test_df_full = pd.read_csv(test_data_path)

# Determine number of examples per class
n_positive = int(DATASET_SIZE * pos_split)
n_negative = DATASET_SIZE - n_positive

# Stratified sampling
positive_df = test_df_full[test_df_full["label"] == 1].sample(n=n_positive, random_state=seed)
negative_df = test_df_full[test_df_full["label"] == 0].sample(n=n_negative, random_state=seed)
test_df = pd.concat([positive_df, negative_df]).sample(frac=1, random_state=seed).reset_index(drop=True)
test_dataset = Dataset.from_pandas(test_df[["text", "label"]])

# === Load tokenizer and model ===
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

# === Confusion Matrix ===
cm = confusion_matrix(labels, preds)
disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=["Not Grooming", "Grooming"])
disp.plot(cmap=plt.cm.Blues)
plt.title("Confusion Matrix")

# Save confusion matrix
cm_path = f"{save_path}/confusion_matrix.png"
plt.savefig(cm_path)
print(f"Saved confusion matrix to: {cm_path}")

# === Prediction Results ===
results_df = test_df.copy()
results_df["predicted_label"] = preds
results_df["correct"] = results_df["label"] == results_df["predicted_label"]

# Save full prediction results
results_csv_path = f"{save_path}/test_results.csv"
results_df.to_csv(results_csv_path, index=False)
print(f"Saved test results to: {results_csv_path}")

# === Save metrics ===
precision, recall, f1, _ = precision_recall_fscore_support(labels, preds, average="binary")
metrics_dict = {
    "precision": precision,
    "recall": recall,
    "f1_score": f1,
    "accuracy": np.mean(results_df["correct"]),
}
metrics_path = f"{save_path}/test_metrics.csv"
pd.DataFrame([metrics_dict]).to_csv(metrics_path, index=False)
print(f"Saved metrics to: {metrics_path}")

# === Save misclassified examples ===
misclassified_df = results_df[~results_df["correct"]]
misclassified_path = f"{save_path}/misclassified.csv"
misclassified_df.to_csv(misclassified_path, index=False)
print(f"Saved misclassified examples to: {misclassified_path}")
