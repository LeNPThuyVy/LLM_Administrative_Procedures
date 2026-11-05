import pytest
from pathlib import Path
from ingestion.loaders import get_loader, JSONLoader, CSVLoader, PDFLoader, DOCXLoader, WebLoader
from ingestion.loaders.base_loader import RawDocument

def test_json_loader():
    loader = get_loader("json")
    assert isinstance(loader, JSONLoader)
    
    # Test loading actual procedures.json
    results = loader.load({"path": "data/procedures.json"})
    assert len(results) > 0
    assert isinstance(results[0], RawDocument)
    assert "document_id" in results[0].metadata

def test_csv_loader(tmp_path):
    csv_file = tmp_path / "test.csv"
    csv_file.write_text("document_id,title,fee\nPROC_99,Test Procedure,50000 VNĐ\n", encoding="utf-8")
    
    loader = get_loader("csv")
    assert isinstance(loader, CSVLoader)
    
    results = loader.load({"path": str(csv_file)})
    assert len(results) == 1
    assert results[0].metadata["document_id"] == "PROC_99"
    assert results[0].metadata["title"] == "Test Procedure"

def test_get_loader_invalid():
    with pytest.raises(ValueError):
        get_loader("unsupported_format")
