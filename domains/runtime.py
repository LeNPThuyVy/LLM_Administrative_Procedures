from dataclasses import dataclass, field, fields
from functools import lru_cache
from domains.domain_loader import DomainConfig, load_domain_config

@dataclass
class DomainRuntime:
    domain_id: str
    config: DomainConfig
    collection_name: str
    mode: str
    risk_level: str
    persona: str
    assistant_role: str
    no_evidence_message: str
    disclaimer: str
    supported_locations: list[str]
    min_retrieval_score: float
    allowed_tools: list[str]
    entity_keywords: list[str]

@lru_cache(maxsize=None)
def _build_runtime(domain_id: str) -> DomainRuntime:
    config = load_domain_config(domain_id)
    
    return DomainRuntime(
        domain_id=domain_id,
        config=config,
        collection_name=config.collection_name,
        mode=config.mode,
        risk_level=config.risk_level,
        persona=config.persona,
        assistant_role=config.assistant_role,
        no_evidence_message=config.no_evidence_message,
        disclaimer=config.disclaimer,
        supported_locations=config.supported_locations,
        min_retrieval_score=config.min_retrieval_score,
        allowed_tools=config.allowed_tools,
        entity_keywords=config.entity_keywords,
    )

def get_domain_runtime(domain_id: str | None = None) -> DomainRuntime:
    if not domain_id:
        from my_config import DEFAULT_DOMAIN
        domain_id = DEFAULT_DOMAIN
    return _build_runtime(domain_id)
