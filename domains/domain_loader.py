from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any
import warnings

import yaml


DOMAINS_DIR = Path(__file__).parent


@dataclass
class DomainConfig:
    domain_id: str = ""
    domain_name: str = ""
    description: str = ""

    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024

    collection_name: str = ""
    distance_metric: str = "cosine"

    chunk_fields: list[str] = field(default_factory=list)
    chunk_field_specs: dict[str, dict[str, Any]] = field(default_factory=dict)

    sources: list[dict[str, Any]] = field(default_factory=list)

    mode: str = "friendly"
    persona: str = "thân thiện, giản dị"
    risk_level: str = "low"

    dedup_threshold: float = 0.95


def load_domain_config(domain_id: str) -> DomainConfig:
    """
    Load config YAML của một domain.

    Quy tắc:
    - Key thiếu -> dùng default trong DomainConfig.
    - Key lạ -> bỏ qua và cảnh báo.
    - Không tồn tại config -> FileNotFoundError.
    """
    config_path = DOMAINS_DIR / domain_id / "config.yaml"

    if not config_path.exists():
        raise FileNotFoundError(
            f"Domain config not found: {config_path}"
        )

    raw = yaml.safe_load(
        config_path.read_text(encoding="utf-8")
    ) or {}

    if not isinstance(raw, dict):
        raise ValueError(
            f"Invalid YAML config format: {config_path}"
        )

    valid_keys = {f.name for f in fields(DomainConfig)}
    unknown_keys = set(raw.keys()) - valid_keys

    for key in sorted(unknown_keys):
        warnings.warn(
            f"[domain_loader] Unknown config key ignored: {key}",
            UserWarning,
        )

    filtered = {
        key: value
        for key, value in raw.items()
        if key in valid_keys
    }

    config = DomainConfig(**filtered)

    if not config.domain_id:
        config.domain_id = domain_id

    if not config.collection_name:
        config.collection_name = config.domain_id

    return config