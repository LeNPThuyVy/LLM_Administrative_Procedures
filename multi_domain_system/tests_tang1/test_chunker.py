import pytest
from domains.domain_loader import load_domain_config
from domains.administrative_procedures.schema import ProcedureDocument
from ingestion.chunker import FieldChunker, Chunk

def test_field_chunker():
    config = load_domain_config("administrative_procedures")
    chunker = FieldChunker(config)
    
    doc = ProcedureDocument(
        document_id="PROC_001",
        title="Đăng ký kết hôn",
        required_documents="Tờ khai đăng ký kết hôn, CCCD",
        fee="Miễn phí",
        processing_time="Trong ngày",
        submission_method="Nộp trực tiếp",
        submission_location="Ủy ban nhân dân xã/phường",
        content="Nội dung chi tiết quy trình đăng ký kết hôn..."
    )
    
    chunks = chunker.chunk(doc)
    assert len(chunks) > 0
    chunk_map = {c.metadata["field"]: c for c in chunks}
    
    assert "required_documents" in chunk_map
    assert chunk_map["required_documents"].chunk_id == "PROC_001_docs"
    assert "Tờ khai đăng ký kết hôn" in chunk_map["required_documents"].text
    
    assert "fee" in chunk_map
    assert chunk_map["fee"].chunk_id == "PROC_001_fee"
    assert "Miễn phí" in chunk_map["fee"].text
    
    assert "submission_method" in chunk_map
    assert chunk_map["submission_method"].chunk_id == "PROC_001_method"
    # Should combine method and location
    assert "Nộp trực tiếp" in chunk_map["submission_method"].text
    assert "Ủy ban nhân dân" in chunk_map["submission_method"].text
    
    assert "general" in chunk_map
    assert chunk_map["general"].chunk_id == "PROC_001_general"
