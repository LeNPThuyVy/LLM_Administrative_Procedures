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

    def _split_long_text(self, text: str, max_chars: int = 1400, overlap: int = 200) -> list[str]:
        """Chia văn bản dài theo đoạn văn có gối đầu (sliding window)."""
        if len(text) <= max_chars:
            return [text]

        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        chunks = []
        current_chunk = []
        current_len = 0

        for p in paragraphs:
            p_len = len(p)
            if current_len + p_len + 1 > max_chars and current_chunk:
                chunks.append("\n".join(current_chunk))
                # Giữ lại đoạn cuối làm overlap
                overlap_chunk = []
                overlap_len = 0
                for prev_p in reversed(current_chunk):
                    if overlap_len + len(prev_p) <= overlap:
                        overlap_chunk.insert(0, prev_p)
                        overlap_len += len(prev_p)
                    else:
                        break
                current_chunk = overlap_chunk
                current_len = overlap_len

            current_chunk.append(p)
            current_len += p_len + 1

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        return chunks if chunks else [text]

    def _get_field_value(self, document: Any, field_name: str) -> Any:
        """Đọc giá trị an toàn từ thuộc tính model hoặc model_extra."""
        val = getattr(document, field_name, None)
        if val is None and hasattr(document, "model_extra") and document.model_extra:
            val = document.model_extra.get(field_name)
        return val

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
            "aliases": getattr(
                document,
                "aliases",
                [],
            ) or [],
        }

        aliases_list = base_metadata["aliases"]
        chunks: list[Chunk] = []

        for field_name in self.config.chunk_fields:
            spec = self.config.chunk_field_specs.get(field_name)

            if not spec:
                continue

            suffix = spec.get("suffix", f"_{field_name}")
            label = spec.get("label", field_name)
            attr = spec.get("attr", field_name)
            source_cols = spec.get("source_columns", [])

            # =========================
            # GENERAL
            # =========================
            if field_name == "general":
                value = self._get_field_value(document, attr)

                # Nếu value rỗng, thử gom từ source_cols hoặc toàn bộ model_extra
                if not value:
                    if source_cols:
                        parts = []
                        for col in source_cols:
                            c_val = self._get_field_value(document, col)
                            if c_val is not None and str(c_val).strip():
                                parts.append(f"{col}: {str(c_val).strip()}")
                        if parts:
                            value = "\n".join(parts)
                    elif hasattr(document, "model_extra") and document.model_extra:
                        parts = []
                        for col, c_val in document.model_extra.items():
                            if c_val is not None and str(c_val).strip():
                                parts.append(f"{col}: {str(c_val).strip()}")
                        if parts:
                            value = "\n".join(parts)

                if value is None:
                    continue

                text = str(value).strip()
                if not text:
                    continue

                # Đảm bảo có title ở đầu chunk general
                if title and not text.lower().startswith(title.lower()) and f"tiêu đề: {title.lower()}" not in text.lower():
                    text = f"Tiêu đề: {title}\n{text}"

                if aliases_list:
                    text += f"\nTừ khóa và tình huống liên quan: {', '.join(aliases_list)}"

                # Cắt nhỏ nếu vượt quá CHUNK_SIZE
                sub_texts = self._split_long_text(text, max_chars=1400, overlap=200)
                for idx, s_text in enumerate(sub_texts):
                    chunk_id = f"{doc_id}{suffix}" if len(sub_texts) == 1 else f"{doc_id}{suffix}_{idx+1}"
                    chunks.append(
                        Chunk(
                            chunk_id=chunk_id,
                            text=s_text,
                            metadata={
                                **base_metadata,
                                "chunk_id": chunk_id,
                                "field": "general",
                            },
                        )
                    )

                continue

            # =========================
            # FIELD VALUE / SPECIAL CHUNK
            # =========================
            parts: list[str] = []

            # 1. Thu thập từ source_columns nếu có
            if source_cols:
                for col in source_cols:
                    c_val = self._get_field_value(document, col)
                    if c_val is not None and str(c_val).strip():
                        parts.append(f"{col}: {str(c_val).strip()}")
            else:
                value = self._get_field_value(document, attr)
                if value is not None and str(value).strip():
                    parts.append(str(value).strip())

            # 2. merge_with
            merge_fields = spec.get("merge_with", [])
            for merge_field in merge_fields:
                merge_value = self._get_field_value(document, merge_field)
                if merge_value is not None and str(merge_value).strip():
                    parts.append(str(merge_value).strip())

            if not parts:
                continue

            value_text = "\n".join(parts)
            full_field_text = (
                f"Tên: {title}\n"
                f"{label}:\n"
                f"{value_text}"
            )

            sub_texts = self._split_long_text(full_field_text, max_chars=1400, overlap=200)
            for idx, s_text in enumerate(sub_texts):
                chunk_id = f"{doc_id}{suffix}" if len(sub_texts) == 1 else f"{doc_id}{suffix}_{idx+1}"
                chunks.append(
                    Chunk(
                        chunk_id=chunk_id,
                        text=s_text,
                        metadata={
                            **base_metadata,
                            "chunk_id": chunk_id,
                            "field": field_name,
                        },
                    )
                )

        return chunks