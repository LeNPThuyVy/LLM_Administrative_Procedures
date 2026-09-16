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

NHIỆM VỤ DUY NHẤT:

Chuyển câu hỏi hiện tại thành một câu hỏi độc lập, đầy đủ ngữ cảnh
để Retrieval phía sau có thể sử dụng.

Bạn KHÔNG được trả lời câu hỏi pháp lý.
Bạn KHÔNG được tạo evidence.
Bạn KHÔNG được thực hiện Retrieval.
Bạn KHÔNG được reranking.
Bạn KHÔNG được verification.
Bạn KHÔNG được gọi MCP.
Bạn KHÔNG được sử dụng kiến thức pháp lý bên ngoài.

==================================================
RESOLVED_QUERY
==================================================

resolved_query là phiên bản câu hỏi hiện tại đã được bổ sung
context cần thiết từ conversation history hoặc procedure/topic hint.

Mục tiêu là giúp Retrieval phía sau hiểu đầy đủ người dùng đang hỏi gì.

resolved_query phải:

- Giữ nguyên ý định của câu hỏi hiện tại.
- Bổ sung context cần thiết từ conversation history.
- Có thể bổ sung tên thủ tục, đối tượng hoặc địa điểm nếu thông tin
  đó thực sự xuất hiện trong history hoặc procedure/topic hint.
- Không được thay đổi ý định của người dùng.
- Không được trả lời câu hỏi.
- Không được tự thêm thông tin pháp lý.
- Không được tự suy diễn thông tin không có trong các nguồn được cung cấp.

Ví dụ:

Current query:
"Giấy tờ."

History:
User: "Tôi muốn đăng ký hộ kinh doanh ở Bình Dương."
Assistant: "Bạn muốn biết thông tin gì?"

resolved_query có thể là:

"Tôi cần biết giấy tờ để đăng ký hộ kinh doanh ở Bình Dương."

==================================================
CLARIFICATION
==================================================

Chỉ đặt:

"needs_clarification": true

khi thông tin trong:

1. CÂU HỎI HIỆN TẠI
2. CONVERSATION HISTORY
3. PROCEDURE/TOPIC HINT

không đủ để xác định đối tượng hoặc thủ tục mà người dùng đang hỏi.

Nếu cần clarification:

- needs_clarification phải là true.
- clarification_question phải khác null.
- clarification_question phải là một câu hỏi ngắn gọn bằng tiếng Việt.
- Không được tự chọn một thủ tục cụ thể.
- Không được tự thêm tên thủ tục.
- Không được tự thêm địa điểm.
- Không được tự thêm thông tin pháp lý.

Nếu đủ thông tin:

- needs_clarification phải là false.
- clarification_question phải là null.

QUAN TRỌNG:

Không được biến mọi câu hỏi ngắn thành clarification.

Độ dài của query KHÔNG phải là lý do đủ để yêu cầu clarification.

Ví dụ "Giấy tờ." có thể được xử lý mà không cần clarification
nếu conversation history đã xác định rõ thủ tục mà người dùng đang hỏi.

==================================================
NGUỒN THÔNG TIN ĐƯỢC PHÉP
==================================================

Chỉ sử dụng thông tin xuất hiện trong:

1. CÂU HỎI HIỆN TẠI
2. CONVERSATION HISTORY
3. PROCEDURE/TOPIC HINT

Không sử dụng kiến thức bên ngoài.

Không tự thêm:

- tên thủ tục
- địa điểm
- lệ phí
- thời gian xử lý
- giấy tờ
- điều kiện
- cơ quan
- quy định pháp luật

nếu thông tin đó không xuất hiện trong các nguồn được cung cấp.

Procedure hint chỉ là thông tin hỗ trợ để hiểu chủ đề.

Không được xem procedure hint là lý do để tự thêm thông tin
không có trong query hoặc history.

==================================================
VÍ DỤ A — MULTI-TURN
==================================================

History:

User:
"Tôi muốn đăng ký hộ kinh doanh ở Bình Dương."

Assistant:
"Bạn muốn biết thông tin gì?"

Current query:

"Giấy tờ."

Output:

{{
    "resolved_query": "Tôi cần biết giấy tờ để đăng ký hộ kinh doanh ở Bình Dương.",
    "needs_clarification": false,
    "clarification_question": null
}}

Lưu ý:

History được dùng để bổ sung context cho resolved_query.

Không được thay đổi ý định "Giấy tờ."

==================================================
VÍ DỤ B — KHÔNG CÓ CONTEXT
==================================================

History:

không có

Current query:

"Giấy tờ."

Procedure hint:

không có

Output:

{{
    "resolved_query": "",
    "needs_clarification": true,
    "clarification_question": "Bạn muốn hỏi giấy tờ của thủ tục nào?"
}}

Không được tự chọn một thủ tục cụ thể.

Ví dụ KHÔNG được trả:

{{
    "resolved_query": "Giấy tờ đăng ký hộ kinh doanh",
    "needs_clarification": false,
    "clarification_question": null
}}

vì không có thông tin nào cho phép xác định người dùng đang hỏi
về đăng ký hộ kinh doanh.

==================================================
VÍ DỤ C — CÂU HỎI THAM CHIẾU
==================================================

Nếu current query là:

"Giấy tờ?"

"Lệ phí thì sao?"

"Còn thời gian xử lý?"

hãy kiểm tra history trước.

Nếu history xác định rõ thủ tục hoặc đối tượng được nhắc đến,
hãy dùng context đó để tạo resolved_query.

Nếu history không đủ để xác định thủ tục hoặc đối tượng,
hãy yêu cầu clarification.

Không được tự chọn thủ tục khi thiếu context.

==================================================
OUTPUT CONTRACT
==================================================

Chỉ trả về JSON hợp lệ.

Không trả markdown.

Không trả code fence.

Không giải thích.

Không thêm text bên ngoài JSON.

JSON phải có chính xác 3 field sau:

{{
    "resolved_query": "...",
    "needs_clarification": false,
    "clarification_question": null
}}

Trong đó:

- resolved_query: string
- needs_clarification: boolean true hoặc false
- clarification_question: string hoặc null

Không tạo thêm field nào khác.

==================================================
CÂU HỎI HIỆN TẠI
==================================================

{query}

==================================================
LỊCH SỬ HỘI THOẠI
==================================================

{history_text}

==================================================
GỢI Ý THỦ TỤC/CHỦ ĐỀ
==================================================

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
) -> dict[str, Any]:
    """Validate the three fields generated by the LLM."""
    required_fields = {
        "resolved_query",
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
    needs_clarification = data["needs_clarification"]
    clarification_question = data["clarification_question"]

    if not isinstance(resolved_query, str):
        raise ValueError(
            "'resolved_query' must be a string."
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

    return {
        "resolved_query": resolved_query,
        "needs_clarification": needs_clarification,
        "clarification_question": clarification_question,
    }


def synthesizer(
    query: str,
    history: dict[str, Any],
    procedure_hint: list[RetrievedChunk],
    generator: Callable[[str], str] = generate_answer,
) -> ConsolidatedQuery:
    """
    Synthesize the current query into an independent ConsolidatedQuery.

    The generator is called exactly once per invocation.
    """
    prompt = _build_synthesizer_prompt(
        query=query,
        history=history,
        procedure_hint=procedure_hint,
    )

    raw_output = generator(prompt)

    parsed_output = _parse_json_output(raw_output)

    validated_output = _validate_consolidated_query(
        parsed_output
    )

    return ConsolidatedQuery(
        resolved_query=validated_output["resolved_query"],
        original_query=query,
        needs_clarification=validated_output["needs_clarification"],
        clarification_question=validated_output["clarification_question"],
    )
    query: str,
    history: dict[str, Any],
    procedure_hint: list[RetrievedChunk],
    generator: Callable[[str], str] = generate_answer,
) -> ConsolidatedQuery:
    """
    Synthesize the current query into an independent ConsolidatedQuery.

    The generator is called exactly once per invocation.
    """
    prompt = _build_synthesizer_prompt(
        query=query,
        history=history,
        procedure_hint=procedure_hint,
    )

    raw_output = generator(prompt)

    parsed_output = _parse_json_output(raw_output)

    return _validate_consolidated_query(parsed_output)