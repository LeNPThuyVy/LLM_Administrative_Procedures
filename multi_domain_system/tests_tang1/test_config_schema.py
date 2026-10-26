import pytest
from pathlib import Path

from domains import list_domains
from domains.domain_loader import load_domain_config, DomainConfig
from domains.administrative_procedures.schema import ProcedureDocument
from ingestion.schema_validator import validate_documents
from ingestion.loaders.base_loader import RawDocument

def test_list_domains():
    domains = list_domains()
    assert "administrative_procedures" in domains

def test_load_domain_config_success():
    config = load_domain_config("administrative_procedures")
    assert isinstance(config, DomainConfig)
    assert config.domain_id == "administrative_procedures"
    assert config.embedding_model == "BAAI/bge-m3"
    assert config.embedding_dim == 1024
    assert config.collection_name == "administrative_procedures"
    assert "required_documents" in config.chunk_fields

def test_load_domain_config_not_found():
    with pytest.raises(FileNotFoundError):
        load_domain_config("non_existent_domain_xyz")

def test_schema_validation_valid():
    raw_data = [
        RawDocument(
            source_path="test.json",
            raw_text="",
            metadata={
                "document_id": "TEST_001",
                "title": "Thủ tục thử nghiệm",
                "document_type": "TTHC",
                "category": "Hộ tịch",
                "fee": "10.000 VNĐ",
            }
        )
    ]
    valid, errors = validate_documents(raw_data, ProcedureDocument)
    assert len(valid) == 1
    assert len(errors) == 0
    assert valid[0].document_id == "TEST_001"
    assert valid[0].fee == "10.000 VNĐ"

def test_schema_validation_invalid():
    # Missing required field title
    raw_data = [
        RawDocument(
            source_path="test.json",
            raw_text="",
            metadata={
                "document_id": "TEST_002",
                # missing title
            }
        )
    ]
    valid, errors = validate_documents(raw_data, ProcedureDocument)
    assert len(valid) == 0
    assert len(errors) == 1
    assert errors[0]["document_id"] == "TEST_002"
