from .base_loader import BaseLoader, RawDocument
from .json_loader import JSONLoader
from .csv_loader import CSVLoader
from .pdf_loader import PDFLoader
from .docx_loader import DOCXLoader
from .web_loader import WebLoader


LOADER_REGISTRY = {
    "json": JSONLoader,
    "csv": CSVLoader,
    "xlsx": CSVLoader,
    "pdf": PDFLoader,
    "docx": DOCXLoader,
    "web": WebLoader,
}


def get_loader(source_type: str) -> BaseLoader:
    key = source_type.strip().lower()

    loader_class = LOADER_REGISTRY.get(key)

    if loader_class is None:
        raise ValueError(
            f"Unsupported source type: {source_type}"
        )

    return loader_class()