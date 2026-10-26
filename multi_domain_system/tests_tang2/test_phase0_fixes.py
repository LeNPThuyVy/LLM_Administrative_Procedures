import pytest
from guardrails.output import apply_output_guard
from domains.runtime import get_domain_runtime, _build_runtime
from backend.api.chat import is_valid_domain
from rag.generator import LLMUnavailableError
from rag.pipeline import answer_query
from rag.retrieval import RetrievedChunk

def test_output_guard_keeps_agency_hotline():
    evidence = "Hotline cơ quan: 028 3829 1111 và tổng đài 19001234."
    
    # 028... is a landline, shouldn't be masked anyway
    result = apply_output_guard(
        "Hotline là 028 3829 1111, gọi ngay",
        "friendly",
        allowed_text=evidence
    )
    assert "028 3829 1111" in result
    
    # A random mobile number NOT in evidence should be masked
    result_mobile = apply_output_guard(
        "SĐT di động 0901234567",
        "friendly",
        allowed_text=evidence
    )
    assert "0901234567" not in result_mobile
    assert "[REDACTED_PHONE]" in result_mobile

def test_domain_runtime_cached():
    _build_runtime.cache_clear()
    
    rt1 = get_domain_runtime(None)
    rt2 = get_domain_runtime(None)
    
    # Same object identity due to lru_cache
    assert rt1 is rt2

def test_invalid_domain_returns_false():
    assert is_valid_domain("domain_khong_ton_tai") == False
    assert is_valid_domain(None) == True
    assert is_valid_domain("administrative_procedures") == True

@pytest.mark.asyncio
async def test_generator_no_subprocess_llm_down(monkeypatch):
    import rag.pipeline as pl
    
    # Mock generator to raise LLMUnavailableError
    def mock_generator(prompt, **kwargs):
        raise LLMUnavailableError("llama-server is down")

    # Mock procedure_reader to avoid heavy embedding/Qdrant call in unit test
    monkeypatch.setattr(pl, "procedure_reader", lambda **kwargs: [])
        
    # Mock retrieve_two_step to return a dummy chunk with high retrieval_score
    def mock_retrieve_two_step(query, context=None, domain=None, raw_results=None, top_k=None):
        return [RetrievedChunk(
            chunk_id="PROC_001_general",
            document_id="PROC_001",
            content="Thủ tục đăng ký kết hôn tại UBND cấp xã...",
            retrieval_score=0.9,
            metadata={"title": "Đăng ký kết hôn", "domain": "administrative_procedures"},
        )]

    monkeypatch.setattr(pl, "retrieve_two_step", mock_retrieve_two_step)

    response = pl.answer_query(
        "Thủ tục đăng ký kết hôn cần giấy tờ gì?",
        domain="administrative_procedures",
        generator=mock_generator,
        synthesizer_generator=mock_generator
    )
    
    assert response.answer == "Hệ thống đang bận, vui lòng thử lại sau ít phút."
