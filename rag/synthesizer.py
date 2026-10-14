import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from rag.generator import generate_answer_1_5b
from rag.retrieval import RetrievedChunk


# ---------------------------------------------------------------------------
# Issue #3 — Rule-based clarification override
# ---------------------------------------------------------------------------
# Specific keywords extracted from procedure titles in procedures.json.
# If the user's query contains at least one of these, the query is considered
# specific enough to proceed (no forced clarification).
# Add more keywords here whenever new procedures are added to the dataset.
# _PROCEDURE_KEYWORDS has been moved to DomainConfig.entity_keywords


@dataclass
class ConsolidatedQuery:
    resolved_query: str
    original_query: str
    needs_clarification: bool
    clarification_question: str | None = None


def _extract_text(val: object) -> str:
    """Safely extract string text from string, list, or dict message content."""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        return " ".join(_extract_text(item) for item in val if item)
    if isinstance(val, dict):
        if "text" in val and isinstance(val["text"], str):
            return val["text"]
        if "content" in val:
            return _extract_text(val["content"])
        return " ".join(_extract_text(v) for v in val.values() if v)
    return str(val) if val is not None else ""


def _format_history(history: dict[str, Any]) -> str:
    """Format conversation history without modifying the original data."""
    if not history:
        return "Không có lịch sử hội thoại."

    recent_messages = history.get("recent_messages", [])
    if isinstance(recent_messages, list) and len(recent_messages) > 4:
        recent_messages = recent_messages[-4:]

    conversation_summary = history.get("conversation_summary", "")

    parts: list[str] = []

    if conversation_summary:
        sum_text = _extract_text(conversation_summary)
        if len(sum_text) > 300:
            sum_text = sum_text[:300] + "..."
        parts.append(
            f"Tóm tắt hội thoại:\n{sum_text}"
        )

    if recent_messages:
        message_lines: list[str] = []

        for message in recent_messages:
            if isinstance(message, dict):
                role = message.get("role", "")
                content = _extract_text(message.get("content", ""))
                if role == "assistant" and len(content) > 150:
                    content = content[:150] + "..."
                message_lines.append(f"{role}: {content}")
            elif isinstance(message, (list, tuple)) and len(message) == 2:
                user_text = _extract_text(message[0])
                assistant_text = _extract_text(message[1])
                if len(assistant_text) > 150:
                    assistant_text = assistant_text[:150] + "..."
                message_lines.append(f"user: {user_text}\nassistant: {assistant_text}")

        if message_lines:
            parts.append(
                "Các tin nhắn gần đây:\n"
                + "\n".join(message_lines)
            )

    if not parts:
        return "Không có lịch sử hội thoại."

    return "\n\n".join(parts)


def _format_procedure_hint(
    procedure_hint: list[RetrievedChunk],
) -> str:
    """Format procedure hints using only title (Phase 1)."""
    if not procedure_hint:
        return "Không có gợi ý thủ tục."

    hint_parts: list[str] = []

    for index, chunk in enumerate(procedure_hint, start=1):
        title = chunk.metadata.get("title", "")
        if title:
            hint_parts.append(f"Gợi ý {index}: {title}")

    if not hint_parts:
        return "Không có gợi ý thủ tục."

    return "\n".join(hint_parts)


_PRONOUNS = {
    "nó", "vậy", "thế", "cái đó", "việc đó", "còn", "như vậy", "thì sao",
    "đây", "đó", "này", "ấy", "chưa", "nếu", "mà", "ủa", "sao", "thế thì",
    "vậy thì", "ai", "bao nhiêu", "ở đâu", "mấy ngày", "mất bao lâu",
    "thì làm sao", "thì phải làm sao"
}

def _is_faithful(
    resolved_query: str,
    query: str,
    history_user_texts: list[str],
    hint_titles: list[str],
) -> bool:
    """Check if LLM hallucinated numbers."""
    allowed_text = (
        query.lower() + " " +
        " ".join(history_user_texts).lower() + " " +
        " ".join(hint_titles).lower()
    )
    
    # Check if any digits in the resolved query are not in the allowed text
    for num in re.findall(r'\d+', resolved_query):
        if num not in allowed_text:
            return False
            
    return True


def _build_synthesizer_prompt(
    query: str,
    history: dict[str, Any],
    procedure_hint: list[RetrievedChunk],
) -> str:
    """Build the Vietnamese prompt for query synthesis."""
    history_text = _format_history(history)
    procedure_hint_text = _format_procedure_hint(procedure_hint)

    return f"""
Bạn là Query Synthesizer cho một Legal AI Assistant chuyên về thủ tục hành chính.

Nhiệm vụ duy nhất của bạn là viết lại câu hỏi hiện tại thành một câu hỏi độc lập, đầy đủ ngữ cảnh để hệ thống Retrieval có thể sử dụng.

QUY TẮC:
- Giữ nguyên ý định của câu hỏi hiện tại.
- Sử dụng lịch sử hội thoại để giải quyết các tham chiếu ("nó", "vậy", "thì sao", "còn"...).
- Sử dụng gợi ý thủ tục chỉ để hỗ trợ hiểu câu hỏi.
- Không tự thêm thông tin chưa được cung cấp.
- Không trả lời câu hỏi pháp lý, không suy diễn thông tin.
- Nếu thông tin hiện có đủ để xác định câu hỏi độc lập: needs_clarification = false, clarification_question = null
- Nếu thiếu thông tin quan trọng để xác định: needs_clarification = true, clarification_question = "câu hỏi làm rõ ngắn gọn"
- ĐẶC BIỆT LƯU Ý: Nếu câu mở đầu ("chào", "cho hỏi") không nói rõ thủ tục và không có follow-up, BẮT BUỘC needs_clarification = true. KHÔNG tự nối thủ tục cũ vào nếu người dùng không hỏi.

VÍ DỤ MẪU:

Ví dụ 1:
LỊCH SỬ: user: tôi muốn đăng ký kết hôn
CÂU HỎI HIỆN TẠI: vậy lệ phí thì sao?
ĐÁP ÁN JSON:
{{
    "resolved_query": "lệ phí đăng ký kết hôn là bao nhiêu?",
    "original_query": "vậy lệ phí thì sao?",
    "needs_clarification": false,
    "clarification_question": null
}}

Ví dụ 2:
LỊCH SỬ: Không có lịch sử hội thoại.
CÂU HỎI HIỆN TẠI: tôi muốn làm giấy tờ
ĐÁP ÁN JSON:
{{
    "resolved_query": "tôi muốn làm giấy tờ",
    "original_query": "tôi muốn làm giấy tờ",
    "needs_clarification": true,
    "clarification_question": "Bạn muốn làm giấy tờ liên quan đến thủ tục nào?"
}}

Ví dụ 3:
LỊCH SỬ: user: thủ tục cấp hộ chiếu
CÂU HỎI HIỆN TẠI: xin chào
ĐÁP ÁN JSON:
{{
    "resolved_query": "xin chào",
    "original_query": "xin chào",
    "needs_clarification": true,
    "clarification_question": "Chào bạn, bạn muốn hỏi về thủ tục hành chính nào?"
}}

Ví dụ 4:
LỊCH SỬ: Không có lịch sử hội thoại.
GỢI Ý: Gợi ý 1: Thủ tục đăng ký khai sinh
CÂU HỎI HIỆN TẠI: kiểu mình mới đẻ con ấy thì giờ mình phải làm gì
ĐÁP ÁN JSON:
{{
    "resolved_query": "mới sinh con thì làm thủ tục đăng ký khai sinh như thế nào?",
    "original_query": "kiểu mình mới đẻ con ấy thì giờ mình phải làm gì",
    "needs_clarification": false,
    "clarification_question": null
}}

Ví dụ 5:
LỊCH SỬ: user: thủ tục giấy khai sinh
CÂU HỎI HIỆN TẠI: ủa mà mình chưa đăng kí kết hôn á thì phải làm sao?
ĐÁP ÁN JSON:
{{
    "resolved_query": "chưa đăng ký kết hôn thì đăng ký khai sinh cho con như thế nào?",
    "original_query": "ủa mà mình chưa đăng kí kết hôn á thì phải làm sao?",
    "needs_clarification": false,
    "clarification_question": null
}}

CÂU HỎI HIỆN TẠI:
{query}

LỊCH SỬ HỘI THOẠI:
{history_text}

GỢI Ý THỦ TỤC/CHỦ ĐỀ:
{procedure_hint_text}
""".strip()


def _parse_json_output(raw_output: str) -> dict[str, Any]:
    """
    Parse raw LLM output into a JSON dictionary.

    Supports plain JSON and JSON wrapped in a markdown code fence.
    """
    if not isinstance(raw_output, str):
        raise ValueError(
            "LLM output must be a string."
        )

    cleaned = raw_output.strip()

    if not cleaned:
        raise ValueError(
            "LLM output is empty."
        )

    # Remove an optional markdown code fence.
    code_fence_match = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```",
        cleaned,
        flags=re.DOTALL | re.IGNORECASE,
    )

    if code_fence_match:
        cleaned = code_fence_match.group(1).strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Failed to parse LLM output as JSON: {exc}"
        ) from exc

    if not isinstance(parsed, dict):
        raise ValueError(
            "Parsed LLM output must be a JSON object."
        )

    return parsed


def _validate_consolidated_query(
    data: dict[str, Any],
) -> ConsolidatedQuery:
    """Validate parsed JSON and construct ConsolidatedQuery."""
    required_fields = {
        "resolved_query",
        "original_query",
        "needs_clarification",
        "clarification_question",
    }

    missing_fields = required_fields - data.keys()

    if missing_fields:
        raise ValueError(
            "Missing required field(s): "
            + ", ".join(sorted(missing_fields))
        )

    resolved_query = data["resolved_query"]
    original_query = data["original_query"]
    needs_clarification = data["needs_clarification"]
    clarification_question = data["clarification_question"]

    if not isinstance(resolved_query, str):
        raise ValueError(
            "'resolved_query' must be a string."
        )

    if not isinstance(original_query, str):
        raise ValueError(
            "'original_query' must be a string."
        )

    if not isinstance(needs_clarification, bool):
        raise ValueError(
            "'needs_clarification' must be a boolean."
        )

    if (
        clarification_question is not None
        and not isinstance(clarification_question, str)
    ):
        raise ValueError(
            "'clarification_question' must be a string or None."
        )

    return ConsolidatedQuery(
        resolved_query=resolved_query,
        original_query=original_query,
        needs_clarification=needs_clarification,
        clarification_question=clarification_question,
    )


def _has_specific_procedure_keyword(query: str, extra_text: str = "", domain: str | None = None) -> bool:
    """
    Return True if the query contains at least one keyword that maps to a
    known procedure in the dataset (procedures.json titles or aliases).

    This is a deterministic guard — the LLM is NOT consulted here.

    GĐ3 mục 12: `extra_text` nên chỉ chứa nội dung tin nhắn USER,
    không bao gồm câu trả lời assistant (tránh match keyword không liên quan).
    """
    from domains.runtime import get_domain_runtime
    runtime = get_domain_runtime(domain)
    keywords = runtime.entity_keywords

    combined = (query + " " + (extra_text or "")).lower()
    if any(kw.lower() in combined for kw in keywords):
        return True

    from rag.retrieval import _get_alias_catalog
    catalog = _get_alias_catalog()
    for doc_id, aliases in catalog.items():
        if any(a in combined for a in aliases if a):
            return True

    return False


def _get_active_procedure(history: dict, procedure_hint: list, domain: str | None = None) -> str:
    """
    GĐ3 mục 10: Xác định thủ tục đang active theo thứ tự ưu tiên:
    1. structured_context.procedure_name (do Person 2 điền)
    2. Thủ tục khớp mạnh ở tin nhắn USER gần nhất trong history
    3. Top-1 procedure_hint title
    """
    # 1. structured_context (nếu có)
    if isinstance(history, dict):
        sc = history.get("structured_context") or {}
        if isinstance(sc, dict) and sc.get("procedure_name"):
            return sc["procedure_name"]

    # 2. Tin nhắn USER gần nhất có keyword thủ tục
    if isinstance(history, dict):
        msgs = history.get("recent_messages", [])
        # Duyệt ngược để lấy tin nhắn gần nhất
        for msg in reversed(msgs):
            if isinstance(msg, dict):
                role = msg.get("role", "")
                if role == "user":
                    content = _extract_text(msg.get("content", ""))
                    if _has_specific_procedure_keyword(content, domain=domain):
                        return content  # trả về text để extract sau
            elif isinstance(msg, (list, tuple)) and len(msg) >= 2:
                user_text = _extract_text(msg[0])
                if _has_specific_procedure_keyword(user_text, domain=domain):
                    return user_text

    # 3. procedure_hint title
    if procedure_hint:
        title = procedure_hint[0].metadata.get("title", "")
        if title:
            return title

    return ""


def synthesizer(
    query: str,
    history: dict[str, Any],
    procedure_hint: list[RetrievedChunk],
    generator: Callable[[str], str] = generate_answer_1_5b,
    domain: str | None = None,
) -> ConsolidatedQuery:
    """
    Synthesize the current query into an independent ConsolidatedQuery.

    GĐ3 cải tiến:
    - Mục 12: Chỉ quét USER messages cho keyword check (không quét assistant).
    - Mục 10: Rule-based resolve_followup trước khi gọi LLM.
    - Mục 11: Khi parse JSON lỗi, ghép thủ tục đang active vào fallback.
    """

    # GĐ3 mục 12: Chỉ lấy tin nhắn USER cho keyword check
    recent_messages = (
        history.get("recent_messages", [])
        if isinstance(history, dict)
        else []
    )
    user_kw_texts = []
    for m in recent_messages:
        if isinstance(m, dict):
            # Chỉ lấy tin nhắn user, bỏ assistant
            if m.get("role", "") == "user":
                user_kw_texts.append(_extract_text(m.get("content", "")))
        elif isinstance(m, (list, tuple)):
            # Format (user_text, assistant_text) — chỉ lấy user_text
            user_kw_texts.append(_extract_text(m[0]))
        elif isinstance(m, str):
            user_kw_texts.append(m)

    history_text_for_kw = " ".join(user_kw_texts)

    # -----------------------------------------------------------------
    # Rule-based clarification override (Bước 2A: Kết hợp Retrieval Hints)
    # -----------------------------------------------------------------
    has_keyword = _has_specific_procedure_keyword(query, history_text_for_kw, domain=domain)
    has_hint = bool(procedure_hint and len(procedure_hint) > 0)

    if not has_keyword and not has_hint:
        clarification_q = (
            "Bạn muốn hỏi về thủ tục hành chính nào? "
            "Vui lòng cung cấp thêm thông tin cụ thể để tôi có thể hỗ trợ bạn."
        )
        print(
            "[synthesizer] Rule-based override: no procedure keyword and no valid hints "
            "→ needs_clarification=True"
        )
        return ConsolidatedQuery(
            resolved_query=query,
            original_query=query,
            needs_clarification=True,
            clarification_question=clarification_q,
        )

    # -----------------------------------------------------------------
    # Bỏ qua LLM khi câu đã rõ
    # -----------------------------------------------------------------
    query_lower = query.lower()
    has_pronoun = any(re.search(r'\b' + p + r'\b', query_lower) for p in _PRONOUNS)
    
    # Chỉ bypass khi chính câu hiện tại (query) có từ khóa thủ tục rõ ràng
    has_query_kw = _has_specific_procedure_keyword(query, domain=domain)
    if not has_pronoun and has_query_kw:
        print("[synthesizer] Query is clear (no pronouns, has keyword) -> bypass LLM.")
        return ConsolidatedQuery(
            resolved_query=query,
            original_query=query,
            needs_clarification=False,
            clarification_question=None,
        )

    # Turn 1: Không có lịch sử hội thoại, nếu đã có keyword thủ tục/alias thì query độc lập, bypass LLM
    if not recent_messages and has_query_kw:
        print("[synthesizer] Turn 1 with procedure keyword -> bypass LLM.")
        return ConsolidatedQuery(
            resolved_query=query,
            original_query=query,
            needs_clarification=False,
            clarification_question=None,
        )

    active_procedure = _get_active_procedure(history, procedure_hint, domain=domain)

    # SYNTHESIZER_MODE check: 'rule' or 'off' bypasses LLM call completely
    import my_config as cfg
    synth_mode = getattr(cfg, "SYNTHESIZER_MODE", "llm")
    if generator is generate_answer_1_5b:
        if synth_mode in ("rule", "off") and active_procedure:
            resolved = f"{query} (liên quan đến: {active_procedure})"
            print(f"[synthesizer] Fast rule/off bypass (mode='{synth_mode}'): {resolved}")
            return ConsolidatedQuery(
                resolved_query=resolved,
                original_query=query,
                needs_clarification=False,
                clarification_question=None,
            )
        elif synth_mode == "off":
            print(f"[synthesizer] Fast off bypass: {query}")
            return ConsolidatedQuery(
                resolved_query=query,
                original_query=query,
                needs_clarification=False,
                clarification_question=None,
            )

    # Bước 3A Fast Path: Nếu câu hỏi hỏi về field/hồ sơ/lệ phí và đã có thủ tục active, ghép nhanh (chỉ khi dùng production generator)
    if generator is generate_answer_1_5b:
        from rag.prompt_builder import _detect_field_types
        detected_fields = _detect_field_types(query)
        if detected_fields and active_procedure and not has_query_kw:
            resolved = f"{query} (liên quan đến: {active_procedure})"
            print(f"[synthesizer] Fast follow-up field resolution: {resolved}")
            return ConsolidatedQuery(
                resolved_query=resolved,
                original_query=query,
                needs_clarification=False,
                clarification_question=None,
            )


    # -----------------------------------------------------------------
    # Normal path: call LLM synthesizer
    # -----------------------------------------------------------------
    prompt = _build_synthesizer_prompt(
        query=query,
        history=history,
        procedure_hint=procedure_hint,
    )

    try:
        from rag.generator import LLMUnavailableError
        # Phase 1: Call generator with temperature=0 and json_mode=True
        raw_output = generator(prompt, temperature=0.0, json_mode=True)
        parsed_output = _parse_json_output(raw_output)
        cq = _validate_consolidated_query(parsed_output)
        
        # Phase 1: Faithfulness check
        hint_titles = [h.metadata.get("title", "") for h in procedure_hint]
        if not _is_faithful(cq.resolved_query, query, user_kw_texts, hint_titles):
            print("[synthesizer] LLM output failed faithfulness check, using fallback.")
            raise ValueError("Faithfulness check failed")
            
        return cq
    except (ValueError, LLMUnavailableError, TypeError) as exc:
        # TypeError can happen if generator doesn't accept temperature/json_mode kwargs
        # GĐ3 mục 11: khi parse lỗi, ghép thủ tục active vào fallback
        # thay vì dùng nguyên câu gốc (dễ gây nhầm trong multi-turn)
        print(f"[synthesizer] Fallback do lỗi parse/LLM: {exc}")
        fallback_query = query
        if active_procedure:
            proc_short = active_procedure[:60] if len(active_procedure) > 60 else active_procedure
            fallback_query = f"{query} (liên quan đến: {proc_short})"
        return ConsolidatedQuery(
            resolved_query=fallback_query,
            original_query=query,
            needs_clarification=False,
            clarification_question=None,
        )

