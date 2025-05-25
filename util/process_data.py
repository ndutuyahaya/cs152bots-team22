import xml.etree.ElementTree as ET
import pandas as pd

predator_ids_file_path = "../data/train/pan12-sexual-predator-identification-training-corpus-predators-2012-05-01.txt"
conversations_file_path = "../data/train/pan12-sexual-predator-identification-training-corpus-2012-05-01.xml"
output_file_path = "../data/train/grooming_train_dataset.csv"

with open(predator_ids_file_path, "r") as f:
    predator_ids = set(line.strip() for line in f if line.strip())

tree = ET.parse(conversations_file_path)
root = tree.getroot()

data = []

for conversation in root.findall("conversation"):
    conv_id = conversation.get("id")
    messages = conversation.findall("message")

    convo_text = []
    authors = set()

    for msg in messages:
        author = msg.find("author").text.strip()
        text_elem = msg.find("text")
        text = text_elem.text.strip() if text_elem is not None and text_elem.text else ""

        convo_text.append(f"{author}: {text}")
        authors.add(author)

    full_text = "\n".join(convo_text)
    label = int(bool(authors & predator_ids))  # 1 if any predator is present

    data.append({"id": conv_id, "text": full_text, "label": label})

df = pd.DataFrame(data)
df.to_csv(output_file_path, index=False)