import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "grade_against_db.py"
spec = importlib.util.spec_from_file_location("grade_against_db", SCRIPT)
grader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grader)


RECORD = {
    "document_id": "PROC_002",
    "title": "Thủ tục đăng ký khai sinh",
    "required_documents": (
        "- Giấy chứng sinh bản chính\n"
        "- Căn cước công dân của người đi đăng ký\n"
        "- Giấy chứng nhận kết hôn của cha mẹ"
    ),
    "processing_time": "1 ngày",
    "fee": "Bản sao: 8.000đ/bản",
}


def grade(answer, cited=None, field="required_documents", rejected=False):
    return grader.grade_answer(
        answer,
        rejected,
        {"PROC_002"} if cited is None else cited,
        [RECORD],
        field,
    )


FULL_ANSWER = (
    "Thành phần hồ sơ:\n"
    "1. Giấy chứng sinh bản chính\n"
    "2. Căn cước công dân của người đi đăng ký\n"
    "3. Giấy chứng nhận kết hôn của cha mẹ"
)


def test_full_answer_from_source_is_correct():
    assert grade(FULL_ANSWER)["verdict"] == grader.CORRECT


def test_disclaimer_does_not_count_as_unsupported_content():
    answer = FULL_ANSWER + "\n\nĐây là thông tin tư vấn tự động. Vui lòng liên hệ cơ quan nhà nước."

    assert grade(answer)["verdict"] == grader.CORRECT


def test_missing_items_are_incomplete():
    result = grade("Thành phần hồ sơ:\n1. Giấy chứng sinh bản chính")

    assert result["verdict"] == grader.INCOMPLETE
    assert "1/3" in result["reasons"][0]


def test_number_outside_source_is_wrong():
    result = grade("Lệ phí bản sao là 99.000đ/bản", field="fee")

    assert result["verdict"] == grader.WRONG
    assert "99000" in result["reasons"][0]


def test_citing_another_procedure_is_wrong():
    result = grade(FULL_ANSWER, cited={"PROC_004"})

    assert result["verdict"] == grader.WRONG
    assert "sai thủ tục" in result["reasons"][0]


def test_content_outside_source_is_wrong():
    result = grade(
        "Phải nộp thêm giấy phép lái xe quốc tế và lý lịch tư pháp nước ngoài",
    )

    assert result["verdict"] == grader.WRONG


def test_rejected_valid_question_is_false_rejection():
    assert grade(FULL_ANSWER, rejected=True)["verdict"] == grader.FALSE_REJECTION


def test_out_of_scope_grading():
    assert grader.grade_out_of_scope(True)["verdict"] == grader.CORRECT_REJECTION
    assert grader.grade_out_of_scope(False)["verdict"] == grader.LEAKED


def test_expected_document_ids_accepts_all_formats():
    assert grader.expected_document_ids("PROC_020, PROC_008") == ["PROC_020", "PROC_008"]
    assert grader.expected_document_ids(["PROC_027", "PROC_025"]) == ["PROC_027", "PROC_025"]
    assert grader.expected_document_ids("CLARIFY/NONE") == []


def test_out_of_scope_case_detection():
    assert grader.is_out_of_scope({"expected_behavior": "REJECT"}) is True
    assert grader.is_out_of_scope({"expected_document_id": "CLARIFY/NONE"}) is True
    assert grader.is_out_of_scope({"expected_document_id": "PROC_002"}) is False


def test_summary_never_claims_legal_review():
    summary = grader.summarize([
        {"verdict": grader.CORRECT},
        {"verdict": grader.WRONG},
        {"verdict": grader.CORRECT_REJECTION},
    ])

    assert summary["correct_pct"] == 50.0
    assert summary["correct_rejection_pct"] == 100.0
    assert "không phải kiểm định pháp lý" in summary["scope_note"]
