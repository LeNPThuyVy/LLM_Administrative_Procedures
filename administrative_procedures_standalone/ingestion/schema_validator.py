from typing import Any

from pydantic import BaseModel, ValidationError

from ingestion.loaders.base_loader import RawDocument


def validate_documents(
    documents: list[RawDocument],
    schema_class: type[BaseModel],
) -> tuple[list[BaseModel], list[dict[str, Any]]]:
    """
    Validate RawDocument bằng Pydantic schema.

    Returns:
        (
            valid_documents,
            errors
        )

    Mỗi error có index, document_id và chi tiết validation.
    """

    valid: list[BaseModel] = []
    errors: list[dict[str, Any]] = []

    for index, document in enumerate(documents):
        metadata = dict(document.metadata or {})

        # Enrich từ raw_text nếu là văn bản phi cấu trúc (PDF, DOCX)
        if not metadata.get("content") and getattr(document, "raw_text", ""):
            metadata["content"] = document.raw_text

        if not metadata.get("document_id"):
            metadata["document_id"] = f"DOC_{index+1:04d}"

        if not metadata.get("title"):
            from pathlib import Path
            src_stem = Path(document.source_path).stem if getattr(document, "source_path", None) else ""
            metadata["title"] = metadata.get("file_name") or src_stem or f"Tài liệu {index+1}"

        if "category" not in metadata:
            metadata["category"] = "chung"

        document_id = metadata["document_id"]

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