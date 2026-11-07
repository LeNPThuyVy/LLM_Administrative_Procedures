"""
Chấm câu trả lời bằng cách đối chiếu với dữ liệu nguồn và hành vi mong đợi.

Đây KHÔNG phải kiểm định pháp lý: kết quả chỉ cho biết hệ thống có trả lời
đúng theo data/procedures.json hay không, không chứng minh dữ liệu đó đúng luật.

    python scripts/grade_against_db.py --out-dir docs/db_grading_YYYYMMDD
    python scripts/grade_against_db.py --cases domains/administrative_procedures/holdout_cases_20261107.json --out-dir docs/db_grading_YYYYMMDD

Cần Qdrant và llama-server đang chạy. Không ghi vào Qdrant hay DB.
"""
import argparse
import collections
import csv
import json
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from rag.verification import (
    _extract_numbers_from_text,
    _is_structural_header,
    _split_into_claims,
    _tokenize_meaningful,
)


DEFAULT_CASES = "domains/administrative_procedures/golden_set.json"
DATA_FILE = ROOT_DIR / "data" / "procedures.json"
DOMAIN = "administrative_procedures"

MIN_ITEM_OVERLAP = 0.6
MIN_GROUNDED_LINE_OVERLAP = 0.5
MIN_COMPLETENESS = 0.8
MIN_GROUNDED = 0.8

CORRECT = "DUNG"
INCOMPLETE = "THIEU"
WRONG = "SAI"
FALSE_REJECTION = "TU_CHOI_NHAM"
CORRECT_REJECTION = "TU_CHOI_DUNG"
LEAKED = "LOT_NGOAI_PHAM_VI"

FIELD_SOURCES = {
    "required_documents": ["required_documents"],
    "fee": ["fee"],
    "processing_time": ["processing_time"],
    "submission_method": ["submission_method", "submission_location"],
}

# Dòng không mang thông tin về thủ tục nên không cần có trong dữ liệu nguồn.
BOILERPLATE = re.compile(
    r"thông tin tư vấn tự động|liên hệ cơ quan|muốn hỏi thêm|"
    r"nguồn tham khảo|^\W*(\[?EC_\d+\]?\W*)*(\[?xxx\]?\W*)*$",
    flags=re.IGNORECASE,
)
LIST_ITEM_SPLIT = re.compile(r"\n+|;|(?<=[.!?])\s+|(?:^|\s)\d{1,2}[.)]\s+")


def expected_document_ids(raw) -> list[str]:
    values = raw if isinstance(raw, list) else str(raw or "").split(",")
    return [str(v).strip() for v in values if str(v).strip().startswith("PROC_")]


def _token_coverage(part: str, whole_tokens: set[str]) -> float:
    tokens = set(_tokenize_meaningful(part))
    if not tokens:
        return 1.0
    return len(tokens & whole_tokens) / len(tokens)


def field_items(value: str) -> list[str]:
    """Tách một trường dữ liệu thành các mục có nội dung."""
    items = [item.strip(" -+*\t") for item in LIST_ITEM_SPLIT.split(value or "")]
    return [item for item in items if len(_tokenize_meaningful(item)) >= 2]


def answer_lines(answer: str) -> list[str]:
    return [
        claim
        for claim in _split_into_claims(answer)
        if not BOILERPLATE.search(claim)
        and not _is_structural_header(claim)
        and _tokenize_meaningful(claim)
    ]


def grade_answer(
    answer: str,
    rejected: bool,
    cited_document_ids: set[str],
    records: list[dict],
    expected_field: str | None,
) -> dict:
    """Chấm một câu hỏi trong phạm vi theo bản ghi nguồn của thủ tục mong đợi."""
    if rejected:
        return {"verdict": FALSE_REJECTION, "reasons": ["từ chối câu hợp lệ"]}

    expected_ids = {record["document_id"] for record in records}
    source_text = "\n".join(
        str(value) for record in records for value in record.values()
    )
    source_tokens = set(_tokenize_meaningful(source_text))
    reasons = []

    if cited_document_ids and not cited_document_ids & expected_ids:
        reasons.append(f"sai thủ tục: {sorted(cited_document_ids)}")

    wrong_numbers = sorted(
        _extract_numbers_from_text(answer)
        - _extract_numbers_from_text(source_text)
    )
    if wrong_numbers:
        reasons.append(f"số không có trong DB: {wrong_numbers}")

    lines = answer_lines(answer)
    grounded_lines = [
        line for line in lines
        if _token_coverage(line, source_tokens) >= MIN_GROUNDED_LINE_OVERLAP
    ]
    grounded = len(grounded_lines) / len(lines) if lines else 0.0
    if grounded < MIN_GROUNDED:
        reasons.append(f"nội dung ngoài DB: {grounded:.0%} dòng có căn cứ")

    answer_tokens = set(_tokenize_meaningful(answer))
    items = [
        item
        for record in records
        for source_field in FIELD_SOURCES.get(expected_field or "", [])
        for item in field_items(str(record.get(source_field) or ""))
    ]
    covered = [
        item for item in items
        if _token_coverage(item, answer_tokens) >= MIN_ITEM_OVERLAP
    ]
    completeness = len(covered) / len(items) if items else 1.0

    if reasons:
        verdict = WRONG
    elif completeness < MIN_COMPLETENESS:
        verdict = INCOMPLETE
        reasons.append(f"đủ {len(covered)}/{len(items)} mục của trường")
    else:
        verdict = CORRECT

    return {
        "verdict": verdict,
        "reasons": reasons,
        "grounded": round(grounded, 3),
        "completeness": round(completeness, 3),
    }


def grade_out_of_scope(rejected: bool) -> dict:
    if rejected:
        return {"verdict": CORRECT_REJECTION, "reasons": []}
    return {"verdict": LEAKED, "reasons": ["trả lời câu ngoài phạm vi"]}


def is_out_of_scope(case: dict) -> bool:
    return (
        case.get("expected_behavior") == "REJECT"
        or not expected_document_ids(case.get("expected_document_id"))
    )


def summarize(rows: list[dict]) -> dict:
    counts = collections.Counter(row["verdict"] for row in rows)
    in_scope = sum(counts[v] for v in (CORRECT, INCOMPLETE, WRONG, FALSE_REJECTION))
    out_scope = counts[CORRECT_REJECTION] + counts[LEAKED]
    return {
        "total": len(rows),
        "counts": dict(counts),
        "in_scope": in_scope,
        "correct_pct": round(counts[CORRECT] / in_scope * 100, 1) if in_scope else 0.0,
        "out_of_scope": out_scope,
        "correct_rejection_pct": (
            round(counts[CORRECT_REJECTION] / out_scope * 100, 1) if out_scope else 0.0
        ),
        "scope_note": "Đối chiếu với dữ liệu nguồn, không phải kiểm định pháp lý",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cases", default=DEFAULT_CASES)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    from domains.runtime import get_domain_runtime
    from eval_golden_set import _is_rejection_response
    from rag.pipeline import answer_query

    cases = json.loads((ROOT_DIR / args.cases).read_text(encoding="utf-8"))
    records = {
        record["document_id"]: record
        for record in json.loads(DATA_FILE.read_text(encoding="utf-8"))
    }
    runtime = get_domain_runtime(DOMAIN)

    rows = []
    for case in cases:
        response = answer_query(query=case["question"], domain=DOMAIN)
        answer = response.answer or ""
        rejected = _is_rejection_response(response, runtime)

        if is_out_of_scope(case):
            grade = grade_out_of_scope(rejected)
        else:
            cited = {
                citation.document_id
                for claim in response.claims
                for citation in claim.citations
            }
            grade = grade_answer(
                answer,
                rejected,
                cited,
                [records[i] for i in expected_document_ids(case["expected_document_id"])],
                case.get("expected_field"),
            )

        rows.append({
            "id": case["id"],
            "question": case["question"],
            "expected_document_id": str(case.get("expected_document_id")),
            "expected_field": case.get("expected_field"),
            "answer": answer,
            **grade,
            "reasons": "; ".join(grade["reasons"]),
        })
        print(f"[{grade['verdict']}] {case['id']} {rows[-1]['reasons']}", flush=True)

    summary = summarize(rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.cases).stem
    (out_dir / f"{stem}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    fields = [
        "id", "verdict", "reasons", "grounded", "completeness",
        "expected_document_id", "expected_field", "question", "answer",
    ]
    with (out_dir / f"{stem}_cases.csv").open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
