import re
import unicodedata

ABBREVIATIONS = {
    r"\bdk\b": "đăng ký",
    r"\bdky\b": "đăng ký",
    r"\bđk\b": "đăng ký",
    r"\bgpxd\b": "giấy phép xây dựng",
    r"\bbn\b": "bao nhiêu",
    r"\bbao nhiu\b": "bao nhiêu",
    r"\bmk\b": "mình",
    r"\btphcm\b": "thành phố hồ chí minh",
    r"\btp\.hcm\b": "thành phố hồ chí minh",
    r"\bko\b": "không",
    r"\bkhg\b": "không",
    r"\bj\b": "gì",
    r"\bdc\b": "được",
    r"\bđc\b": "được",
    r"\bthoi zan\b": "thời gian",
    r"\bkhai sih\b": "khai sinh",
    r"\bubnd\b": "ủy ban nhân dân",
    r"\bcccd\b": "căn cước công dân",
    r"\bcmnd\b": "chứng minh nhân dân",
}

# Vietnamese accent mapping for fast fold
_ACCENTS_MAP = {
    ord("à"): "a",
    ord("á"): "a",
    ord("ả"): "a",
    ord("ã"): "a",
    ord("ạ"): "a",
    ord("ă"): "a",
    ord("ằ"): "a",
    ord("ắ"): "a",
    ord("ẳ"): "a",
    ord("ẵ"): "a",
    ord("ặ"): "a",
    ord("â"): "a",
    ord("ầ"): "a",
    ord("ấ"): "a",
    ord("ẩ"): "a",
    ord("ẫ"): "a",
    ord("ậ"): "a",
    ord("è"): "e",
    ord("é"): "e",
    ord("ẻ"): "e",
    ord("ẽ"): "e",
    ord("ẹ"): "e",
    ord("ê"): "e",
    ord("ề"): "e",
    ord("ế"): "e",
    ord("ể"): "e",
    ord("ễ"): "e",
    ord("ệ"): "e",
    ord("ì"): "i",
    ord("í"): "i",
    ord("ỉ"): "i",
    ord("ĩ"): "i",
    ord("ị"): "i",
    ord("ò"): "o",
    ord("ó"): "o",
    ord("ỏ"): "o",
    ord("õ"): "o",
    ord("ọ"): "o",
    ord("ô"): "o",
    ord("ồ"): "o",
    ord("ố"): "o",
    ord("ổ"): "o",
    ord("ỗ"): "o",
    ord("ộ"): "o",
    ord("ơ"): "o",
    ord("ờ"): "o",
    ord("ớ"): "o",
    ord("ở"): "o",
    ord("ỡ"): "o",
    ord("ợ"): "o",
    ord("ù"): "u",
    ord("ú"): "u",
    ord("ủ"): "u",
    ord("ũ"): "u",
    ord("ụ"): "u",
    ord("ư"): "u",
    ord("ừ"): "u",
    ord("ứ"): "u",
    ord("ử"): "u",
    ord("ữ"): "u",
    ord("ự"): "u",
    ord("ỳ"): "y",
    ord("ý"): "y",
    ord("ỷ"): "y",
    ord("ỹ"): "y",
    ord("ỵ"): "y",
    ord("đ"): "d",
}


def fold_accents(text: str) -> str:
    """Strip Vietnamese diacritics and convert to lowercase ASCII."""
    if not text:
        return ""
    return text.lower().translate(_ACCENTS_MAP)


def normalize_query_text(text: str) -> str:
    """Expand common chat abbreviations and typos in Vietnamese queries."""
    if not text:
        return ""
    result = text.strip()
    for pattern, replacement in ABBREVIATIONS.items():
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result
