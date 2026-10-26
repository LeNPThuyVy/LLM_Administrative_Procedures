import pytest
from domains.administrative_procedures.schema import ProcedureDocument
from ingestion.dedup import SimilarityDeduplicator

def test_dedup_duplicates_removed():
    dedup = SimilarityDeduplicator(threshold=0.90)
    
    doc1 = ProcedureDocument(
        document_id="PROC_001",
        title="Đăng ký khai sinh",
        content="Nội dung dài cho thủ tục khai sinh trực tiếp hoặc trực tuyến"
    )
    doc2 = ProcedureDocument(
        document_id="PROC_002",
        title="Đăng ký khai sinh (trùng)",
        content="Nội dung ngắn"
    )
    
    # Vectors with high similarity (cos = 0.9999)
    vec1 = [1.0, 0.0, 0.0]
    vec2 = [0.99, 0.01, 0.0]
    
    result = dedup.deduplicate([doc1, doc2], [vec1, vec2])
    assert len(result.kept) == 1
    assert result.kept[0].document_id == "PROC_001"  # doc1 content is longer
    assert len(result.removed) == 1
    assert result.removed[0]["removed_id"] == "PROC_002"
    assert result.removed[0]["kept_id"] == "PROC_001"

def test_dedup_no_duplicates():
    dedup = SimilarityDeduplicator(threshold=0.90)
    
    doc1 = ProcedureDocument(document_id="PROC_001", title="Khai sinh", content="Content 1")
    doc2 = ProcedureDocument(document_id="PROC_002", title="Kết hôn", content="Content 2")
    
    # Orthogonal vectors (cos = 0.0)
    vec1 = [1.0, 0.0, 0.0]
    vec2 = [0.0, 1.0, 0.0]
    
    result = dedup.deduplicate([doc1, doc2], [vec1, vec2])
    assert len(result.kept) == 2
    assert len(result.removed) == 0

def test_dedup_mismatched_lengths():
    dedup = SimilarityDeduplicator()
    doc1 = ProcedureDocument(document_id="PROC_001", title="A")
    with pytest.raises(ValueError):
        dedup.deduplicate([doc1], [[1.0], [2.0]])
