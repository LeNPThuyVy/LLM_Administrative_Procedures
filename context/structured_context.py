import re
import unicodedata
from copy import deepcopy
from typing import Any, Dict, List


DEFAULT_STRUCTURED_CONTEXT: Dict[str, Any] = {
    "intent": None,
    "procedure_name": None,
    "location": None,
    "method": None,
    "documents": [],
    "fee": None,
    "processing_time": None,
    "applicant_type": None,
}


def normalize_text(text: str) -> str:
    """
    Chuẩn hóa khoảng trắng.
    Giữ nguyên tiếng Việt có dấu để trả kết quả đẹp hơn.
    """
    if not text:
        return ""

    return " ".join(text.strip().split())


def remove_accents(text: str) -> str:
    """
    Tạo bản không dấu để hỗ trợ so khớp từ khóa.
    """
    normalized = unicodedata.normalize("NFD", text)

    return "".join(
        ch
        for ch in normalized
        if unicodedata.category(ch) != "Mn"
    ).replace("đ", "d").replace("Đ", "D")


def normalize_for_match(text: str) -> str:
    text = normalize_text(text).lower()
    return remove_accents(text)


def extract_intent(text: str):
    lowered = normalize_for_match(text)

    rules = [
        (
            "hỏi thành phần hồ sơ",
            [
                "ho so",
                "giay to gi",
                "can giay to gi",
                "can chuan bi",
                "thanh phan ho so",
                "giay to can thiet",
            ],
        ),
        (
            "hỏi lệ phí",
            [
                "le phi",
                "phi bao nhieu",
                "mat bao nhieu",
                "chi phi",
                "dong bao nhieu",
            ],
        ),
        (
            "hỏi thời gian xử lý",
            [
                "bao lau",
                "mat bao lau",
                "thoi gian",
                "may ngay",
                "giai quyet trong",
            ],
        ),
        (
            "hỏi cách thực hiện",
            [
                "lam nhu the nao",
                "cach lam",
                "thuc hien nhu the nao",
                "nop o dau",
                "nop online",
                "nop truc tuyen",
                "nop truc tiep",
            ],
        ),
        (
            "hỏi điều kiện",
            [
                "dieu kien",
                "co du dieu kien",
                "yeu cau gi",
            ],
        ),
        (
            "hỏi thủ tục",
            [
                "thu tuc",
                "muon lam",
                "dang ky",
                "xin cap",
                "cap lai",
                "gia han",
            ],
        ),
    ]

    for intent, keywords in rules:
        if any(keyword in lowered for keyword in keywords):
            return intent

    return None


def extract_procedure_name(text: str):
    text_clean = normalize_text(text)
    lowered = normalize_for_match(text_clean)

    # Tránh hiểu tên giấy tờ thành tên thủ tục
    document_only_phrases = [
        "giay khai sinh",
        "giay chung nhan",
        "giay xac nhan cu tru",
        "can cuoc cong dan",
        "cccd",
        "cmnd",
        "so ho khau",
        "to khai",
        "don de nghi",
    ]

    # Nếu câu chủ yếu nói về giấy tờ và không có động từ làm thủ tục
    procedure_action_words = [
        "dang ky",
        "lam thu tuc",
        "muon lam",
        "can lam",
        "xin cap",
        "cap lai",
        "gia han",
        "lam ho chieu",
        "lam cccd",
    ]

    has_document_phrase = any(
        phrase in lowered
        for phrase in document_only_phrases
    )

    has_procedure_action = any(
        phrase in lowered
        for phrase in procedure_action_words
    )

    if has_document_phrase and not has_procedure_action:
        return None

    procedures = {
        "Đăng ký thường trú": [
            "dang ky thuong tru",
            "lam thu tuc thuong tru",
        ],

        "Đăng ký tạm trú": [
            "dang ky tam tru",
            "lam thu tuc tam tru",
        ],

        "Đăng ký hộ kinh doanh": [
            "dang ky ho kinh doanh",
        ],

        "Cấp căn cước công dân": [
            "cap can cuoc cong dan",
            "lam cccd",
            "cap cccd",
        ],

        "Cấp lại căn cước công dân": [
            "cap lai can cuoc cong dan",
            "cap lai cccd",
        ],

        "Đăng ký khai sinh": [
            "dang ky khai sinh",
            "lam thu tuc khai sinh",
        ],

        "Đăng ký kết hôn": [
            "dang ky ket hon",
            "lam thu tuc ket hon",
        ],

        "Cấp hộ chiếu": [
            "cap ho chieu",
            "lam ho chieu",
        ],
    }

    for procedure_name, keywords in procedures.items():
        if any(keyword in lowered for keyword in keywords):
            return procedure_name

    generic_patterns = [
        r"(?:muốn|cần)\s+làm\s+thủ\s+tục\s+([^,.!?]+)",
        r"(đăng\s+ký\s+[^,.!?]+)",
        r"(cấp\s+lại\s+[^,.!?]+)",
        r"(gia\s+hạn\s+[^,.!?]+)",
    ]

    for pattern in generic_patterns:
        match = re.search(
            pattern,
            text_clean,
            flags=re.IGNORECASE
        )

        if match:
            value = match.group(1).strip()

            if len(value) <= 80:
                return value[0].upper() + value[1:]

    return None


def extract_location(text: str):
    lowered = normalize_for_match(text)

    locations = {
        "TP.HCM": [
            "tp.hcm",
            "tphcm",
            "ho chi minh",
            "sai gon",
            "thanh pho ho chi minh",
        ],
        "Hà Nội": [
            "ha noi",
        ],
        "Đà Nẵng": [
            "da nang",
        ],
        "Bình Dương": [
            "binh duong",
        ],
        "Đồng Nai": [
            "dong nai",
        ],
        "Cần Thơ": [
            "can tho",
        ],
        "Bà Rịa - Vũng Tàu": [
            "ba ria vung tau",
            "vung tau",
        ],
    }

    for location_name, keywords in locations.items():
        if any(keyword in lowered for keyword in keywords):
            return location_name

    return None


def extract_method(text: str):
    lowered = normalize_for_match(text)

    if any(
        keyword in lowered
        for keyword in [
            "online",
            "truc tuyen",
            "qua mang",
            "cong dich vu cong",
        ]
    ):
        return "Trực tuyến"

    if any(
        keyword in lowered
        for keyword in [
            "truc tiep",
            "den nop",
            "nop tai",
        ]
    ):
        return "Trực tiếp"

    if any(
        keyword in lowered
        for keyword in [
            "buu dien",
            "buu chinh",
        ]
    ):
        return "Bưu chính"

    return None


def extract_documents(text: str) -> List[str]:
    lowered = normalize_for_match(text)

    document_rules = {
        "CCCD": [
            "cccd",
            "can cuoc cong dan",
            "can cuoc",
        ],
        "CMND": [
            "cmnd",
            "chung minh nhan dan",
        ],
        "Giấy khai sinh": [
            "giay khai sinh",
        ],
        "Sổ hộ khẩu": [
            "so ho khau",
        ],
        "Giấy chứng nhận": [
            "giay chung nhan",
        ],
        "Đơn đề nghị": [
            "don de nghi",
        ],
        "Tờ khai": [
            "to khai",
        ],
        "Giấy xác nhận cư trú": [
            "giay xac nhan cu tru",
        ],
        "Hộ chiếu": [
            "ho chieu",
        ],
    }

    found: List[str] = []

    for document_name, keywords in document_rules.items():
        if any(keyword in lowered for keyword in keywords):
            found.append(document_name)

    return found


def extract_fee(text: str):
    text_clean = normalize_text(text)

    patterns = [
        r"\b\d{1,3}(?:[.,]\d{3})+\s*(?:đồng|vnđ|vnd)\b",
        r"\b\d+(?:[.,]\d+)?\s*(?:nghìn|ngàn)\s*(?:đồng)?\b",
        r"\b\d+(?:[.,]\d+)?\s*triệu\s*(?:đồng)?\b",
        r"\b\d+\s*(?:đồng|vnđ|vnd)\b",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text_clean,
            flags=re.IGNORECASE
        )

        if match:
            return match.group(0).strip()

    return None


def extract_processing_time(text: str):
    text_clean = normalize_text(text)

    patterns = [
        r"\b\d+\s*ngày\s*làm\s*việc\b",
        r"\b\d+\s*ngày\b",
        r"\b\d+\s*tuần\b",
        r"\b\d+\s*tháng\b",
        r"\b\d+\s*giờ\b",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text_clean,
            flags=re.IGNORECASE
        )

        if match:
            return match.group(0).strip()

    return None


def extract_applicant_type(text: str):
    lowered = normalize_for_match(text)

    applicant_rules = {
        "Cá nhân": [
            "ca nhan",
            "nguoi dan",
            "toi",
            "minh",
        ],
        "Doanh nghiệp": [
            "doanh nghiep",
            "cong ty",
        ],
        "Hộ kinh doanh": [
            "ho kinh doanh",
        ],
        "Người nước ngoài": [
            "nguoi nuoc ngoai",
        ],
        "Trẻ em": [
            "tre em",
            "tre duoi",
        ],
    }

    for applicant_type, keywords in applicant_rules.items():
        if any(keyword in lowered for keyword in keywords):
            return applicant_type

    return None


def _merge_documents(
    old_documents: List[str],
    new_documents: List[str]
) -> List[str]:
    result = list(old_documents or [])

    for item in new_documents:
        if item not in result:
            result.append(item)

    return result


def extract_structured_context(
    message: str,
    old_context: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    """
    Trích structured context từ một lượt chat.

    Quy tắc multi-turn:
    - field mới có giá trị -> cập nhật
    - field không tìm thấy -> giữ giá trị cũ
    - documents -> cộng dồn, không ghi đè
    """

    if old_context:
        context = deepcopy(DEFAULT_STRUCTURED_CONTEXT)

        for key, value in old_context.items():
            context[key] = deepcopy(value)

    else:
        context = deepcopy(DEFAULT_STRUCTURED_CONTEXT)

    text = normalize_text(message)

    extracted = {
        "intent": extract_intent(text),
        "procedure_name": extract_procedure_name(text),
        "location": extract_location(text),
        "method": extract_method(text),
        "fee": extract_fee(text),
        "processing_time": extract_processing_time(text),
        "applicant_type": extract_applicant_type(text),
    }

    for key, value in extracted.items():
        if value is not None:
            context[key] = value

    new_documents = extract_documents(text)

    context["documents"] = _merge_documents(
        context.get("documents", []),
        new_documents
    )

    return context


if __name__ == "__main__":
    context = None

    test_messages = [
        "Tôi muốn làm thủ tục đăng ký thường trú ở TP.HCM",
        "Tôi cần chuẩn bị giấy tờ gì?",
        "Tôi đã có CCCD và giấy khai sinh",
        "Tôi muốn nộp online",
        "Lệ phí 20000 đồng phải không?",
        "Thời gian xử lý khoảng 7 ngày phải không?"
    ]

    for message in test_messages:
        context = extract_structured_context(
            message=message,
            old_context=context
        )

        print("=" * 60)
        print("USER:")
        print(message)

        print("\nSTRUCTURED CONTEXT:")
        print(context)