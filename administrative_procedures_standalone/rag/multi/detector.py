import re
import json
from typing import Optional, Tuple

from rag.multi.types import SubQuery
from rag.multi.title_index import find_procedures_in_text, normalize_text
from domains.runtime import get_domain_runtime

# Tách câu
SPLIT_PATTERN = re.compile(r'(?:\s+và\s+|\s+với\s+|\s+cùng\s+|\s+cũng như\s+|,|;)')

_PRONOUNS = {"nó", "vậy", "thế", "cái đó", "việc đó", "còn", "như vậy", "thì sao", "đây", "đó", "này", "ấy"}

def _detect_fields(text: str, domain: str) -> list[str]:
    runtime = get_domain_runtime(domain)
    # the yaml config should ideally have field_synonyms, but it's not present yet.
    # We will fallback to existing detection or hardcode a simple map based on Phase 2 plan.
    synonyms = {
        "required_documents": ["hồ sơ", "giấy tờ", "thành phần hồ sơ", "cần những gì", "chuẩn bị gì"],
        "fee": ["lệ phí", "phí", "bao nhiêu tiền", "đóng bao nhiêu"],
        "processing_time": ["thời gian", "mất bao lâu", "bao nhiêu ngày", "khi nào xong"],
        "submission_method": ["nộp ở đâu", "nộp ở", "hình thức nộp", "nơi nộp", "cơ quan nào"]
    }
    
    # Try to load from config if available (Phase 2)
    if hasattr(runtime.config, "field_synonyms") and getattr(runtime.config, "field_synonyms"):
        synonyms = runtime.config.field_synonyms
        
    found_fields = set()
    norm = text.lower()
    for field_name, kws in synonyms.items():
        for kw in kws:
            if kw in norm:
                found_fields.add(field_name)
                break
                
    return list(found_fields)

def _extract_via_llm(query: str, history: dict, domain: str) -> list[SubQuery]:
    # TODO: Phase 2 LLM fallback extraction. For now, return empty or single generic.
    return []

def detect_sub_queries(query: str, history: dict, domain: str) -> Tuple[list[SubQuery], bool]:
    """
    Detect multiple procedures in a single query.
    Returns (list of SubQuery, truncated boolean).
    """
    # 1. Bỏ qua LLM nếu có đại từ
    query_lower = query.lower()
    has_pronoun = any(re.search(r'\b' + p + r'\b', query_lower) for p in _PRONOUNS)
    if has_pronoun:
        # Fallback to LLM
        pass # Will implement later
        
    # 2. Quét title/alias trong câu
    found_procs = find_procedures_in_text(query, domain)
    
    if not found_procs:
        # If no specific procedures found in index, fallback to LLM
        llm_results = _extract_via_llm(query, history, domain)
        if llm_results:
            return llm_results, False
        # If LLM also fails, return a single generic subquery
        return [SubQuery(raw_mention=query, procedure_hint=None, fields=_detect_fields(query, domain), order=0)], False

    # 3. Tách phần câu
    parts = SPLIT_PATTERN.split(query)
    
    sub_queries = []
    order = 0
    
    # Phân bổ trường cho thủ tục
    # Nếu trường chỉ xuất hiện ở 1 part mà part đó ko có thủ tục, nó là trường dùng chung
    all_fields = _detect_fields(query, domain)
    
    # Simple mapping: for each found procedure, create a SubQuery
    # In a full implementation, we'd map parts to procedures more carefully.
    for proc in found_procs:
        # Tìm part chứa procedure này
        proc_fields = all_fields # Default to all detected fields in query (trường dùng chung)
        # To be more precise, we could check which part contains the alias and get its fields
        
        sub_queries.append(SubQuery(
            raw_mention=proc.title,
            procedure_hint=proc.title,
            fields=proc_fields,
            order=order
        ))
        order += 1
        
    # 6. Cắt tại max_procedures (8)
    MAX_PROC = 8
    truncated = len(sub_queries) > MAX_PROC
    
    return sub_queries[:MAX_PROC], truncated
