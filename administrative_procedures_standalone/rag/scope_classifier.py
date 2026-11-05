"""
rag/scope_classifier.py — Hybrid Rule + Entity-Alignment + 1.5B LLM Scope Classifier.

Determines whether a user query belongs to the configured domain's supported scope
or should be rejected as out-of-scope (OOS).
"""

import json
import re
from collections import OrderedDict
from collections.abc import Callable

from domains.runtime import get_domain_runtime
from rag.text_normalizer import fold_accents, normalize_query_text

_SCOPE_CACHE: OrderedDict[tuple[str, str], tuple[bool, str]] = OrderedDict()
_MAX_SCOPE_CACHE = 500

# Generic administrative/question words that do NOT identify a specific in-scope procedure
_GENERIC_ADMIN_WORDS = {
    "thu", "tuc", "hanh", "chinh", "ho", "so", "giay", "to", "can", "nhung",
    "gi", "bao", "lau", "nhieu", "tien", "ngay", "lam", "viec", "nop", "o",
    "dau", "tai", "le", "phi", "chi", "thoi", "gian", "giai", "quyet", "xin",
    "cap", "dang", "ky", "xac", "nhan", "thanh", "pho", "ho", "chi", "minh",
    "tphcm", "hcm", "ubnd", "xa", "phuong", "quan", "huyen", "nha", "nuoc",
    "quy", "dinh", "เชิญ", "cho", "toi", "minh", "hoi", "ve", "cua", "va",
    "theo", "hinh", "thuc", "nao", "online", "truc", "tuyen", "tiep", "mat",
    "ton", "khong", "co", "duoc", "la", "mot", "truong", "hop", "doi", "voi",
    "nguoi", "dan", "cong", "dich", "vu", "bo", "phan", "cua", "nam", "nay",
    "hom", "cach", "the", "nao", "de", "muon", "chuan", "bi", "gom", "mang",
    "trinh", "xu", "ly", "noi", "chung",
}


def _extract_distinctive_tokens(text: str) -> set[str]:
    norm = fold_accents(normalize_query_text(text or "")).lower()
    tokens = re.findall(r"\w+", norm)
    return {t for t in tokens if len(t) > 1 and t not in _GENERIC_ADMIN_WORDS}


def has_domain_entity_match(query: str, domain: str | None = None) -> bool:
    """
    Check if query matches any configured entity_keywords or procedure aliases
    (both accented and accent-folded).
    """
    runtime = get_domain_runtime(domain)
    norm_q = normalize_query_text(query or "").lower()
    folded_q = fold_accents(norm_q)

    for kw in (runtime.entity_keywords or []):
        if not kw:
            continue
        kw_low = kw.lower()
        kw_fold = fold_accents(kw_low)
        # "kinh doanh" alone is too broad if paired with out-of-scope industries (e.g., "hàng không vũ trụ")
        if kw_fold in ("kinh doanh", "dang ky kinh doanh", "ho tro", "xac nhan tinh trang", "hop dong"):
            continue
        if kw_low in norm_q or kw_fold in folded_q:
            return True

    from rag.retrieval import _get_alias_catalog
    catalog = _get_alias_catalog(domain=domain)
    for _doc_id, aliases in catalog.items():
        for a in aliases:
            if not a or len(a) < 4:
                continue
            a_low = a.lower()
            a_fold = fold_accents(a_low)
            if a_low in norm_q or a_fold in folded_q:
                return True

    # Check "hộ kinh doanh" or specific business terms
    if any(p in folded_q for p in ("ho kinh doanh", "ca the", "tam ngung kinh doanh", "cham dut hoat dong")):
        return True

    return False


def classify_query_scope(
    query: str,
    top_doc_title: str = "",
    top_vector_score: float = 0.0,
    domain: str | None = None,
    generator: Callable[[str], str] | None = None,
) -> tuple[bool, str]:
    """
    Determine whether `query` is IN_SCOPE (True) or OUT_OF_SCOPE (False).

    Returns:
        (is_in_scope, reason)
    """
    runtime = get_domain_runtime(domain)
    domain_id = runtime.domain_id
    norm_q = normalize_query_text(query or "").strip()
    folded_q = fold_accents(norm_q).lower()

    cache_key = (domain_id, folded_q, bool(generator))
    if cache_key in _SCOPE_CACHE:
        _SCOPE_CACHE.move_to_end(cache_key)
        return _SCOPE_CACHE[cache_key]

    # 1. Explicit Out-of-Scope topic blocklist from config.yaml
    oos_topics = getattr(runtime.config, "out_of_scope_topics", None) or [
        "hộ chiếu", "visa", "giấy phép lái xe", "bằng lái", "đổi bằng lái",
        "giá xăng", "hàng không vũ trụ", "sốt xuất huyết", "uống thuốc",
        "system prompt", "bỏ qua mọi chỉ dẫn",
    ]
    for topic in oos_topics:
        if not topic:
            continue
        t_low = topic.lower()
        t_fold = fold_accents(t_low)
        if (
            re.search(r"\b" + re.escape(t_low) + r"\b", norm_q.lower())
            or re.search(r"\b" + re.escape(t_fold) + r"\b", folded_q)
        ):
            # Exception: marriage with foreign element is valid in-scope (PROC_006)
            if any(w in folded_q for w in ("ket hon", "hon nhan")) and t_fold in ("xuat nhap canh",):
                continue
            res = (False, f"matched_oos_topic:{topic}")
            _SCOPE_CACHE[cache_key] = res
            return res

    # 2. Check entity / title alignment for gray-zone queries
    entity_matched = has_domain_entity_match(norm_q, domain=domain_id)
    q_distinct = _extract_distinctive_tokens(norm_q)
    if not q_distinct and not entity_matched:
        res = (False, "vague_no_distinctive_subject")
        _SCOPE_CACHE[cache_key] = res
        return res

    title_distinct = _extract_distinctive_tokens(top_doc_title) if top_doc_title else set()
    title_overlap = len(q_distinct & title_distinct)
    overlap_ratio = title_overlap / max(len(q_distinct), 1)

    min_sem = float(getattr(runtime.config, "min_semantic_score", 0.44) or 0.44)

    # Strong in-scope signal: matches explicit domain entity/alias
    if entity_matched:
        res = (True, "entity_aligned")
        _SCOPE_CACHE[cache_key] = res
        return res

    # If no explicit entity matched, check high title token alignment when no LLM generator is needed
    if title_overlap >= 2 and overlap_ratio >= 0.50 and top_vector_score >= min_sem and generator is None:
        res = (True, "title_aligned")
        _SCOPE_CACHE[cache_key] = res
        return res

    # If top vector score is below semantic threshold and no entity matched -> reject immediately
    if top_vector_score > 0.0 and top_vector_score < min_sem and not entity_matched:
        res = (False, f"low_semantic_score:{top_vector_score:.3f}<{min_sem:.3f}")
        _SCOPE_CACHE[cache_key] = res
        return res

    # Gray zone (no explicit entity match): consult 1.5B LLM classifier if enabled, otherwise require strong title alignment
    if not entity_matched:
        if getattr(runtime.config, "scope_classifier", False) and generator is not None:
            prompt = (
                f"Bạn là bộ phân loại phạm vi câu hỏi cho hệ thống '{runtime.config.domain_name}'.\n"
                f"Thủ tục gần nhất tìm thấy trong DB: '{top_doc_title}'.\n"
                f"Câu hỏi người dùng: '{query}'\n"
                "Câu hỏi này có thực sự hỏi về thủ tục trên hoặc thủ tục hành chính cấp phường/xã tại TP.HCM không? "
                'Trả lời đúng định dạng JSON: {"in_scope": true} hoặc {"in_scope": false}.'
            )
            try:
                raw = generator(prompt)
                if raw and '"in_scope"' in raw:
                    m = re.search(r"\{.*?\}", raw, flags=re.DOTALL)
                    if m:
                        parsed = json.loads(m.group(0))
                        in_scope = bool(parsed.get("in_scope", False))
                        res = (in_scope, "llm_1_5b_scope_classifier")
                        _SCOPE_CACHE[cache_key] = res
                        return res
            except Exception:
                pass

        if title_overlap >= 1 and overlap_ratio >= 0.50 and top_vector_score >= min_sem:
            res = (True, "title_partial_aligned")
            _SCOPE_CACHE[cache_key] = res
            return res

        res = (False, "no_entity_or_title_alignment")
        _SCOPE_CACHE[cache_key] = res
        return res

    res = (True, "default_pass")
    _SCOPE_CACHE[cache_key] = res
    return res
