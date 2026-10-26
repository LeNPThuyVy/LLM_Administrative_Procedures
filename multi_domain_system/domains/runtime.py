from typing import Any
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
    clarification_prompt: str
    system_prompt_rules: Any = ""
    answer_template: Any = ""
    search_backend: str = "qdrant"

@lru_cache(maxsize=None)
def _build_runtime(domain_id: str) -> DomainRuntime:
    config = load_domain_config(domain_id)

    clarification = getattr(config, "clarification_prompt", "")
    if not clarification:
        if domain_id == "administrative_procedures":
            clarification = (
                "Bạn muốn hỏi hoặc thực hiện thủ tục hành chính nào? "
                "Vui lòng cung cấp thêm thông tin cụ thể (ví dụ: đăng ký kết hôn, làm lại thẻ căn cước, cấp hộ chiếu, đăng ký khai sinh...) "
                "để tôi có thể hỗ trợ bạn chính xác nhất."
            )
        else:
            d_name = config.domain_name or domain_id
            clarification = (
                f"Bạn muốn tìm hiểu thông tin gì về {d_name}? "
                "Vui lòng cung cấp thêm thông tin cụ thể để tôi có thể hỗ trợ bạn chính xác nhất."
            )
    
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
        clarification_prompt=clarification,
        system_prompt_rules=getattr(config, "system_prompt_rules", ""),
        answer_template=getattr(config, "answer_template", ""),
        search_backend=getattr(config, "search_backend", "qdrant"),
    )

def get_domain_runtime(domain_id: str | None = None) -> DomainRuntime:
    if not domain_id:
        from my_config import DEFAULT_DOMAIN
        domain_id = DEFAULT_DOMAIN
    return _build_runtime(domain_id)
