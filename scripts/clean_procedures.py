import json
import os
from collections import defaultdict

data_path = "data/procedures.json"

with open(data_path, "r", encoding="utf-8") as f:
    data = json.load(f)

# 1. Standardize category labels, add source_url, notes, submission_location
# 2. Check duplicates

title_counts = defaultdict(list)

for item in data:
    # 1a. Standardize category
    if "category" in item:
        cat = item["category"].strip().lower()
        if cat in ["giáo dục", "giáo dục và đào tạo"]:
            item["category"] = "Giáo dục và Đào tạo"
        elif cat in ["y tế", "sức khỏe"]:
            item["category"] = "Y tế"
        elif "đất đai" in cat:
            item["category"] = "Đất đai"
        elif "doanh nghiệp" in cat or "kinh doanh" in cat:
            item["category"] = "Doanh nghiệp"
        else:
            item["category"] = item["category"].capitalize()

    # 1b. Add source_url if missing
    if "source_url" not in item or not item["source_url"]:
        item["source_url"] = "https://dichvucong.hochiminhcity.gov.vn"

    # 1c. Add notes if missing
    if "notes" not in item:
        item["notes"] = ""

    # 1d. Add submission_location if missing
    if "submission_location" not in item or not item["submission_location"]:
        item["submission_location"] = "Bộ phận Tiếp nhận và Trả kết quả của cơ quan có thẩm quyền."

    # For duplicate checking
    title_counts[item["title"].strip()].append(item)

# Resolve duplicates by appending category or ID to title if there are exactly 3 duplicates? Wait, the requirement says "kiểm tra 3 tên trùng"
for title, items in title_counts.items():
    if len(items) > 1:
        # We append a distinguishing feature to the title
        for idx, it in enumerate(items):
            it["title"] = f"{it['title']} ({it.get('category', 'Khác')} - {idx+1})"

with open(data_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("Cleaned data successfully.")
