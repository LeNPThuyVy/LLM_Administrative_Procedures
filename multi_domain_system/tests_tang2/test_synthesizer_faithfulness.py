import pytest
from unittest.mock import patch
from rag.synthesizer import synthesizer, ConsolidatedQuery
from rag.retrieval import RetrievedChunk

def test_bypass_llm_for_clear_query():
    # Câu hỏi rõ ràng, không đại từ, có keyword thủ tục (ví dụ "đăng ký thường trú")
    query = "thủ tục đăng ký thường trú"
    history = {}
    procedure_hint = []
    
    # Mock generator - nó không nên được gọi
    def mock_generator(*args, **kwargs):
        raise RuntimeError("LLM should not be called")
        
    def mock_has_kw(q, extra="", *args, **kwargs):
        return "đăng ký thường trú" in q or "đăng ký thường trú" in extra or "cấp hộ chiếu" in q or "cấp hộ chiếu" in extra

    with patch("rag.synthesizer._has_specific_procedure_keyword", side_effect=mock_has_kw):
        result = synthesizer(
            query=query,
            history=history,
            procedure_hint=procedure_hint,
            generator=mock_generator,
            domain="administrative_procedures"
        )
    
    assert result.needs_clarification is False
    assert result.resolved_query == query


def test_faithfulness_fallback():
    # Câu hỏi follow-up
    query = "thời gian bao lâu?"
    history = {
        "recent_messages": [{"role": "user", "content": "đăng ký thường trú"}]
    }
    procedure_hint = [
        RetrievedChunk(
            chunk_id="1", document_id="1", content="", retrieval_score=0.9, 
            metadata={"title": "đăng ký thường trú"}
        )
    ]
    
    # Generator bịa ra con số không có trong allowed_text (12345)
    def mock_generator(*args, **kwargs):
        return '{"resolved_query": "thời gian giải quyết đăng ký thường trú là 12345 ngày", "original_query": "thời gian bao lâu?", "needs_clarification": false, "clarification_question": null}'
        
    with patch("rag.synthesizer._has_specific_procedure_keyword", side_effect=lambda q, extra="", *args, **kwargs: "đăng ký thường trú" in q or "đăng ký thường trú" in extra or "cấp hộ chiếu" in q or "cấp hộ chiếu" in extra):
        result = synthesizer(
            query=query,
            history=history,
            procedure_hint=procedure_hint,
            generator=mock_generator,
            domain="administrative_procedures"
        )
    
    # Do không faithful, nó sẽ fallback về original query ghép với thủ tục active
    assert result.resolved_query == "thời gian bao lâu? (liên quan đến: đăng ký thường trú)"
    assert result.needs_clarification is False


def test_followup_valid():
    query = "lệ phí bao nhiêu?"
    history = {
        "recent_messages": [{"role": "user", "content": "cấp hộ chiếu"}]
    }
    procedure_hint = []
    
    # Generator sinh chuẩn
    def mock_generator(*args, **kwargs):
        return '{"resolved_query": "lệ phí cấp hộ chiếu bao nhiêu", "original_query": "lệ phí bao nhiêu?", "needs_clarification": false, "clarification_question": null}'
        
    with patch("rag.synthesizer._has_specific_procedure_keyword", side_effect=lambda q, extra="", *args, **kwargs: "đăng ký thường trú" in q or "đăng ký thường trú" in extra or "cấp hộ chiếu" in q or "cấp hộ chiếu" in extra):
        result = synthesizer(
            query=query,
            history=history,
            procedure_hint=procedure_hint,
            generator=mock_generator,
            domain="administrative_procedures"
        )
    
    assert result.resolved_query == "lệ phí cấp hộ chiếu bao nhiêu"
    assert result.needs_clarification is False


def test_vague_procedure_query_requires_clarification():
    # Câu hỏi mơ hồ về thủ tục, kèm trợ từ tiếng Việt "á cậu", kèm procedure_hint giả định từ vector search
    query = "mình muốn hỏi thủ tục á cậu"
    history = {}
    procedure_hint = [
        RetrievedChunk(
            chunk_id="1", document_id="1", content="", retrieval_score=0.85,
            metadata={"title": "chứng thực chữ ký - chứng thực Hợp đồng giao dịch/Di chúc"}
        )
    ]

    def mock_generator(*args, **kwargs):
        raise RuntimeError("LLM should not be called for vague query")

    result = synthesizer(
        query=query,
        history=history,
        procedure_hint=procedure_hint,
        generator=mock_generator,
        domain="administrative_procedures"
    )

    assert result.needs_clarification is True
    assert result.clarification_question is not None
    assert "chứng thực" not in result.resolved_query


def test_greeting_query_requires_clarification():
    # Câu chào hỏi đơn thuần không có thủ tục
    query = "xin chào"
    history = {}
    procedure_hint = [
        RetrievedChunk(
            chunk_id="1", document_id="1", content="", retrieval_score=0.9,
            metadata={"title": "đăng ký khai sinh"}
        )
    ]

    def mock_generator(*args, **kwargs):
        raise RuntimeError("LLM should not be called for greeting")

    result = synthesizer(
        query=query,
        history=history,
        procedure_hint=procedure_hint,
        generator=mock_generator,
        domain="administrative_procedures"
    )

    assert result.needs_clarification is True
    assert result.clarification_question is not None


def test_get_active_procedure_ignores_hint():
    from rag.synthesizer import _get_active_procedure
    hints = [
        RetrievedChunk(
            chunk_id="1", document_id="1", content="", retrieval_score=0.9,
            metadata={"title": "thủ tục đăng ký kết hôn"}
        )
    ]
    # Khi history rỗng, không được lấy hint làm active procedure
    assert _get_active_procedure(history={}, procedure_hint=hints) == ""


def test_multiturn_window_10_turns_retrieves_active_procedure():
    # 7 lượt trước (14 messages), trong đó lượt 1 hỏi đăng ký thường trú
    messages = [
        {"role": "user", "content": "đăng ký thường trú"},
        {"role": "assistant", "content": "Hồ sơ đăng ký thường trú gồm tờ khai..."},
    ]
    for i in range(6):
        messages.append({"role": "user", "content": f"cho tôi hỏi thêm ý {i}"})
        messages.append({"role": "assistant", "content": f"Ý {i} là..."})

    history = {"recent_messages": messages}

    with patch("rag.synthesizer._has_specific_procedure_keyword", side_effect=lambda q, extra="", *args, **kwargs: "thường trú" in q or "thường trú" in extra):
        from rag.synthesizer import _get_active_procedure
        active = _get_active_procedure(history, domain="administrative_procedures")
        assert "thường trú" in active

        # Lượt 8: hỏi lệ phí bao nhiêu (follow-up)
        res = synthesizer(
            query="lệ phí bao nhiêu?",
            history=history,
            procedure_hint=[],
            domain="administrative_procedures",
        )
        assert res.needs_clarification is False
        assert "thường trú" in res.resolved_query


def test_derive_active_entity_from_evidence():
    from context.context_service import derive_active_entity

    # 1. Rỗng
    assert derive_active_entity([]) is None

    # 2. Chỉ có user
    assert derive_active_entity([{"role": "user", "content": "xin chào"}]) is None

    # 3. Assistant có evidence với citations
    messages = [
        {"role": "user", "content": "làm thủ tục cấp hộ chiếu"},
        {
            "role": "assistant",
            "content": "Để cấp hộ chiếu bạn cần chuẩn bị tờ khai...",
            "evidence": [
                {
                    "claim": "Cần chuẩn bị tờ khai TK01",
                    "status": "supported",
                    "citations": [
                        {
                            "document_id": "PROC_PASSPORT_01",
                            "title": "Thủ tục cấp hộ chiếu phổ thông",
                            "chunk_id": "c1",
                        }
                    ],
                }
            ],
        },
    ]

    entity = derive_active_entity(messages)
    assert entity is not None
    assert entity["doc_id"] == "PROC_PASSPORT_01"
    assert entity["title"] == "Thủ tục cấp hộ chiếu phổ thông"


def test_derive_active_entity_prefers_latest_assistant_turn():
    from context.context_service import derive_active_entity

    messages = [
        # Lượt 1: Hộ chiếu
        {"role": "user", "content": "hộ chiếu"},
        {
            "role": "assistant",
            "content": "Hộ chiếu...",
            "evidence": [{"citations": [{"document_id": "DOC_1", "title": "Cấp hộ chiếu"}]}],
        },
        # Lượt 2: Chuyển sang Chứng thực chữ ký
        {"role": "user", "content": "chứng thực chữ ký"},
        {
            "role": "assistant",
            "content": "Chứng thực...",
            "evidence": [{"citations": [{"document_id": "DOC_2", "title": "Chứng thực chữ ký"}]}],
        },
        {"role": "user", "content": "hết bao nhiêu tiền?"},
    ]

    entity = derive_active_entity(messages)
    assert entity is not None
    assert entity["doc_id"] == "DOC_2"
    assert entity["title"] == "Chứng thực chữ ký"


def test_slim_context_active_entity_integration_with_synthesizer():
    from context.context_service import derive_active_entity

    messages = [
        {"role": "user", "content": "tôi muốn đăng ký thường trú"},
        {
            "role": "assistant",
            "content": "Hồ sơ đăng ký thường trú...",
            "evidence": [
                {
                    "citations": [
                        {
                            "document_id": "PROC_001",
                            "title": "Đăng ký thường trú",
                        }
                    ]
                }
            ],
        },
    ]

    active_entity = derive_active_entity(messages)
    assert active_entity == {"doc_id": "PROC_001", "title": "Đăng ký thường trú"}

    # Giả lập history được build từ SLIM_CONTEXT
    history = {
        "recent_messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        "structured_context": {
            "procedure_name": active_entity["title"],
            "doc_id": active_entity["doc_id"],
        },
    }

    # Follow-up: hỏi hồ sơ gồm gì
    with patch("rag.synthesizer._has_specific_procedure_keyword", side_effect=lambda q, extra="", *args, **kwargs: "thường trú" in q or "thường trú" in extra or "Đăng ký thường trú" in extra):
        res = synthesizer(
            query="hồ sơ gồm những gì?",
            history=history,
            procedure_hint=[],
            domain="administrative_procedures",
        )
        assert res.needs_clarification is False
        assert "Đăng ký thường trú" in res.resolved_query


def test_location_check_domain_awareness():
    from rag.pipeline import _detect_unsupported_location

    # 1. Hành chính: chặn Đà Nẵng, Hà Nội
    assert _detect_unsupported_location("Tôi muốn làm thủ tục ở Đà Nẵng", domain="administrative_procedures") is True
    assert _detect_unsupported_location("Tôi muốn làm thủ tục ở Hà Nội", domain="administrative_procedures") is True
    assert _detect_unsupported_location("Tôi muốn làm thủ tục ở TP.HCM", domain="administrative_procedures") is False

    # 2. Du lịch (tourism_demo có Đà Nẵng, Hà Nội trong supported_locations): KHÔNG chặn
    assert _detect_unsupported_location("Đà Nẵng có gì chơi?", domain="tourism_demo") is False
    assert _detect_unsupported_location("Hà Nội mùa thu đi đâu?", domain="tourism_demo") is False


def test_field_intents_domain_awareness():
    from rag.prompt_builder import _detect_field_types

    # 1. Hành chính: nhận diện fee, docs, time, method
    assert "fee" in _detect_field_types("lệ phí bao nhiêu tiền?", domain="administrative_procedures")
    assert "docs" in _detect_field_types("cần chuẩn bị giấy tờ gì?", domain="administrative_procedures")

    # 2. Du lịch: không cấu hình field_intents -> không gắn rule hành chính
    assert _detect_field_types("giá vé bao nhiêu tiền?", domain="tourism_demo") == []
    assert _detect_field_types("cần chuẩn bị giấy tờ gì?", domain="tourism_demo") == []


def test_template_fast_path_disabled_for_tourism():
    from rag.pipeline import _try_template_fast_path
    from rag.evidence_builder import EvidenceCandidate

    mock_ev = EvidenceCandidate(
        candidate_id="EC_001",
        chunk_id="chunk_fee",
        document_id="DOC_001",
        content="Giá vé tham quan: 100.000đ",
        title="Du lịch Đà Nẵng",
        document_type="guide",
        page=1,
        source_url=None,
        retrieval_score=0.9,
        rerank_score=0.9,
    )

    # Khi domain là tourism_demo (chỉ có general chunk spec), fast path trả về None
    res = _try_template_fast_path(
        query="giá vé bao nhiêu?",
        evidence_candidates=[mock_ev],
        field_types=["fee"],
        domain="tourism_demo",
    )
    assert res is None


def test_cross_domain_session_resets_active_entity():
    from context.context_service import derive_active_entity

    messages = [
        {"role": "user", "content": "thủ tục kết hôn"},
        {
            "role": "assistant",
            "content": "Để đăng ký kết hôn...",
            "evidence": [
                {
                    "domain": "administrative_procedures",
                    "citations": [{"document_id": "PROC_004", "title": "Đăng ký kết hôn"}],
                }
            ],
        },
    ]

    # Cùng domain -> giữ active_entity
    same_domain_entity = derive_active_entity(messages, current_domain="administrative_procedures")
    assert same_domain_entity is not None
    assert same_domain_entity["title"] == "Đăng ký kết hôn"

    # Đổi sang domain du lịch -> reset active_entity (trả None)
    cross_domain_entity = derive_active_entity(messages, current_domain="tourism_demo")
    assert cross_domain_entity is None


def test_mode_resolution_strict_vs_friendly():
    from guardrails.risk import classify_risk, resolve_mode

    # 1. Hành chính: luôn strict
    risk_low = classify_risk("thủ tục đăng ký kết hôn")
    assert resolve_mode("strict", risk_low) == "strict"

    # 2. Du lịch: câu hỏi thông thường -> friendly
    risk_travel = classify_risk("Đà Nẵng có cây cầu nào đẹp?")
    assert resolve_mode("friendly", risk_travel) == "friendly"

    # 3. Du lịch: câu hỏi y tế / sức khỏe / thuốc -> tự động nâng lên strict
    risk_health = classify_risk("Đi du lịch bị đau bụng uống thuốc gì?")
    assert risk_health.force_strict is True
    assert resolve_mode("friendly", risk_health) == "strict"


def test_custom_domain_risk_keywords():
    from guardrails.risk import classify_risk, resolve_mode

    custom_kws = ["ngộ độc", "cấp cứu", "tai nạn"]

    # Câu hỏi chứa custom keyword
    risk = classify_risk("Tôi bị ngộ độc hải sản khi đi tour", domain_risk_keywords=custom_kws)
    assert risk.force_strict is True
    assert resolve_mode("friendly", risk) == "strict"


def test_apply_output_guard_mode_behavior():
    from guardrails.output import apply_output_guard

    answer = "Đà Nẵng có cầu Rồng rất đẹp."
    disclaimer = "Thông tin chỉ mang tính tham khảo."

    # Mode friendly: KHÔNG thêm disclaimer
    friendly_out = apply_output_guard(answer, mode="friendly", disclaimer=disclaimer)
    assert disclaimer not in friendly_out
    assert friendly_out == answer

    # Mode strict: BẮT BUỘC thêm disclaimer
    strict_out = apply_output_guard(answer, mode="strict", disclaimer=disclaimer)
    assert disclaimer in strict_out
    assert strict_out.endswith(disclaimer)


def test_all_three_domains_registered():
    from domains import list_domains, is_valid_domain

    available = list_domains()
    assert "administrative_procedures" in available
    assert "tourism_demo" in available
    assert "cuisine_demo" in available

    assert is_valid_domain("cuisine_demo") is True
    assert is_valid_domain("tourism_demo") is True
    assert is_valid_domain("administrative_procedures") is True
    assert is_valid_domain("non_existent_domain") is False


def test_cuisine_friendly_no_disclaimer():
    from domains.domain_loader import load_domain_config
    from guardrails.output import apply_output_guard

    cuisine_cfg = load_domain_config("cuisine_demo")
    assert cuisine_cfg.mode == "friendly"

    answer = "Phở bò Bát Đàn có nước dùng rất thanh và đậm đà."
    out = apply_output_guard(answer, mode=cuisine_cfg.mode, disclaimer="Disclaimer pháp lý")
    assert "Disclaimer" not in out
    assert out == answer


def test_cuisine_allergy_risk_escalation():
    from domains.domain_loader import load_domain_config
    from guardrails.risk import classify_risk, resolve_mode

    cuisine_cfg = load_domain_config("cuisine_demo")
    # Hỏi câu rủi ro sức khỏe / ngộ độc trong domain ẩm thực
    risk = classify_risk(
        "Ăn bún đậu mắm tôm bị ngộ độc nôn mửa thì phải làm sao?",
        domain_risk_keywords=cuisine_cfg.risk_keywords,
    )
    assert risk.force_strict is True
    assert resolve_mode(cuisine_cfg.mode, risk) == "strict"


def test_cross_domain_multi_switch():
    from context.context_service import derive_active_entity

    # Phiên trước trợ lý vừa trả lời về món ăn trong domain cuisine_demo
    messages = [
        {"role": "user", "content": "Phở bò Hà Nội ở đâu ngon?"},
        {
            "role": "assistant",
            "content": "Bạn có thể ghé Phở Bát Đàn.",
            "evidence": [
                {
                    "domain": "cuisine_demo",
                    "citations": [{"document_id": "CD001", "title": "Phở bò Hà Nội"}],
                }
            ],
        },
    ]

    # Vẫn ở domain ẩm thực -> active_entity được duy trì
    entity_cuisine = derive_active_entity(messages, current_domain="cuisine_demo")
    assert entity_cuisine is not None
    assert entity_cuisine["title"] == "Phở bò Hà Nội"

    # Người dùng nhảy sang hỏi thủ tục hành chính -> active_entity bị reset về None
    entity_admin = derive_active_entity(messages, current_domain="administrative_procedures")
    assert entity_admin is None

    # Người dùng nhảy sang hỏi du lịch -> active_entity bị reset về None
    entity_tour = derive_active_entity(messages, current_domain="tourism_demo")
    assert entity_tour is None






