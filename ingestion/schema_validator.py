from typing import Any, Optional
import re

from pydantic import BaseModel, ValidationError

from ingestion.loaders.base_loader import RawDocument


def validate_documents(
    documents: list[RawDocument],
    schema_class: type[BaseModel],
    column_mapping: Optional[dict[str, Any]] = None,
) -> tuple[list[BaseModel], list[dict[str, Any]]]:
    """
    Validate RawDocument bằng Pydantic schema, hỗ trợ column_mapping tự động từ AI Chunk Planner.

    Returns:
        (valid_documents, errors)
    """
    valid: list[BaseModel] = []
    errors: list[dict[str, Any]] = []
    col_map = column_mapping or {}

    id_col = col_map.get("id_column")
    title_col = col_map.get("title_column")
    cat_col = col_map.get("category_column")
    alias_col = col_map.get("aliases_column")

    for index, document in enumerate(documents):
        metadata = dict(document.metadata or {})

        # 1. Trích xuất document_id
        doc_id = None
        if id_col and metadata.get(id_col) is not None:
            raw_id = str(metadata[id_col]).strip()
            if raw_id:
                doc_id = f"DOC_{int(raw_id):04d}" if raw_id.isdigit() else raw_id

        if not doc_id:
            for cand in ["document_id", "id", "stt", "mã", "ma", "code"]:
                if metadata.get(cand) is not None:
                    raw_id = str(metadata[cand]).strip()
                    if raw_id:
                        doc_id = f"DOC_{int(raw_id):04d}" if raw_id.isdigit() else raw_id
                        break

        metadata["document_id"] = doc_id or f"DOC_{index+1:04d}"
        document_id = metadata["document_id"]

        # 2. Trích xuất title riêng biệt cho từng dòng
        doc_title = None
        if title_col and metadata.get(title_col) is not None:
            raw_title = str(metadata[title_col]).strip()
            if raw_title:
                doc_title = raw_title

        if not doc_title:
            for cand in [
                "title", "name", "tên", "ten", "tên món", "tên món ăn", "ten_mon",
                "ten_mon_an", "dish_name", "recipe_name", "procedure_name", "tên thủ tục",
                "tiêu đề", "tên địa điểm", "tên bài viết", "chủ đề"
            ]:
                if metadata.get(cand) is not None:
                    raw_title = str(metadata[cand]).strip()
                    if raw_title:
                        doc_title = raw_title
                        break

        # Nếu là dữ liệu bảng (nhiều cột) mà chưa tìm thấy title, lấy cột string đầu tiên có độ dài <= 150
        if not doc_title and len(metadata) > 1:
            for k, v in metadata.items():
                if k not in ("document_id", id_col, "stt", "id", "_source_type", "source_type") and isinstance(v, str) and v.strip() and len(v.strip()) <= 150:
                    doc_title = v.strip()
                    break

        if not doc_title:
            from pathlib import Path
            src_stem = Path(document.source_path).stem if getattr(document, "source_path", None) else ""
            if len(documents) > 1:
                doc_title = f"{src_stem} - Mục {index+1}" if src_stem else f"Tài liệu {index+1}"
            else:
                doc_title = metadata.get("file_name") or src_stem or f"Tài liệu {index+1}"

        metadata["title"] = doc_title

        # 3. Trích xuất category
        doc_cat = None
        if cat_col and metadata.get(cat_col) is not None:
            doc_cat = str(metadata[cat_col]).strip()
        if not doc_cat:
            for cand in ["category", "loại", "loại món", "danh mục", "nhóm", "group"]:
                if metadata.get(cand) is not None:
                    doc_cat = str(metadata[cand]).strip()
                    break
        metadata["category"] = doc_cat or "chung"

        # 4. Trích xuất aliases
        if alias_col and metadata.get(alias_col) is not None:
            raw_aliases = metadata[alias_col]
            if isinstance(raw_aliases, str):
                metadata["aliases"] = [a.strip() for a in re.split(r"[,;|\n]", raw_aliases) if a.strip()]
            elif isinstance(raw_aliases, list):
                metadata["aliases"] = [str(a).strip() for a in raw_aliases if str(a).strip()]

        # 5. Enrich content: đảm bảo luôn có văn bản chi tiết
        # Bảo tồn nguồn gốc dữ liệu (_source_type)
        if "_source_type" in metadata:
            metadata.setdefault("source_type", metadata.pop("_source_type"))
        elif getattr(document, "metadata", None) and "_source_type" in document.metadata:
            metadata.setdefault("source_type", document.metadata["_source_type"])
        if not metadata.get("content"):
            if getattr(document, "raw_text", "") and str(document.raw_text).strip():
                metadata["content"] = str(document.raw_text).strip()
            else:
                # Tổng hợp tất cả các cột có giá trị trong metadata
                content_lines = [f"Tiêu đề: {metadata['title']}"]
                for k, v in metadata.items():
                    if k not in ("document_id", "title", "category", "source_url", "aliases") and v is not None and str(v).strip():
                        content_lines.append(f"{k}: {str(v).strip()}")
                metadata["content"] = "\n".join(content_lines)

        try:
            validated = schema_class.model_validate(metadata)
            valid.append(validated)

        except ValidationError as exc:
            errors.append({
                "index": index,
                "document_id": document_id,
                "errors": exc.errors(),
            })

    print(
        f"[schema_validator] "
        f"valid={len(valid)} "
        f"errors={len(errors)}"
    )

    return valid, errors
