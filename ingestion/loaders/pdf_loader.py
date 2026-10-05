from pathlib import Path

from llama_index.core import SimpleDirectoryReader

from .base_loader import BaseLoader, RawDocument


class PDFLoader(BaseLoader):
    """
    Đọc PDF thành raw text bằng LlamaIndex.

    Field extraction từ PDF nằm ngoài phạm vi loader này.
    """

    def load(self, source_config: dict) -> list[RawDocument]:
        path_value = source_config.get("path")

        if not path_value:
            raise ValueError("PDF source config must contain 'path'")

        path = Path(path_value)

        if not path.exists():
            raise FileNotFoundError(f"PDF source not found: {path}")

        if path.is_file():
            reader = SimpleDirectoryReader(
                input_files=[str(path)]
            )
        else:
            reader = SimpleDirectoryReader(
                input_dir=str(path),
                required_exts=[".pdf"],
            )

        parsed = reader.load_data()

        return [
            RawDocument(
                source_path=str(path),
                raw_text=doc.text or "",
                metadata=dict(doc.metadata or {}),
            )
            for doc in parsed
        ]