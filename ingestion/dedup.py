import numpy as np
from dataclasses import dataclass


@dataclass
class DedupResult:
    kept: list
    removed: list[dict]


class SimilarityDeduplicator:
    def __init__(self, threshold: float = 0.95):
        self.threshold = threshold

    def deduplicate(
        self,
        documents: list,
        embeddings: list[list[float]],
    ) -> DedupResult:

        if not documents:
            return DedupResult(kept=[], removed=[])

        if len(documents) != len(embeddings):
            raise ValueError(
                "documents và embeddings phải có cùng số lượng"
            )

        vecs = np.asarray(embeddings, dtype=np.float32)

        norms = np.linalg.norm(
            vecs,
            axis=1,
            keepdims=True,
        )

        vecs = vecs / np.maximum(norms, 1e-10)

        similarity_matrix = vecs @ vecs.T

        removed_ids = set()
        removal_log = []

        n = len(documents)

        for i in range(n):
            doc_i = documents[i]

            if doc_i.document_id in removed_ids:
                continue

            for j in range(i + 1, n):
                doc_j = documents[j]

                if doc_j.document_id in removed_ids:
                    continue

                similarity = float(
                    similarity_matrix[i, j]
                )

                if similarity < self.threshold:
                    continue

                content_i = (
                    getattr(doc_i, "content", "") or ""
                )

                content_j = (
                    getattr(doc_j, "content", "") or ""
                )

                if len(content_i) >= len(content_j):
                    kept_doc = doc_i
                    removed_doc = doc_j
                else:
                    kept_doc = doc_j
                    removed_doc = doc_i

                removed_ids.add(
                    removed_doc.document_id
                )

                removal_log.append({
                    "removed_id": removed_doc.document_id,
                    "kept_id": kept_doc.document_id,
                    "similarity": round(similarity, 4),
                })

                print(
                    "[dedup] "
                    f"removed={removed_doc.document_id}, "
                    f"kept={kept_doc.document_id}, "
                    f"similarity={similarity:.4f}"
                )

                if removed_doc.document_id == doc_i.document_id:
                    break

        kept_documents = [
            doc
            for doc in documents
            if doc.document_id not in removed_ids
        ]

        return DedupResult(
            kept=kept_documents,
            removed=removal_log,
        )