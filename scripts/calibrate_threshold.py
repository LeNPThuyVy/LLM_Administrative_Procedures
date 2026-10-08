from rag.retrieval import retrieve


DOMAIN = "administrative_procedures"

OUT_OF_SCOPE_QUERIES = [
    "Hôm nay thời tiết TP.HCM thế nào?",
    "Cách nấu phở bò ngon?",
    "iPhone mới nhất giá bao nhiêu?",
    "Gợi ý địa điểm du lịch Đà Lạt",
    "Đội tuyển Việt Nam đá trận tiếp theo khi nào?",
    "Viết cho tôi chương trình Python tính tổng hai số",
    "Cổ phiếu nào đáng đầu tư hiện nay?",
    "Tôi nên tập gym bao nhiêu buổi một tuần?",
    "Phim nào đang chiếu rạp hay?",
    "Dịch câu hello world sang tiếng Việt",
]


scores = []

print("=" * 90)
print("OUT-OF-SCOPE THRESHOLD CALIBRATION")
print("=" * 90)

for i, query in enumerate(OUT_OF_SCOPE_QUERIES, 1):
    results = retrieve(
        query=query,
        context={},
        top_k=3,
        domain=DOMAIN,
    )

    if not results:
        score = 0.0
        print(f"[{i:02}] score=0.000 | {query}")
        scores.append(score)
        continue

    top = results[0]
    score = float(getattr(top, "retrieval_score", 0.0))
    scores.append(score)

    doc_id = getattr(top, "document_id", None)

    if doc_id is None:
        metadata = getattr(top, "metadata", {}) or {}
        doc_id = metadata.get("document_id", "?")

    print(
        f"[{i:02}] score={score:.4f} | "
        f"doc={doc_id} | {query}"
    )


print("\n" + "=" * 90)
print("SUMMARY")
print("=" * 90)

print(f"Min OOD score : {min(scores):.4f}")
print(f"Max OOD score : {max(scores):.4f}")
print(f"Avg OOD score : {sum(scores) / len(scores):.4f}")

print("\nSorted scores:")
for score in sorted(scores):
    print(f"{score:.4f}")