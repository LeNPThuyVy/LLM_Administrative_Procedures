"""
Đánh giá mở rộng qua HTTP API thật (POST /api/chat, SSE).

Cần server đang chạy. Mặc định chạy các ca trong api_cases.csv của đợt 22/10
và xóa các session đã tạo sau khi xong.

    python scripts/run_extended_evaluation.py --url http://127.0.0.1:8002 --out-dir docs/extended_evaluation_YYYYMMDD
"""
import argparse
import csv
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

import httpx


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CASES = ROOT_DIR / "docs" / "extended_evaluation_20261022" / "api_cases.csv"

# update_memory chạy nền sau sự kiện done. Xóa sớm hơn sẽ khiến nó tạo lại session.
MEMORY_SETTLE_SECONDS = 5
FIELDS = [
    "case", "query", "http", "done", "latency_s", "first_content_s",
    "expected_doc", "observed_doc_ids", "expected_doc_found", "has_answer",
    "unsupported_claims", "unsupported_in_final_answer", "response_mode",
    "events", "error", "answer_preview",
]


def load_cases(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fp:
        return [
            {
                "case": row["case"],
                "query": row["query"],
                "expected_doc": row.get("expected_doc", ""),
            }
            for row in csv.DictReader(fp)
        ]


def iter_sse(response: httpx.Response):
    event, data = None, []
    for line in response.iter_lines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
        elif not line and event:
            yield event, "\n".join(data)
            event, data = None, []


def count_unsupported(evidence: list, answer: str) -> tuple[int, int]:
    unsupported = [
        item for item in evidence
        if isinstance(item, dict) and item.get("status") == "unsupported"
    ]
    in_answer = sum(
        1 for item in unsupported
        if item.get("claim") and item["claim"] in answer
    )
    return len(unsupported), in_answer


def run_case(client: httpx.Client, case: dict, session_id: str, domain: str) -> dict:
    result = {field: "" for field in FIELDS}
    result.update(case)
    events: list[str] = []
    done_payload: dict = {}
    first_content = None
    started = time.perf_counter()

    try:
        with client.stream(
            "POST",
            "/api/chat",
            json={"session_id": session_id, "query": case["query"], "domain": domain},
        ) as response:
            result["http"] = response.status_code
            for event, data in iter_sse(response):
                events.append(event)
                if first_content is None and event in ("chunk", "clarification", "section"):
                    first_content = time.perf_counter() - started
                if event == "done":
                    done_payload = json.loads(data) if data.startswith("{") else {}
    except httpx.HTTPError as exc:
        result["error"] = repr(exc)

    evidence = done_payload.get("evidence_list") or []
    answer = done_payload.get("answer") or ""
    doc_ids = sorted({
        str(citation.get("document_id"))
        for item in evidence if isinstance(item, dict)
        for citation in ([item] + (item.get("citations") or []))
        if isinstance(citation, dict) and citation.get("document_id")
    })
    unsupported, in_answer = count_unsupported(evidence, answer)

    result.update({
        "done": "done" in events,
        "latency_s": round(time.perf_counter() - started, 3),
        "first_content_s": round(first_content, 3) if first_content else "",
        "observed_doc_ids": ";".join(doc_ids),
        "expected_doc_found": (
            case["expected_doc"] in doc_ids if case["expected_doc"] else ""
        ),
        "has_answer": bool(answer.strip()),
        "unsupported_claims": unsupported,
        "unsupported_in_final_answer": in_answer,
        "response_mode": done_payload.get("mode") or "",
        "events": ";".join(sorted(set(events))),
        "answer_preview": answer[:300].replace("\n", " "),
    })
    return result


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 3)


def summarize(url: str, rows: list[dict]) -> dict:
    latencies = [row["latency_s"] for row in rows if row["done"]]
    scored = [row for row in rows if row["expected_doc"]]
    return {
        "source": "fresh real API execution",
        "endpoint": url,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cases": len(rows),
        "http200_done": sum(1 for row in rows if row["http"] == 200 and row["done"]),
        "error_count": sum(1 for row in rows if row["error"]),
        "latency_mean_s": round(statistics.mean(latencies), 3) if latencies else None,
        "latency_p50_s": percentile(latencies, 0.50),
        "latency_p95_s": percentile(latencies, 0.95),
        "unsupported_leak_cases": sum(
            1 for row in rows if row["unsupported_in_final_answer"]
        ),
        "expected_doc_hit_over_scored_cases": sum(
            1 for row in scored if row["expected_doc_found"] is True
        ),
        "scored_cases": len(scored),
        "scope_note": "Không phải đánh giá chính xác pháp lý",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8002")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--domain", default="administrative_procedures")
    parser.add_argument("--keep-sessions", action="store_true")
    args = parser.parse_args()

    rows: list[dict] = []
    session_ids: list[str] = []

    with httpx.Client(base_url=args.url, timeout=180, trust_env=False) as client:
        client.get("/api/session/bootstrap").raise_for_status()

        for case in load_cases(Path(args.cases)):
            created = client.post("/api/sessions/new")
            created.raise_for_status()
            session_id = created.json()["session_id"]
            session_ids.append(session_id)

            row = run_case(client, case, session_id, args.domain)
            rows.append(row)
            print(
                f"{row['case']}: http={row['http']} done={row['done']} "
                f"{row['latency_s']}s unsupported={row['unsupported_in_final_answer']}",
                flush=True,
            )

        if not args.keep_sessions:
            time.sleep(MEMORY_SETTLE_SECONDS)
            for session_id in session_ids:
                client.delete(f"/api/sessions/{session_id}").raise_for_status()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with (out_dir / "api_cases.csv").open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    summary = summarize(args.url, rows)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
