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
    FieldChunker hỗ trợ 2 nhánh phân tách rõ ràng:
    1. Nhánh Tabular (Excel / CSV / Structured JSON):
       - Không chia nhỏ 1 dòng thành nhiều chunk.
       - Giữ nguyên toàn bộ schema 1 dòng theo format {tên cột}: {nội dung dòng}.
       - Bảo vệ an toàn chống cell overflow (ngưỡng 2500 ký tự).
    2. Nhánh Document (PDF / DOCX):
       - Chia chunk theo đoạn văn bản + sliding window overlap.
       - Gắn kèm Tiêu đề tài liệu ở đầu mỗi chunk.
    3. Nhánh Legacy Multi-field (procedures.json):
       - Duy trì tương thích ngược cho domain hành chính công có nhiều chunk_fields con.
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

        source_type = self._get_field_value(document, "source_type") or ""
        base_metadata = {
            "document_id": doc_id,
            "title": title,
            "domain": self.config.domain_id,
            "source_type": source_type,
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

        # =========================================================================
        # KIỂM TRA NHÁNH:
        # 1. Nếu là domain administrative_procedures HOẶC domain có nhiều chunk_fields
        #    thì chạy theo multi-field legacy chunking.
        # 2. Nếu là Tabular (Excel / CSV / Structured JSON):
        #    -> Chạy Nhánh 1: 1 dòng = 1 schema record {tên cột}: {nội dung dòng}.
        # 3. Nếu là Document (PDF / DOCX):
        #    -> Chạy Nhánh 2: Chia chunk theo đoạn văn + sliding window.
        # =========================================================================
        is_legacy_multi_field = (
            len(self.config.chunk_fields) > 1
            and any(f != "general" for f in self.config.chunk_fields)
        )

        if not is_legacy_multi_field:
            if source_type == "tabular":
                return self._chunk_tabular(document, base_metadata, aliases_list)
            elif source_type == "document":
                return self._chunk_document(document, base_metadata)
            else:
                # Mặc định: nếu chỉ có chunk 'general', kiểm tra xem content có cấu trúc cột hay không
                return self._chunk_tabular(document, base_metadata, aliases_list)

        # =========================================================================
        # NHÁNH 3: LEGACY MULTI-FIELD CHUNKING (Dành cho administrative_procedures)
        # =========================================================================
        chunks: list[Chunk] = []

        for field_name in self.config.chunk_fields:
            spec = self.config.chunk_field_specs.get(field_name)

            if not spec:
                continue

            suffix = spec.get("suffix", f"_{field_name}")
            label = spec.get("label", field_name)
            attr = spec.get("attr", field_name)
            source_cols = spec.get("source_columns", [])

            # GENERAL
            if field_name == "general":
                value = self._get_field_value(document, attr)

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
                            if col not in ("source_type", "_source_type") and c_val is not None and str(c_val).strip():
                                parts.append(f"{col}: {str(c_val).strip()}")
                        if parts:
                            value = "\n".join(parts)

                if value is None:
                    continue

                text = str(value).strip()
                if not text:
                    continue

                if title and not text.lower().startswith(title.lower()) and f"tiêu đề: {title.lower()}" not in text.lower():
                    text = f"Tiêu đề: {title}\n{text}"

                if aliases_list:
                    text += f"\nTừ khóa và tình huống liên quan: {', '.join(aliases_list)}"

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

            # FIELD VALUE / SPECIAL CHUNK
            parts: list[str] = []

            if source_cols:
                for col in source_cols:
                    c_val = self._get_field_value(document, col)
                    if c_val is not None and str(c_val).strip():
                        parts.append(f"{col}: {str(c_val).strip()}")
            else:
                value = self._get_field_value(document, attr)
                if value is not None and str(value).strip():
                    parts.append(str(value).strip())

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

    def _chunk_tabular(self, document: Any, base_metadata: dict, aliases_list: list[str]) -> list[Chunk]:
        """
        Nhánh 1: Tabular Schema Record.
        1 dòng = 1 Chunk chuẩn dạng {tên cột}: {nội dung dòng}.
        """
        doc_id = document.document_id
        title = document.title
        content = getattr(document, "content", None) or ""

        # Nếu content chưa có hoặc ngắn, xây dựng từ toàn bộ các cột trong model_extra
        lines = []
        if title:
            lines.append(f"Tiêu đề: {title}")

        if hasattr(document, "model_extra") and document.model_extra:
            for k, v in document.model_extra.items():
                if k in ("document_id", "title", "source_type", "_source_type", "aliases", "category", "source_url"):
                    continue
                if v is not None and str(v).strip():
                    lines.append(f"{k}: {str(v).strip()}")

        # Nếu model_extra không có, dùng content đã được tổng hợp ở validator
        if len(lines) <= 1 and content:
            record_text = content.strip()
        else:
            record_text = "\n".join(lines).strip()

        if aliases_list:
            record_text += f"\nTừ khóa liên quan: {', '.join(aliases_list)}"

        if not record_text:
            return []

        # Bảo vệ overflow: nếu 1 dòng quá 2500 ký tự mới cắt phụ
        chunks = []
        sub_texts = self._split_long_text(record_text, max_chars=2500, overlap=200)
        for idx, s_text in enumerate(sub_texts):
            chunk_id = f"{doc_id}_general" if len(sub_texts) == 1 else f"{doc_id}_general_{idx+1}"
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

        return chunks

    def _chunk_document(self, document: Any, base_metadata: dict) -> list[Chunk]:
        """
        Nhánh 2: Document Chunking cho PDF / DOCX.
        Chia theo đoạn văn bản + sliding window overlap. Luôn đính kèm Tiêu đề tài liệu.
        """
        doc_id = document.document_id
        title = document.title
        raw_text = getattr(document, "content", "") or getattr(document, "raw_text", "") or ""

        if not raw_text.strip():
            return []

        sub_texts = self._split_long_text(raw_text.strip(), max_chars=1200, overlap=200)
        chunks = []

        for idx, s_text in enumerate(sub_texts):
            # Luôn gắn kèm tiêu đề ở đầu chunk để giữ ngữ cảnh embedding
            chunk_text = f"Tài liệu: {title}\n{s_text}" if title and not s_text.startswith(title) else s_text
            chunk_id = f"{doc_id}_doc_{idx+1}"
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    text=chunk_text,
                    metadata={
                        **base_metadata,
                        "chunk_id": chunk_id,
                        "field": "document",
                    },
                )
            )

        return chunks
