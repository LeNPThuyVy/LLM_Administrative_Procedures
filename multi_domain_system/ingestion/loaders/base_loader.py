from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class RawDocument:
    """
    Document thô sau khi load từ nguồn,
    trước bước schema validation.
    """
    source_path: str
    raw_text: str
    metadata: dict


class BaseLoader(ABC):
    @abstractmethod
    def load(self, source_config: dict) -> list[RawDocument]:
        """
        Load dữ liệu từ source config.

        Returns:
            Danh sách RawDocument.
        """
        raise NotImplementedError