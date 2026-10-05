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
        metadata = document.metadata

        document_id = metadata.get(
            "document_id",
            f"record_{index}",
        )

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