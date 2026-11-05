from __future__ import annotations

import logging
import re
from rag.pipeline_guards import FALLBACK_TEXT

logger = logging.getLogger(__name__)


def answer_from_evidence(evidence_candidates, field_types: list[str] | None = None) -> str:
    """
    Nếu LLM không tạo được câu trả lời hữu ích,
    dùng trực tiếp evidence tốt nhất có chứa thông tin cần tìm.
    """
    if not evidence_candidates:
        return FALLBACK_TEXT

    # Nếu chỉ cần docs, tìm chunk có chứa "Thành phần hồ sơ:"
    if field_types and "docs" in field_types and len(field_types) == 1:
        for ev in evidence_candidates:
            content = (ev.content or "").strip()
            if "Thành phần hồ sơ:" in content:
                docs_part = content.split("Thành phần hồ sơ:")[1]
                return f"Thành phần hồ sơ:\n{docs_part.strip()} [{ev.candidate_id}]"

    # Nếu không filter được hoặc filter thất bại, trả về các chunk phù hợp (loại bỏ lặp Tên thủ tục)
    parts = []
    seen_titles = set()

    # 1. Ưu tiên chunk general: tìm các document_id có chunk _general
    general_docs = {
        ev.document_id for ev in evidence_candidates
        if ev.chunk_id and ev.chunk_id.endswith("_general")
    }

    for ev in evidence_candidates:
        if ev.document_id in general_docs and not (ev.chunk_id and ev.chunk_id.endswith("_general")):
            continue

        content = (ev.content or "").strip()
        if not content:
            continue

        title_match = re.search(r"^Tên thủ tục: (.*?)\n", content)
        if title_match:
            title = title_match.group(1).strip()
            if title not in seen_titles:
                parts.append(f"Tên thủ tục: {title}")
                seen_titles.add(title)
            content = content.replace(title_match.group(0), "").strip()

        if content:
            parts.append(f"{content} [{ev.candidate_id}]")

    if parts:
        return "\n\n".join(parts)

    return FALLBACK_TEXT


def try_template_fast_path(
    query: str,
    evidence_candidates,
    field_types: list[str],
    domain: str | None = None,
) -> str | None:
    """
    Bước 3A Template Fast Path:
    Khi query chỉ hỏi đúng 1 field (fee, time, method, docs) và domain có chunk_field_specs tương ứng,
    kết xuất câu trả lời chuẩn trực tiếp, bỏ qua LLM sinh token để giảm độ trễ từ ~3s về <0.1s.
    """
    if not field_types or len(field_types) != 1 or not evidence_candidates:
        return None

    from domains.runtime import get_domain_runtime
    runtime = get_domain_runtime(domain)
    if not runtime.config.chunk_field_specs or list(runtime.config.chunk_field_specs.keys()) == ["general"]:
        return None

    ftype = field_types[0]
    specs = runtime.config.chunk_field_specs

    ftype_map = {
        "fee": "fee",
        "time": "processing_time",
        "method": "submission_method",
        "docs": "required_documents",
    }
    spec_key = ftype_map.get(ftype)
    if not spec_key or spec_key not in specs:
        return None

    target_suffix = specs[spec_key].get("suffix")
    target_label = specs[spec_key].get("label", "")

    for ev in evidence_candidates:
        if ev.chunk_id and ev.chunk_id.endswith(target_suffix):
            content = (ev.content or "").strip()
            if not content:
                continue
            title = ev.title or ""
            if not title:
                m = re.search(r"^Tên thủ tục: (.*?)\n", content)
                if m:
                    title = m.group(1).strip()
            body = content
            prefix_pattern = rf"^(?:Tên thủ tục: [^\n]+\n+)?(?:{re.escape(target_label)}:\s*)"
            body = re.sub(prefix_pattern, "", body, flags=re.IGNORECASE).strip()
            if not body:
                continue
            rendered = f"{title}\n\n**{target_label}:**\n{body} [{ev.candidate_id}]"
            return rendered

    return None


def is_useless_answer(answer: str) -> bool:
    """
    Kiểm tra câu trả lời rỗng, chỉ có citation, hoặc dưới 15 ký tự.
    """
    if not answer or not answer.strip():
        return True

    text = answer.strip()

    if text.lower().strip() == FALLBACK_TEXT.lower().strip():
        return True

    citation_only = re.fullmatch(
        r"\s*\[?EC_\d{3}\]?\s*[.!]?\s*",
        text,
    )
    if citation_only:
        return True

    cleaned = re.sub(
        r"\[?EC_\d{3}\]?",
        "",
        text,
    ).strip()

    if len(cleaned) < 15:
        return True

    return False

