import pytest
import os
import subprocess
import my_config as cfg
from qdrant_client import QdrantClient
from rag.retrieval import retrieve, retrieve_two_step

def test_e2e_full_ingestion_and_retrieval():
    assert cfg.QDRANT_URL, "QDRANT_URL is required for E2E testing"
    
    domain_id = "administrative_procedures"
    
    # 1. Run Ingestion Pipeline (--force)
    pipeline_proc = subprocess.run(
        ["py", "-3.12", "scripts/run_ingestion.py", "--domain", domain_id, "--force"],
        capture_output=True,
        cwd=str(cfg.BASE_DIR)
    )
    stdout = pipeline_proc.stdout.decode("utf-8", errors="ignore") if pipeline_proc.stdout else ""
    stderr = pipeline_proc.stderr.decode("utf-8", errors="ignore") if pipeline_proc.stderr else ""
    
    assert pipeline_proc.returncode == 0, f"Ingestion failed:\nSTDERR:\n{stderr}"
    assert "Chunks" in stdout or "Total chunks" in stdout or "195" in stdout, f"Ingestion output did not match:\n{stdout}"
    
    # 2. Check Qdrant Cloud Collection Status
    client = QdrantClient(url=cfg.QDRANT_URL, api_key=cfg.QDRANT_API_KEY or None)
    collection_name = cfg.COLLECTION_NAME
    info = client.get_collection(collection_name)
    assert info.points_count > 0, "Qdrant collection must not be empty after ingestion"
    assert info.config.params.vectors.size == 1024, "Vector size must be 1024 (BGE-M3)"
    
    # 3. Test Retrieval Runtime
    chunks = retrieve("Hồ sơ đăng ký kết hôn cần những gì?", top_k=5)
    assert len(chunks) > 0, "retrieve() should return relevant chunks"
    # Marriage registration is PROC_004 (or PROC_006 / PROC_001)
    retrieved_doc_ids = [c.document_id for c in chunks]
    assert any(doc_id in ["PROC_004", "PROC_001", "PROC_006"] for doc_id in retrieved_doc_ids), f"Should retrieve PROC_004 for marriage registration query, got: {retrieved_doc_ids}"
    
    two_step_chunks = retrieve_two_step("Hồ sơ đăng ký kết hôn cần những gì?", top_k=5)
    assert len(two_step_chunks) > 0, "retrieve_two_step() should return chunks"
    
    # 4. Run Golden Set Evaluation
    eval_proc = subprocess.run(
        ["py", "-3.12", "scripts/eval_golden_set.py", "--domain", domain_id],
        capture_output=True,
        cwd=str(cfg.BASE_DIR)
    )
    eval_stdout = eval_proc.stdout.decode("utf-8", errors="ignore") if eval_proc.stdout else ""
    eval_stderr = eval_proc.stderr.decode("utf-8", errors="ignore") if eval_proc.stderr else ""
    
    assert eval_proc.returncode == 0, f"Golden set eval failed:\nSTDERR:\n{eval_stderr}"
    assert "Retrieval@5" in eval_stdout
