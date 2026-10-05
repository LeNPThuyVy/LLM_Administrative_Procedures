from .base_loader import BaseLoader, RawDocument
from .json_loader import JSONLoader


LOADER_REGISTRY = {
    "json": JSONLoader,
}


def get_loader(source_type: str) -> BaseLoader:
    """
    Trả về loader tương ứng với source type.
    """
    key = source_type.strip().lower()

    loader_class = LOADER_REGISTRY.get(key)

    if loader_class is None:
        raise ValueError(
            f"Unsupported source type: {source_type}"
        )

    return loader_class()