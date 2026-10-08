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
    conversation_summary = history.get("conversation_summary", "")

    parts: list[str] = []

    if conversation_summary:
        parts.append(
            f"Tóm tắt hội thoại:\n{conversation_summary}"
        )

    if recent_messages:
        message_lines: list[str] = []

        for message in recent_messages:
            if isinstance(message, dict):
                role = message.get("role", "")
                content = _extract_text(message.get("content", ""))
                message_lines.append(f"{role}: {content}")
            elif isinstance(message, (list, tuple)) and len(message) == 2:
                message_lines.append(f"user: {_extract_text(message[0])}\nassistant: {_extract_text(message[1])}")

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
    """Format procedure hints using only relevant chunk information."""
    if not procedure_hint:
        return "Không có gợi ý thủ tục."

    hint_parts: list[str] = []

    for index, chunk in enumerate(procedure_hint, start=1):
        title = chunk.metadata.get("title", "")
        title_text = f"\nTiêu đề: {title}" if title else ""

        hint_parts.append(
            f"Gợi ý {index}:\n"
            f"document_id: {chunk.document_id}"
            f"{title_text}\n"
            f"Nội dung: {chunk.content}"
        )

    return "\n\n".join(hint_parts)


def _build_synthesizer_prompt(
    query: str,
    history: dict[str, Any],
    procedure_hint: list[RetrievedChunk],
) -> str:
    """Build the Vietnamese prompt for query synthesis."""
    history_text = _format_history(history)
    procedure_hint_text = _format_procedure_hint(procedure_hint)

    return f"""
Bạn là Query Synthesizer cho một Legal AI Assistant chuyên về
thủ tục hành chính.

Nhiệm vụ duy nhất của bạn là viết lại câu hỏi hiện tại thành
một câu hỏi độc lập, đầy đủ ngữ cảnh để hệ thống Retrieval
có thể sử dụng.

Bạn được cung cấp:

1. Câu hỏi hiện tại.
2. Lịch sử hội thoại.
3. Một số gợi ý về thủ tục/chủ đề từ hệ thống Retrieval.

QUY TẮC:

- Giữ nguyên ý định của câu hỏi hiện tại.
- Sử dụng lịch sử hội thoại để giải quyết các tham chiếu như
  "nó", "vậy", "thế", "còn", "giấy tờ", "lệ phí thì sao?".
- Sử dụng gợi ý thủ tục/chủ đề chỉ để hỗ trợ hiểu câu hỏi.
- Không tự thêm thông tin mà người dùng chưa cung cấp.
- Không sử dụng kiến thức bên ngoài.
- Không trả lời câu hỏi pháp lý.
- Không tạo evidence.
- Không thực hiện Retrieval.
- Không thực hiện reranking.
- Không thực hiện verification.
- Không gọi MCP.
- Không tự suy diễn các thông tin còn thiếu.
- original_query phải giữ nguyên câu hỏi hiện tại.
- Nếu thông tin hiện có đủ để xác định câu hỏi độc lập:
  needs_clarification = false
  clarification_question = null
- Nếu vẫn thiếu thông tin quan trọng để xác định câu hỏi:
  needs_clarification = true
  clarification_question là một câu hỏi làm rõ ngắn gọn bằng tiếng Việt.
- Không đánh dấu cần làm rõ chỉ vì câu hỏi ngắn. Hãy dựa trên
  thông tin thực tế trong query, history và procedure hint.
- ĐẶC BIỆT LƯU Ý: Nếu câu hỏi hiện tại là một câu hỏi mở đầu hoặc chung chung
  (ví dụ: "chào", "mình muốn hỏi thủ tục", "cho mình hỏi"), và không có
  dấu hiệu nào cho thấy người dùng đang hỏi tiếp (follow-up) về thủ tục cũ,
  bạn BẮT BUỘC phải đặt needs_clarification = true và hỏi lại người dùng.
  KHÔNG tự động nối thủ tục cũ vào câu hỏi nếu người dùng không hỏi về nó.
- Chỉ trả về JSON hợp lệ.
- Không trả markdown.
- Không giải thích ngoài JSON.

ĐỊNH DẠNG JSON BẮT BUỘC:

{{
    "resolved_query": "...",
    "original_query": "...",
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
    known procedure in the dataset (procedures.json titles).

    This is a deterministic guard — the LLM is NOT consulted here.

    GĐ3 mục 12: `extra_text` nên chỉ chứa nội dung tin nhắn USER,
    không bao gồm câu trả lời assistant (tránh match keyword không liên quan).
    """
    from domains.runtime import get_domain_runtime
    runtime = get_domain_runtime(domain)
    keywords = runtime.entity_keywords

    combined = (query + " " + (extra_text or "")).lower()
    return any(kw.lower() in combined for kw in keywords)


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
    # Rule-based clarification override (Issue #3)
    # -----------------------------------------------------------------
    if not _has_specific_procedure_keyword(query, history_text_for_kw, domain=domain):
        clarification_q = (
            "Bạn muốn hỏi về thủ tục hành chính nào? "
            "Vui lòng cung cấp thêm thông tin cụ thể để tôi có thể hỗ trợ bạn."
        )
        print(
            "[synthesizer] Rule-based override: no procedure keyword in "
            "query+history → needs_clarification=True"
        )
        return ConsolidatedQuery(
            resolved_query=query,
            original_query=query,
            needs_clarification=True,
            clarification_question=clarification_q,
        )

    # -----------------------------------------------------------------
    # GĐ3 mục 10: (ĐÃ XOÁ BỎ) Rule-based follow-up resolution.
    # Nhường hoàn toàn cho LLM quyết định việc có phải follow-up hay không.
    # -----------------------------------------------------------------
    active_procedure = _get_active_procedure(history, procedure_hint, domain=domain)


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
        raw_output = generator(prompt)
        parsed_output = _parse_json_output(raw_output)
        return _validate_consolidated_query(parsed_output)
    except (ValueError, LLMUnavailableError) as exc:
        # GĐ3 mục 11: khi parse lỗi, ghép thủ tục active vào fallback
        # thay vì dùng nguyên câu gốc (dễ gây nhầm trong multi-turn)
        print(f"[synthesizer] Fallback do lỗi parse: {exc}")
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

