from rag.evidence_builder import EvidenceCandidate
from rag.verification import filter_answer_by_verification, verify_answer


def _list_evidence(content):
    return [
        EvidenceCandidate(
            candidate_id="EC_001",
            document_id="PROC_011",
            chunk_id="PROC_011_docs",
            title="Đăng ký kết hôn",
            document_type="procedure",
            page=1,
            content=content,
            source_url="https://dichvucong.gov.vn",
            retrieval_score=0.95,
            rerank_score=0.95,
        )
    ]


def test_numbered_list_is_not_rejected_for_list_markers():
    """Số thứ tự không có trong bằng chứng không được làm mất cả câu trả lời."""
    evidence = _list_evidence(
        "Tờ khai theo mẫu quy định; Giấy tờ tùy thân bản chính; Giấy xác nhận tình trạng hôn nhân"
    )
    answer = (
        "Thành phần hồ sơ:\n"
        "1. Tờ khai theo mẫu quy định.\n"
        "2. Giấy tờ tùy thân bản chính.\n"
        "3. Giấy xác nhận tình trạng hôn nhân."
    )

    results = verify_answer(answer, evidence)
    filtered, kept, conflict = filter_answer_by_verification(answer, results)

    assert conflict is False
    assert "2. Giấy tờ tùy thân bản chính." in filtered
    assert "3. Giấy xác nhận tình trạng hôn nhân." in filtered
    assert len(kept) == 4


def test_numbered_list_item_with_fake_number_is_still_blocked():
    evidence = _list_evidence("Lệ phí đăng ký kết hôn là 50.000 đồng một lần")
    answer = "1. Lệ phí đăng ký kết hôn là 99.000 đồng một lần."

    results = verify_answer(answer, evidence)
    _, kept, conflict = filter_answer_by_verification(answer, results)

    assert results[0].status == "unsupported"
    assert kept == []
    assert conflict is True


def test_numbered_list_item_without_evidence_is_still_dropped():
    evidence = _list_evidence("Tờ khai theo mẫu quy định; Giấy tờ tùy thân bản chính")
    answer = (
        "1. Tờ khai theo mẫu quy định.\n"
        "2. Giấy phép lái xe hạng cao và lý lịch tư pháp quốc tế."
    )

    results = verify_answer(answer, evidence)
    filtered, _, _ = filter_answer_by_verification(answer, results)

    assert "Tờ khai" in filtered
    assert "lý lịch tư pháp" not in filtered


def test_trailing_number_in_sentence_is_still_checked():
    evidence = _list_evidence("Thời hạn giải quyết hồ sơ đăng ký là 5 ngày làm việc")
    answer = "Thời hạn giải quyết hồ sơ đăng ký là 15."

    results = verify_answer(answer, evidence)

    assert results[0].status == "unsupported"
