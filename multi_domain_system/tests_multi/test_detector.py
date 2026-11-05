import pytest
from rag.multi.detector import detect_sub_queries
from domains.runtime import DomainConfig

def test_detect_single_procedure():
    query = "Lệ phí xác nhận tình trạng hôn nhân bao nhiêu tiền?"
    domain = "administrative_procedures"
    
    sub_queries, truncated = detect_sub_queries(query, {}, domain)
    
    assert truncated is False
    assert len(sub_queries) == 1
    assert sub_queries[0].procedure_hint == "Thủ tục xác nhận tình trạng hôn nhân"
    assert "fee" in sub_queries[0].fields

def test_detect_multiple_procedures():
    query = "Tôi muốn đăng ký kết hôn và khai sinh cho con, hồ sơ cần những gì?"
    domain = "administrative_procedures"
    
    sub_queries, truncated = detect_sub_queries(query, {}, domain)
    
    assert truncated is False
    assert len(sub_queries) == 2
    # Verify titles
    titles = [q.procedure_hint for q in sub_queries]
    assert "Thủ tục đăng ký kết hôn" in titles
    assert "Thủ tục đăng ký khai sinh" in titles
    
    # Verify shared field (hồ sơ cần những gì -> required_documents)
    for q in sub_queries:
        assert "required_documents" in q.fields

def test_max_procedures_truncation():
    # Simulate a query asking for 9 procedures
    procs = [
        "đăng ký kết hôn", "khai sinh", "khai tử", "nhận cha",
        "tình trạng hôn nhân", "nội quy lao động", "vay vốn", "di chúc", "chuyển trường", "học bổng"
    ]
    query = ", ".join(procs)
    domain = "administrative_procedures"
    
    sub_queries, truncated = detect_sub_queries(query, {}, domain)
    
    assert truncated is True
    assert len(sub_queries) == 8
