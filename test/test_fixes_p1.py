"""
Unit tests for P1 fixes:
1. Multi-intent quota retrieval in retrieve_two_step
2. Number/Date/Fee verification layer in verify_answer
3. Pre-structured evidence section labels in build_prompt
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from rag.retrieval import retrieve_two_step
from rag.verification import verify_answer, _check_number_conflict
from rag.evidence_builder import EvidenceCandidate
from rag.prompt_builder import build_prompt


def test_multi_intent_retrieval_quota():
    print("--- Test 1: Multi-intent retrieval quota ---")
    query = "Đăng ký khai sinh cần giấy tờ gì, mất bao lâu và lệ phí bao nhiêu?"
    chunks = retrieve_two_step(query=query, top_k=5)

    chunk_ids = [c.chunk_id for c in chunks]
    print(f"Query: {query}")
    print(f"Retrieved chunk IDs: {chunk_ids}")

    has_docs = any("_docs" in cid for cid in chunk_ids)
    has_fee = any("_fee" in cid for cid in chunk_ids)
    has_time = any("_time" in cid for cid in chunk_ids)

    print(f"Has _docs: {has_docs}, Has _fee: {has_fee}, Has _time: {has_time}")
    assert len(chunks) > 0, "Retrieval returned 0 chunks"
    assert has_docs or has_fee or has_time, "No field-specific chunks retrieved for multi-intent query"
    print("✓ Test 1 passed!\n")


def test_number_verification_layer():
    print("--- Test 2: Number/Date Verification Layer ---")
    evidence = EvidenceCandidate(
        candidate_id="EC_001",
        chunk_id="PROC_001_time",
        document_id="PROC_001",
        content="Thời gian giải quyết: Trong 03 ngày làm việc (nếu nhận hồ sơ sau 15 giờ thì trả kết quả vào ngày hôm sau). Lệ phí: Không thu phí.",
        title="Thủ tục xác nhận tình trạng hôn nhân",
        document_type="Thủ tục hành chính",
        page=1,
        source_url=None,
        retrieval_score=0.9,
        rerank_score=0.9
    )

    # 1. Correct number claim
    correct_answer = "Thời gian giải quyết là 3 ngày làm việc và không mất lệ phí. [EC_001]"
    results_correct = verify_answer(correct_answer, [evidence])
    print(f"Correct answer claim status: {results_correct[0].status}")
    assert results_correct[0].status == "supported", f"Expected supported, got {results_correct[0].status}"

    # 2. Hallucinated number claim
    hallucinated_answer = "Thời gian giải quyết là 7 ngày làm việc. [EC_001]"
    results_hallucinated = verify_answer(hallucinated_answer, [evidence])
    print(f"Hallucinated answer claim status: {results_hallucinated[0].status}")
    print(f"Hallucinated answer claim reason: {results_hallucinated[0].reason}")
    assert results_hallucinated[0].status == "unsupported", f"Expected unsupported, got {results_hallucinated[0].status}"
    print("✓ Test 2 passed!\n")


def test_structured_prompt_building():
    print("--- Test 3: Structured Prompt Building ---")
    evidence1 = EvidenceCandidate(
        candidate_id="EC_001",
        chunk_id="PROC_002_docs",
        document_id="PROC_002",
        content="Thành phần hồ sơ gồm: - Giấy chứng sinh (Bản chính)",
        title="Thủ tục đăng ký khai sinh",
        document_type="Thủ tục hành chính",
        page=1,
        source_url=None,
        retrieval_score=0.95,
        rerank_score=0.95
    )

    evidence2 = EvidenceCandidate(
        candidate_id="EC_002",
        chunk_id="PROC_002_fee",
        document_id="PROC_002",
        content="Lệ phí: Bản chính không thu phí. Bản sao 8.000đ/bản",
        title="Thủ tục đăng ký khai sinh",
        document_type="Thủ tục hành chính",
        page=1,
        source_url=None,
        retrieval_score=0.90,
        rerank_score=0.90
    )

    prompt = build_prompt(
        query="Đăng ký khai sinh cần giấy tờ gì và lệ phí bao nhiêu?",
        evidence_candidates=[evidence1, evidence2],
        context=None
    )

    print("Generated Prompt Preview:")
    print(prompt[:400])
    assert "[MỤC THÀNH PHẦN HỒ SƠ / GIẤY TỜ]" in prompt, "Missing structured section label for _docs"
    assert "[MỤC LỆ PHÍ / CHI PHÍ]" in prompt, "Missing structured section label for _fee"
    assert "multi-intent" in prompt, "Missing multi-intent guidance in prompt"
    print("✓ Test 3 passed!\n")


if __name__ == "__main__":
    test_multi_intent_retrieval_quota()
    test_number_verification_layer()
    test_structured_prompt_building()
    print("=== ALL P1 FIX UNIT TESTS PASSED SUCCESSFULLY! ===")
