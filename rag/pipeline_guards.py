from __future__ import annotations

import logging
import re
import unicodedata

from guardrails.input import mask_sensitive_for_log, validate_input
from rag.mapper import AnswerResponse

logger = logging.getLogger(__name__)

FALLBACK_TEXT = (
    "Thông tin trong tài liệu được cung cấp "
    "chưa đủ để trả lời câu hỏi này."
)

LOCATION_NOT_SUPPORTED_TEXT = (
    "Hiện tại hệ thống chỉ hỗ trợ tra cứu các thủ tục hành chính công áp dụng tại Thành phố Hồ Chí Minh."
)

# Danh sách tỉnh / thành phố lớn ngoài TP.HCM để phát hiện out-of-scope nhanh
_NON_HCMC_PATTERNS = re.compile(
    r"\b(hà nội|hà nam|hải phòng|đà nẵng|hải dương|bắc ninh|quảng ninh|"
    r"thanh hóa|nghệ an|hà tĩnh|huế|thừa thiên huế|quảng bình|quảng trị|"
    r"quảng nam|quảng ngãi|bình định|phú yên|khánh hòa|nha trang|"
    r"ninh thuận|bình thuận|cần thơ|an giang|đồng tháp|tiền giang|"
    r"kiên giang|bến tre|vĩnh long|trà vinh|sóc trăng|bạc liêu|cà mau|"
    r"bình phước|tây ninh|bình dương|đồng nai|vũng tàu|bà rịa)\b",
    re.IGNORECASE | re.UNICODE,
)

GENERIC_PROCEDURE_PATTERNS = {
    "lam thu tuc",
    "toi muon lam thu tuc",
    "toi can lam thu tuc",
    "toi muon hoi thu tuc",
    "toi can hoi thu tuc",
    "can lam thu tuc",
    "muon lam thu tuc",
}

OUT_OF_SCOPE_TOPICS = [
    "hộ chiếu", "visa", "giấy phép lái xe", "bằng lái", "đổi bằng lái",
    "giá xăng", "hàng không vũ trụ",
]


def extract_text(val: object) -> str:
    """Safely extract string text from string, list, or dict message content."""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        return " ".join(extract_text(item) for item in val if item)
    if isinstance(val, dict):
        if "text" in val and isinstance(val["text"], str):
            return val["text"]
        if "content" in val:
            return extract_text(val["content"])
        return " ".join(extract_text(v) for v in val.values() if v)
    return str(val) if val is not None else ""


def fold_vietnamese_text(text: str) -> str:
    """Normalize Vietnamese text to lowercase ASCII for robust matching."""
    text = str(text or "").lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    return "".join(
        ch for ch in text
        if unicodedata.category(ch) != "Mn"
    )


def is_underspecified_procedure_query(text: str) -> bool:
    """
    Detect generic requests that do not identify any actual procedure.
    Examples:
    - Tôi muốn làm thủ tục
    - Tôi cần làm thủ tục
    - Làm thủ tục
    """
    q = fold_vietnamese_text(text)
    q = re.sub(r"[^a-z0-9\s]", " ", q)
    q = re.sub(r"\s+", " ", q).strip()

    return q in GENERIC_PROCEDURE_PATTERNS


def detect_unsupported_location(text: str, domain: str | None = None) -> bool:
    """
    Return True if text contains a Vietnamese location that is
    explicitly NOT supported by the current domain.

    - Nếu domain không cấu hình supported_locations: trả False.
    - Nếu domain là administrative_procedures (hoặc rỗng): dùng _NON_HCMC_PATTERNS.
    - Với các domain khác: nếu câu hỏi chứa supported_locations của domain thì luôn cho phép;
      chỉ từ chối nếu có địa phương rõ ràng ngoài phạm vi.
    """
    from domains.runtime import get_domain_runtime
    runtime = get_domain_runtime(domain)
    if not runtime.supported_locations:
        return False

    text_lower = text.lower()
    has_supported_loc = any(loc.lower() in text_lower for loc in runtime.supported_locations if loc)

    if domain == "administrative_procedures" or not domain:
        if has_supported_loc:
            return False
        return bool(_NON_HCMC_PATTERNS.search(text))

    if has_supported_loc:
        return False

    return bool(_NON_HCMC_PATTERNS.search(text))


def check_early_guards(
    query: str,
    domain: str | None,
    effective_mode: str,
    runtime,
    risk_result,
) -> AnswerResponse | None:
    """
    Check early exits and guards before expensive retrieval/synthesis.
    Returns AnswerResponse if request is intercepted, else None.
    """
    input_guard = validate_input(query)
    if not input_guard.allowed:
        logger.warning(
            "[guardrail] Blocked input: %s | %s",
            input_guard.reason,
            mask_sensitive_for_log(query),
        )
        return AnswerResponse(
            answer="Yêu cầu này không thể được xử lý vì vi phạm quy tắc an toàn.",
            claims=[],
            needs_clarification=False,
            clarification_question=None,
            domain=domain,
            mode=effective_mode,
            tool_calls=[],
        )

    if not query or not query.strip():
        return AnswerResponse(
            answer="",
            claims=[],
            needs_clarification=False,
            clarification_question=None,
            domain=domain,
            mode=effective_mode,
            tool_calls=[],
        )

    # 1. Early safety reject for medical emergencies & poisoning in non-medical domain
    if any(r == "medical" or "ngộ độc" in r or "cấp cứu" in r for r in risk_result.reasons):
        q_low = query.lower()
        if any(w in q_low for w in ["uống thuốc", "thuốc gì", "khó thở", "ngộ độc", "cấp cứu", "sơ cứu", "chữa trị", "bệnh viện"]):
            return AnswerResponse(
                answer=(
                    "Hệ thống không thể tư vấn về y tế, dùng thuốc hoặc sơ cứu điều trị tại nhà. "
                    "Trong trường hợp khẩn cấp hoặc có dấu hiệu ngộ độc, khó thở, vui lòng liên hệ ngay cơ sở y tế gần nhất "
                    "hoặc gọi cấp cứu 115 để được hỗ trợ chuyên môn kịp thời."
                ),
                claims=[],
                needs_clarification=False,
                clarification_question=None,
                domain=domain,
                mode=effective_mode,
                tool_calls=[],
            )

    # 2. Generic / underspecified procedure clarification
    if is_underspecified_procedure_query(query):
        clarification = (
            "Bạn muốn thực hiện thủ tục nào? "
            "Vui lòng cho biết tên thủ tục cụ thể "
            "để tôi hỗ trợ."
        )
        logger.info(
            "[pipeline] Generic procedure query requires clarification: %r",
            query[:100],
        )
        return AnswerResponse(
            answer=clarification,
            claims=[],
            needs_clarification=True,
            clarification_question=clarification,
            domain=domain,
            mode=effective_mode,
            tool_calls=[],
        )

    # 3. Out-of-scope location detection
    if detect_unsupported_location(query, domain=domain):
        logger.info(
            "[pipeline] Unsupported location in current query: %r",
            query[:100],
        )
        reject_message = (
            runtime.config.out_of_scope_message
            if hasattr(runtime, "config") and runtime.config.out_of_scope_message
            else LOCATION_NOT_SUPPORTED_TEXT
        )
        return AnswerResponse(
            answer=reject_message,
            claims=[],
            needs_clarification=False,
            clarification_question=None,
            domain=domain,
            mode=effective_mode,
            tool_calls=[],
        )

    # 4. Out of scope non-jurisdiction topics
    q_norm_lower = query.lower()
    is_out_of_scope = any(re.search(r"\b" + re.escape(t) + r"\b", q_norm_lower) for t in OUT_OF_SCOPE_TOPICS)
    if is_out_of_scope and not any(w in q_norm_lower for w in ["kết hôn", "hôn nhân"]):
        logger.info("[pipeline] Out of scope topic detected in query: %s", query[:60])
        out_msg = (
            "Thủ tục hoặc thông tin bạn hỏi (hộ chiếu, visa, giấy phép lái xe, v.v.) hiện không thuộc "
            "thẩm quyền giải quyết của bộ phận một cửa cấp xã/phường hoặc không có trong cơ sở dữ liệu."
        )
        if runtime.disclaimer:
            out_msg = f"{out_msg}\n\n{runtime.disclaimer}"
        return AnswerResponse(
            answer=out_msg,
            claims=[],
            needs_clarification=False,
            clarification_question=None,
            domain=domain,
            mode=effective_mode,
            tool_calls=[],
        )

    return None

