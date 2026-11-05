"""
Prompt Builder — constructs the final answer-generation prompt.

Uses:
- current user query
- conversation summary
- recent messages
- structured context
- long-term memory
- verified evidence

Also detects which administrative procedure field the user is asking
about and restricts the answer to the requested field(s).
"""

import my_config as cfg
from rag.evidence_builder import EvidenceCandidate
from rag.text_normalizer import fold_accents, normalize_query_text


# =========================================================
# FIELD DETECTION
# =========================================================

import re as _re

# =========================================================
# FIELD DETECTION PATTERNS
# GĐ1 mục 3: Dùng regex word-boundary, tránh match substring rộng.
# =========================================================

_DOCS_REGEX = _re.compile(
    r"\b((?<!trên\s)(?<!trong\s)giấy\s+tờ|thành\s+phần\s+hồ\s+sơ|hồ\s+sơ\s+gì|hồ\s+sơ\s+gồm|hồ\s+sơ\s+cần|"
    r"cần\s+hồ\s+sơ|chuẩn\s+bị\s+hồ\s+sơ|những\s+hồ\s+sơ|cần\s+chuẩn\s+bị|"
    r"tài\s+liệu|giấy\s+chứng\s+minh|giấy\s+chứng\s+sinh|"
    r"giấy\s+khai|cần\s+gì|cần\s+những\s+gì|gồm\s+những\s+gì|gồm\s+gì|"
    r"bao\s+gồm\s+những\s+gì|cần\s+mang|mang\s+theo|xuất\s+trình|required|"
    r"(?<!tren\s)(?<!trong\s)giay\s+to|thanh\s+phan\s+ho\s+so|ho\s+so\s+gi|ho\s+so\s+gom|ho\s+so\s+can|"
    r"can\s+ho\s+so|chuan\s+bi\s+ho\s+so|can\s+chuan\s+bi|tai\s+lieu|can\s+gi|"
    r"can\s+nhung\s+gi|gom\s+nhung\s+gi|gom\s+gi|can\s+mang|xuat\s+trinh)\b",
    _re.IGNORECASE | _re.UNICODE,
)

_METHOD_REGEX = _re.compile(
    r"\b(hình\s+thức\s+nộp|hình\s+thức\s+nào|nộp\s+online|nộp\s+trực\s+tuyến|"
    r"nộp\s+trực\s+tiếp|cách\s+nộp|nộp\s+ở\s+đâu|nộp\s+tại\s+đâu|"
    r"nộp\s+hồ\s+sơ\s+ở\s+đâu|nộp\s+hồ\s+sơ\s+tại\s+đâu|làm\s+ở\s+đâu|"
    r"đăng\s+ký\s+ở\s+đâu|ở\s+đâu|tại\s+đâu|nơi\s+nộp|địa\s+điểm\s+nộp|submission\s+method|"
    r"hinh\s+thuc\s+nop|hinh\s+thuc\s+nao|nop\s+online|nop\s+truc\s+tuyen|"
    r"nop\s+truc\s+tiep|cach\s+nop|nop\s+o\s+dau|nop\s+tai\s+dau|nop\s+ho\s+so\s+o\s+dau|"
    r"lam\s+o\s+dau|o\s+dau|tai\s+dau|noi\s+nop)\b",
    _re.IGNORECASE | _re.UNICODE,
)

_FEE_REGEX = _re.compile(
    r"\b(lệ\s+phí|lệ\s+pí|chi\s+phí\s+làm|miễn\s+phí|bao\s+nhiêu\s+tiền|mất\s+bao\s+nhiêu\s+tiền|"
    r"mất\s+phí|tốn\s+phí|thu\s+phí|phí\s+chứng\s+thực|phí\s+đăng\s+ký|phí\s+cấp|"
    r"mức\s+thu|bao\s+nhiêu\s+một\s+trường\s+hợp|lệ\s+phí.*?(?:bao\s+nhiêu|bn)|"
    r"phí.*?(?:bao\s+nhiêu\s+tiền|là\s+bao\s+nhiêu)|"
    r"cấp\s+lại.*bao\s+nhiêu|fee|le\s+phi|le\s+pi|mien\s+phi|bao\s+nhieu\s+tien|mat\s+phi|"
    r"ton\s+phi|thu\s+phi|phi\s+chung\s+thuc|muc\s+thu|le\s+phi.*?(?:bao\s+nhieu|bn)|"
    r"phi.*?(?:bao\s+nhieu\s+tien|la\s+bao\s+nhieu))\b",
    _re.IGNORECASE | _re.UNICODE,
)

_TIME_REGEX = _re.compile(
    r"\b(thời\s+gian|bao\s+lâu|mấy\s+ngày|thời\s+hạn|"
    r"bao\s+nhiêu\s+ngày|trong\s+ngày|lấy\s+ngay|processing\s+time|"
    r"thoi\s+gian|bao\s+lau|may\s+ngay|thoi\s+han|bao\s+nhieu\s+ngay|"
    r"trong\s+ngay|lay\s+ngay)\b",
    _re.IGNORECASE | _re.UNICODE,
)

_ORDERED_FIELD_CHECKS = [
    ("docs",   _DOCS_REGEX),
    ("method", _METHOD_REGEX),
    ("fee",    _FEE_REGEX),
    ("time",   _TIME_REGEX),
]

_FIELD_LABELS = {
    "docs": "GIẤY TỜ / HỒ SƠ cần thiết",
    "fee": "LỆ PHÍ",
    "time": "THỜI GIAN GIẢI QUYẾT",
    "method": "HÌNH THỨC NỘP HỒ SƠ",
}

_FIELD_SECTION_NAMES = {
    "docs": "'Thành phần hồ sơ'",
    "fee": "'Lệ phí'",
    "time": "'Thời gian giải quyết'",
    "method": "'Hình thức nộp'",
}


# =========================================================
# FIELD RESTRICTION
# =========================================================

def _detect_field_types(
    query: str,
    context: dict | None = None,
    domain: str | None = None,
) -> list[str]:
    """
    Detect all procedure fields requested by the user.

    GĐ1 mục 3 & Phase 4:
    - Nếu domain có cấu hình field_intents: dùng danh sách field_intents của domain.
    - Nếu domain không có field_intents (ví dụ tourism_demo): trả về [] (không thêm restriction).
    - Default (hành chính khi chưa load): fallback _ORDERED_FIELD_CHECKS.
    """
    from domains.runtime import get_domain_runtime
    runtime = get_domain_runtime(domain)

    text_parts = [query or ""]

    if isinstance(context, dict):
        structured_context = context.get("structured_context", {}) or {}
        intent = structured_context.get("intent")
        if intent:
            text_parts.append(str(intent))

    raw_q = " ".join(text_parts)
    norm_q = normalize_query_text(raw_q)
    folded_q = fold_accents(norm_q)
    q = f"{raw_q} | {norm_q} | {folded_q}"

    if runtime and hasattr(runtime, "config") and runtime.config.field_intents:
        detected = []
        for fi in runtime.config.field_intents:
            key = fi.get("key")
            pattern_str = fi.get("pattern")
            if key and pattern_str:
                if _re.search(pattern_str, q, _re.IGNORECASE | _re.UNICODE):
                    detected.append(key)
        return detected

    if domain and domain != "administrative_procedures":
        return []

    detected = []
    for key, pattern in _ORDERED_FIELD_CHECKS:
        if pattern.search(q):
            detected.append(key)

    return detected


def _build_field_restriction_rule(
    field_types: list[str],
    domain: str | None = None,
) -> str:
    """
    Build a soft focus rule for detected fields.

    GĐ1 mục 3: Chỉ nói "tập trung vào...", không cấm đề cập
    phần khác nếu thực sự liên quan trực tiếp.
    Khi không có field nào → trả "" (không thêm rule).
    """
    if not field_types:
        return ""

    from domains.runtime import get_domain_runtime
    runtime = get_domain_runtime(domain)

    labels_map = dict(_FIELD_LABELS)
    sections_map = dict(_FIELD_SECTION_NAMES)

    if runtime and hasattr(runtime, "config") and runtime.config.field_intents:
        for fi in runtime.config.field_intents:
            k = fi.get("key")
            if k:
                if fi.get("label"):
                    labels_map[k] = fi["label"]
                if fi.get("section_name"):
                    sections_map[k] = fi["section_name"]

    asked_labels = "; ".join(
        labels_map.get(key, key)
        for key in field_types
    )

    asked_sections = ", ".join(
        sections_map.get(key, f"'{key}'")
        for key in field_types
    )

    return (
        f"Câu hỏi này tập trung vào: {asked_labels}. "
        f"Ưu tiên trả lời phần {asked_sections}. "
        "Bạn vẫn có thể đề cập thông tin khác nếu nó liên quan trực tiếp."
    )


# =========================================================
# TEXT HELPERS
# =========================================================

def _extract_text(
    val: object
) -> str:
    """
    Safely extract text from string,
    list, tuple or dictionary.
    """

    if isinstance(val, str):
        return val

    if isinstance(val, list):
        return " ".join(
            _extract_text(item)
            for item in val
            if item
        )

    if isinstance(val, tuple):
        return " ".join(
            _extract_text(item)
            for item in val
            if item
        )

    if isinstance(val, dict):

        if (
            "text" in val
            and isinstance(
                val["text"],
                str
            )
        ):
            return val["text"]

        if "content" in val:
            return _extract_text(
                val["content"]
            )

        return " ".join(
            _extract_text(value)
            for value in val.values()
            if value
        )

    return (
        str(val)
        if val is not None
        else ""
    )


def _format_mapping(
    data: dict | None
) -> str:
    """
    Format dictionary values in a readable way.
    Ignore empty values.
    """

    if not isinstance(data, dict):
        return ""

    lines = []

    for key, value in data.items():

        if value is None:
            continue

        if isinstance(value, str):
            value = value.strip()

            if not value:
                continue

        if isinstance(value, list):
            if not value:
                continue

            value = ", ".join(
                str(item)
                for item in value
            )

        lines.append(
            f"- {key}: {value}"
        )

    return "\n".join(lines)


# =========================================================
# CONTEXT FORMATTER
# =========================================================

def _format_context(
    context: dict | None
) -> str:
    """
    Format all Context Manager components:

    - conversation_summary
    - recent_messages
    - structured_context
    - long_term_memory
    """

    if (
        not isinstance(context, dict)
        or not context
    ):
        return (
            "Không có ngữ cảnh hội thoại trước đó."
        )

    parts = []

    # (Phase 1: Bỏ CONVERSATION SUMMARY)

    # -----------------------------------------------------
    # RECENT MESSAGES
    # -----------------------------------------------------

    recent_messages = context.get(
        "recent_messages",
        []
    )

    if (
        recent_messages
        and isinstance(
            recent_messages,
            list
        )
    ):

        lines = []
        prompt_window = getattr(cfg, "HISTORY_PROMPT_TURNS", 2) * 2
        msgs_to_show = recent_messages[-prompt_window:] if len(recent_messages) > prompt_window else recent_messages

        for message in msgs_to_show:

            if isinstance(
                message,
                dict
            ):

                role = message.get(
                    "role",
                    "user"
                )

                content = _extract_text(
                    message.get(
                        "content",
                        ""
                    )
                )

                if role == "assistant" and len(content) > 200:
                    content = content[:200] + "..."

                if content:
                    lines.append(
                        f"{role}: {content}"
                    )

            elif (
                isinstance(
                    message,
                    (list, tuple)
                )
                and len(message) == 2
            ):

                user_text = _extract_text(
                    message[0]
                )

                assistant_text = _extract_text(
                    message[1]
                )

                if len(assistant_text) > 200:
                    assistant_text = assistant_text[:200] + "..."

                lines.append(
                    f"user: {user_text}"
                )

                lines.append(
                    f"assistant: "
                    f"{assistant_text}"
                )

        if lines:

            parts.append(
                "TIN NHẮN GẦN ĐÂY:\n"
                + "\n".join(lines)
            )

    # -----------------------------------------------------
    # STRUCTURED CONTEXT
    # -----------------------------------------------------

    structured_context = context.get(
        "structured_context",
        {}
    ) or {}

    formatted_structured = (
        _format_mapping(
            structured_context
        )
    )

    if formatted_structured:

        parts.append(
            "STRUCTURED CONTEXT "
            "(dùng để hiểu câu hỏi hiện tại):\n"
            + formatted_structured
        )

    # (Phase 1: Bỏ LONG-TERM MEMORY)

    if not parts:
        return (
            "Không có ngữ cảnh hội thoại trước đó."
        )

    return "\n\n".join(parts)


# =========================================================
# PROMPT BUILDER
# =========================================================

def build_prompt(
    query: str,
    evidence_candidates: list[EvidenceCandidate],
    context: dict | None = None,
    domain: str | None = None
) -> str:
    """
    Build final generation prompt.

    Context is used only to understand:
    - current procedure
    - location
    - intent
    - multi-turn references

    Evidence remains the only factual/legal source
    used to produce the final answer.
    """
    from domains.runtime import get_domain_runtime
    runtime = get_domain_runtime(domain)
    assistant_role = runtime.assistant_role or "chuyên gia tư vấn"

    # =====================================================
    # EVIDENCE
    # =====================================================

    evidence_sections: list[str] = []

    for evidence in evidence_candidates:
        cid = evidence.chunk_id or ""
        category_label = ""
        if cid.endswith("_docs"):
            category_label = " [HỒ SƠ / GIẤY TỜ]"
        elif cid.endswith("_fee"):
            category_label = " [LỆ PHÍ]"
        elif cid.endswith("_time"):
            category_label = " [THỜI GIAN]"
        elif cid.endswith("_method"):
            category_label = " [HÌNH THỨC NỘP / ĐỊA ĐIỂM]"
        elif cid.endswith("_general"):
            category_label = " [TỔNG QUAN]"

        section = (
            f"[{evidence.candidate_id}]{category_label} {evidence.title}\n"
            f"{evidence.content}"
        )

        evidence_sections.append(section)

    evidence_text = "\n\n".join(evidence_sections)

    if not evidence_text:
        evidence_text = "No evidence was provided."

    # =====================================================
    # CONTEXT
    # =====================================================

    context_text = _format_context(context)

    # =====================================================
    # FIELD RESTRICTION
    # =====================================================

    field_types = _detect_field_types(
        query=query,
        context=context,
        domain=domain,
    )

    restriction_text = _build_field_restriction_rule(field_types, domain=domain)

    # =====================================================
    # FINAL PROMPT — GĐ1 mục 2 + Cache-friendly static prefix
    # Tách system/user, 6 quy tắc tích cực, few-shot example.
    # system_block giữ nguyên tuyệt đối cho administrative_procedures
    # để llama-server tái sử dụng KV prefix cache.
    # =====================================================

    focus_directive = (
        f"LƯU Ý TRỌNG TÂM: {restriction_text}\n\n" if restriction_text else ""
    )

    if domain and domain != "administrative_procedures":
        system_block = f"""Bạn là {assistant_role} ({runtime.persona}) và chính xác.

QUY TẮC:
1. Diễn đạt rõ ràng, thân thiện, dễ hiểu, QUAN TRỌNG LÀ PHẢI BÁM SÁT BẰNG CHỨNG ĐƯỢC CUNG CẤP, KHÔNG ĐƯA Ý KIẾN HAY KIẾN THỨC RIÊNG VÀO CÂU TRẢ LỜI.
2. Giữ nguyên chính xác: địa danh, mức giá, thời gian, dịch vụ.
3. Nếu người dùng hỏi nhiều ý, hãy trả lời đầy đủ từng ý theo cấu trúc rõ ràng.
4. Ý nào bằng chứng không đề cập → nói rõ "{runtime.no_evidence_message or 'chưa có thông tin về phần này'}". KHÔNG tự suy đoán.
5. Trả lời bằng tiếng Việt, tự nhiên, sinh động.
6. Chỉ dùng thông tin từ phần BẰNG CHỨNG — không bịa đặt kiến thức ngoài.
"""
    else:
        system_block = f"""Bạn là {assistant_role} thân thiện và chính xác.

QUY TẮC:
1. Diễn đạt rõ ràng dễ hiểu, QUAN TRỌNG LÀ PHẢI BÁM SÁT BẰNG CHỨNG ĐƯỢC CUNG CẤP, KHÔNG ĐƯA Ý KIẾN HAY KIẾN THỨC RIÊNG VÀO CÂU TRẢ LỜI  .
1b. ĐẶC BIỆT CHÚ Ý TÍNH PHỦ ĐỊNH: Nếu bằng chứng ghi 'KHÔNG CẦN', 'KHÔNG PHẢI NỘP', 'MIỄN' giấy tờ/thủ tục nào, tuyệt đối KHÔNG được viết thành 'cần' hay 'phải nộp'. Phải giữ nguyên nghĩa phủ định/miễn trừ theo bằng chứng.
2. Giữ nguyên chính xác: số tiền, thời hạn, tên giấy tờ, tên cơ quan.
3. Nếu người dùng hỏi nhiều ý (multi-intent: vừa hỏi giấy tờ, vừa hỏi thời gian hay lệ phí), hãy trả lời đầy đủ từng ý theo cấu trúc rõ ràng.
4. Ý nào bằng chứng không đề cập → nói rõ "chưa có thông tin về phần này". KHÔNG tự suy đoán.
5. Cuối câu trả lời, gợi ý một điều người dùng có thể hỏi tiếp.
6. Trả lời bằng tiếng Việt, rõ ràng, tự nhiên, không chèn tiếng khác vào (nhất là tiếng trung) vào câu trả lời.
7. Chỉ dùng thông tin từ phần BẰNG CHỨNG — không dùng kiến thức riêng.
8. Một câu trả lời cần chứa tối thiểu thông tin về tên thủ tục (được in đậm và tách ra dòng riêng để người dùng đọc vào là biết tên thủ tục). Các thông tin còn lại phải được viết rõ ràng, có bullet cho từng thông tin, không viết chùm chùm.
9. Người dùng hỏi gì thì trả lời đó không trả lời dư: ví dụ người dùng hỏi lệ phí thủ tục đăng kí kết hôn thì chỉ trả thủ tục đăng kí kết hôn.
10. Sau khi đưa ra câu trả lời về thủ tục cho người dùng thì hãy kết câu bằng: "Bạn muốn hỏi thêm về thông tin thủ tục nào không?"

ĐÂY LÀ MẪU THỦ TỤC ĐỂ THAM KHẢO (KHÔNG COPY HAY BÊ Y NGUYÊN VÀO CÂU TRẢ LỜI, CHỈ TRẢ LỜI THEO FORMAT NÀY)
Tên thủ tục: [Tên thủ tục]
 - Hình thức nộp: [Thông tin về hình thức nộp]
 - Thành phần hồ sơ: [Thông tin về thành phần hồ sơ]
 - Lệ phí: [Thông tin về lệ phí]
 - Thời gian giải quyết: [Thông tin về thời gian]
 - Địa chỉ cơ quan tiếp nhận hồ sơ: [Thông tin về địa chỉ cơ quan tiếp nhận hồ sơ]
"""

    user_block = f"""{focus_directive}NGỮ CẢNH HỘI THOẠI:
{context_text}

BẰNG CHỨNG:
{evidence_text}

CÂU HỎI: {query}

Hãy trả lời dựa trên bằng chứng trên, diễn đạt tự nhiên, kèm citation [xxx] ở cuối đoạn dùng thông tin đó."""

    # Kết hợp thành một prompt duy nhất
    prompt = f"{system_block}\n\n{user_block}"

    return prompt
