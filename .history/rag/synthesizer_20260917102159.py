import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from rag.generator import generate_answer
from rag.retrieval import RetrievedChunk


@dataclass
class ConsolidatedQuery:
    resolved_query: str
    original_query: str
    needs_clarification: bool
    clarification_question: str | None = None


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
            if not isinstance(message, dict):
                continue

            role = message.get("role", "")
            content = message.get("content", "")

            message_lines.append(
                f"{role}: {content}"
            )

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


def synthesizer(query, history, procedure_hint, generator=generate_answer):
    prompt = _build_synthesizer_prompt(query, history, procedure_hint)
    raw_output = generator(prompt)

    try:
        print("Parsing json outp")
        parsed_output = _parse_json_output(raw_output)
        return _validate_consolidated_query(parsed_output)
    except ValueError as exc:
        print(f"[synthesizer] Fallback do lỗi parse: {exc}")
        return ConsolidatedQuery(
            resolved_query=query,
            original_query=query,
            needs_clarification=False,
            clarification_question=None,
        )