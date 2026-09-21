"""
Round 1 Test Suite — 2026-09-21

Tests the four canonical failure cases identified in the Fix Plan.
Uses the real RAG pipeline (rag.pipeline.answer_query) — no mocking.

Run with:
    C:\\Users\\MsVy\\AppData\\Local\\Programs\\Python\\Python312\\python.exe -X utf8 test_round1.py

Expected outcomes:
  Case 1: needs_clarification=True  (vague query, no procedure keyword)
  Case 2: fallback or clarification (out-of-dataset domain: immigration)
  Case 3: unsupported location response (Bình Dương not in HCMC dataset)
  Case 4: answer contains required_documents only, NOT fee/time/method
"""

import sys

# Import module (not just a value) so we always read the live last_model_used
import rag.hybrid_generator as _hybrid_gen

from rag.pipeline import (
    FALLBACK_TEXT,
    LOCATION_NOT_SUPPORTED_TEXT,
    answer_query,
)

# Soft fallback text that the LLM produces when evidence is insufficient
# (from prompt rule 7 — different from pipeline FALLBACK_TEXT)
_LLM_SOFT_FALLBACK = "thông tin trong"  # lowercase substring match


def _get_model_used() -> str:
    return _hybrid_gen.last_model_used


def _is_fallback(answer: str) -> bool:
    """Return True if answer is either the hard pipeline fallback
    or the soft LLM-generated fallback."""
    if not answer:
        return False
    a = answer.lower()
    return (
        FALLBACK_TEXT.lower() in a
        or _LLM_SOFT_FALLBACK in a
    )


def _header(n: int, description: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"CASE {n}: {description}")
    print("=" * 60)


def _show_result(result) -> None:
    print(f"  needs_clarification : {result.needs_clarification}")
    print(f"  clarification_q     : {result.clarification_question!r}")
    answer_preview = (result.answer or "")[:200].replace("\n", " ")
    print(f"  answer (preview)    : {answer_preview!r}")
    print(f"  model_used          : {_get_model_used()!r}")


def test_case_1():
    """
    Case 1: "Tôi muốn làm thủ tục"
    Expected: needs_clarification=True
    Issues: #1, #2, #3
    """
    _header(1, "Vague query — no specific procedure keyword")
    result = answer_query(
        query="Tôi muốn làm thủ tục",
        context={"recent_messages": []},
    )
    _show_result(result)

    passed = result.needs_clarification is True
    print(f"  PASS: {passed}  (expected needs_clarification=True)")
    return passed


def test_case_2():
    """
    Case 2: "Thủ tục nhập cảnh"
    Expected: fallback or clarification.
    'nhập cảnh' is not in the dataset; LLM should return soft or hard fallback,
    OR pipeline detects low relevance and returns needs_clarification / FALLBACK.

    Note from fix plan: Case 2 was already an incidental pass before fixes.
    We accept any of: needs_clarification=True, hard FALLBACK_TEXT, or LLM soft
    fallback ("Thông tin trong chưa đủ...").
    Issues: #1, #3
    """
    _header(2, "Out-of-dataset domain — immigration not in dataset")
    result = answer_query(
        query="Thủ tục nhập cảnh tại Việt Nam cần những giấy tờ gì?",
        context={"recent_messages": []},
    )
    _show_result(result)

    is_clarification = result.needs_clarification is True
    is_fallback = _is_fallback(result.answer or "")

    passed = is_fallback or is_clarification
    print(
        f"  PASS: {passed}  "
        f"(expected fallback or clarification; "
        f"got fallback={is_fallback}, clarification={is_clarification})"
    )
    return passed


def test_case_3():
    """
    Case 3: "...tại Bình Dương" — location not in HCMC dataset
    Expected: location-not-supported response
    Issues: #1, #3, #7
    """
    _header(3, "Unsupported location — Bình Dương (not HCMC)")
    context = {
        "recent_messages": [
            {"role": "user", "content": "Tôi đang hỏi về thủ tục hành chính tại Bình Dương."},
            {"role": "assistant", "content": "Bạn muốn hỏi thủ tục nào tại Bình Dương?"},
        ],
    }
    result = answer_query(
        query="Vậy cần chuẩn bị những giấy tờ gì?",
        context=context,
    )
    _show_result(result)

    passed = LOCATION_NOT_SUPPORTED_TEXT in (result.answer or "")
    print(
        f"  PASS: {passed}  "
        f"(expected location-not-supported response)"
    )
    return passed


def test_case_4():
    """
    Case 4: Ask ONLY for required_documents of PROC_001
    Expected: answer lists documents and does NOT include fee/processing_time/method
    Issues: #4, #5
    """
    _header(4, "Field-restriction — only documents for xác nhận tình trạng hôn nhân")
    result = answer_query(
        query=(
            "Thủ tục xác nhận tình trạng hôn nhân cần chuẩn bị "
            "những giấy tờ gì?"
        ),
        context={"recent_messages": []},
    )
    _show_result(result)

    answer = (result.answer or "").lower()

    has_docs_content = any(kw in answer for kw in [
        "hộ khẩu", "chứng minh nhân dân", "căn cước", "hộ chiếu",
        "ct07", "giấy tờ", "bản photo",
    ])

    # Unwanted fields should not appear
    has_unwanted_fee = "lệ phí" in answer or "không thu phí" in answer
    has_unwanted_time = "03 ngày" in answer or "thời gian giải quyết" in answer
    has_unwanted_method = "trực tuyến" in answer or "hình thức nộp" in answer

    has_unwanted = has_unwanted_fee or has_unwanted_time or has_unwanted_method

    passed = has_docs_content and not has_unwanted
    print(f"  has_docs_content    : {has_docs_content}")
    print(f"  has_unwanted_fee    : {has_unwanted_fee}")
    print(f"  has_unwanted_time   : {has_unwanted_time}")
    print(f"  has_unwanted_method : {has_unwanted_method}")
    print(f"  PASS: {passed}  (expected docs only, no fee/time/method)")
    return passed


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    results = [
        test_case_1(),
        test_case_2(),
        test_case_3(),
        test_case_4(),
    ]

    passed_count = sum(results)
    total = len(results)

    print(f"\n{'=' * 60}")
    print(f"ROUND 1 RESULTS: {passed_count}/{total} PASSED")
    print("=" * 60)

    sys.exit(0 if passed_count == total else 1)
