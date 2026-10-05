import json
from pathlib import Path

from .base_loader import BaseLoader, RawDocument


class JSONLoader(BaseLoader):
    """
    Loader cho dữ liệu JSON có cấu trúc.

    Hiện tại dùng cho data/procedures.json.
    Mỗi JSON record tương ứng một RawDocument.
    """

    def load(self, source_config: dict) -> list[RawDocument]:
        path_value = source_config.get("path")

        if not path_value:
            raise ValueError(
                "JSON source config must contain 'path'"
            )

        path = Path(path_value)

        if not path.exists():
            raise FileNotFoundError(
                f"JSON source not found: {path}"
            )

        records = json.loads(
            path.read_text(encoding="utf-8")
        )

        if not isinstance(records, list):
            raise ValueError(
                f"JSON source must contain a list of records: {path}"
            )

        documents: list[RawDocument] = []

        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise ValueError(
                    f"Record at index {index} is not an object"
                )

            documents.append(
                RawDocument(
                    source_path=str(path),
                    raw_text="",
                    metadata=record,
                )
            )

        return documents