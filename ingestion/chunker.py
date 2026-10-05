from dataclasses import dataclass
from typing import Any

from domains.domain_loader import DomainConfig


@dataclass
class Chunk:
    chunk_id: str
    text: str
    metadata: dict


class FieldChunker:
    """
    Tách ProcedureDocument thành các chunk theo cấu hình domain.

    Không hardcode suffix / label trong code.
    Các thông tin này được đọc từ config.chunk_field_specs.
    """

    def __init__(self, config: DomainConfig):
        self.config = config

    def chunk(self, document: Any) -> list[Chunk]:
        doc_id = document.document_id
        title = document.title

        base_metadata = {
            "document_id": doc_id,
            "title": title,
            "domain": self.config.domain_id,
            "document_type": getattr(
                document,
                "document_type",
                "",
            ) or "",
            "category": getattr(
                document,
                "category",
                "",
            ) or "",
            "source_url": getattr(
                document,
                "source_url",
                "",
            ) or "",
        }

        chunks: list[Chunk] = []

        for field_name in self.config.chunk_fields:
            spec = self.config.chunk_field_specs.get(field_name)

            if not spec:
                continue

            suffix = spec.get("suffix", "")
            label = spec.get("label", "")
            attr = spec.get("attr", field_name)

            # =========================
            # GENERAL
            # =========================
            if field_name == "general":
                value = getattr(document, attr, None)

                if value is None:
                    continue

                text = str(value).strip()

                if not text:
                    continue

                chunk_id = f"{doc_id}{suffix}"

                chunks.append(
                    Chunk(
                        chunk_id=chunk_id,
                        text=text,
                        metadata={
                            **base_metadata,
                            "chunk_id": chunk_id,
                            "field": "general",
                        },
                    )
                )

                continue

            # =========================
            # FIELD VALUE
            # =========================
            value = getattr(document, attr, None)

            parts: list[str] = []

            if value is not None:
                value_text = str(value).strip()

                if value_text:
                    parts.append(value_text)

            # merge_with:
            # vd submission_method + submission_location
            merge_fields = spec.get("merge_with", [])

            for merge_field in merge_fields:
                merge_value = getattr(
                    document,
                    merge_field,
                    None,
                )

                if merge_value is None:
                    continue

                merge_text = str(merge_value).strip()

                if merge_text:
                    parts.append(merge_text)

            # Field rỗng / None -> không sinh chunk
            if not parts:
                continue

            value_text = "\n".join(parts)
            chunk_id = f"{doc_id}{suffix}"

            text = (
                f"Tên thủ tục: {title}\n"
                f"{label}:\n"
                f"{value_text}"
            )

            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    text=text,
                    metadata={
                        **base_metadata,
                        "chunk_id": chunk_id,
                        "field": field_name,
                    },
                )
            )

        return chunks