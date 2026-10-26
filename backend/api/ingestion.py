import os
import json
import time
import asyncio
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
import yaml

from domains import list_domains, is_valid_domain, DOMAINS_DIR
from domains.domain_loader import load_domain_config, DomainConfig
from domains.runtime import _build_runtime
from ingestion.pipeline import IngestionPipeline
from ingestion.vector_store import QdrantVectorStore
from ingestion.version_tracker import VersionTracker

router = APIRouter(prefix="/api/domains", tags=["domains"])



class CreateDomainRequest(BaseModel):
    domain_id: str
    domain_name: str
    description: str = ""
    mode: str = "friendly"
    risk_level: str = "low"
    assistant_role: str = "chuyên gia tư vấn"
    persona: str = ""
    no_evidence_message: str = "Tôi chưa có thông tin chi tiết về nội dung này."
    out_of_scope_message: str = "Yêu cầu nằm ngoài phạm vi hỗ trợ của hệ thống."
    min_retrieval_score: float = 0.20
    supported_locations: list[str] = []
    risk_keywords: list[str] = []


@router.get("/details")
async def get_domains_details():
    """Lấy danh sách tất cả domain kèm cấu hình chi tiết."""
    domains_list = list_domains()
    details = []

    for d_id in domains_list:
        try:
            cfg = load_domain_config(d_id)
            details.append({
                "domain_id": cfg.domain_id,
                "domain_name": cfg.domain_name or cfg.domain_id,
                "description": cfg.description,
                "mode": cfg.mode,
                "risk_level": cfg.risk_level,
                "collection_name": cfg.collection_name,
                "assistant_role": cfg.assistant_role,
                "persona": cfg.persona,
                "supported_locations": cfg.supported_locations,
                "risk_keywords": cfg.risk_keywords,
                "sources": cfg.sources,
            })
        except Exception as e:
            print(f"[api/domains] Error reading domain {d_id}: {e}")

    return details


@router.post("/create")
async def create_domain(req: CreateDomainRequest):
    """Tạo một domain mới và sinh tự động config.yaml + schema.py."""
    import re
    d_id = req.domain_id.strip().lower()
    if not re.match(r"^[a-z0-9_-]+$", d_id):
        raise HTTPException(
            status_code=400,
            detail="Domain ID chỉ được chứa chữ cái thường không dấu, số, dấu gạch dưới hoặc gạch nối.",
        )

    target_dir = DOMAINS_DIR / d_id
    if target_dir.exists() and (target_dir / "config.yaml").exists():
        raise HTTPException(
            status_code=400,
            detail=f"Domain '{d_id}' đã tồn tại.",
        )

    target_dir.mkdir(parents=True, exist_ok=True)

    # 1. Sinh config.yaml
    config_dict = {
        "domain_id": d_id,
        "domain_name": req.domain_name.strip(),
        "description": req.description.strip(),
        "mode": req.mode.strip().lower() if req.mode in ("strict", "friendly") else "friendly",
        "risk_level": req.risk_level.strip().lower() if req.risk_level in ("low", "high") else "low",
        "collection_name": d_id,
        "assistant_role": req.assistant_role.strip(),
        "persona": req.persona.strip() or f"Bạn là một {req.assistant_role.strip()} chuyên nghiệp và thân thiện.",
        "min_retrieval_score": req.min_retrieval_score,
        "no_evidence_message": req.no_evidence_message.strip(),
        "out_of_scope_message": req.out_of_scope_message.strip(),
        "allowed_tools": [],
        "entity_keywords": [req.domain_name.strip().lower()],
        "supported_locations": req.supported_locations or ["Toàn quốc"],
        "risk_keywords": req.risk_keywords or [],
        "chunk_fields": ["general"],
        "chunk_field_specs": {
            "general": {
                "suffix": "_general",
                "label": "Thông tin chi tiết",
                "attr": "content",
            }
        },
        "sources": [],
    }

    config_yaml_path = target_dir / "config.yaml"
    with open(config_yaml_path, "w", encoding="utf-8") as fp:
        yaml.dump(config_dict, fp, allow_unicode=True, sort_keys=False)

    # 2. Sinh schema.py chuẩn
    schema_code = f'''from typing import Optional
from pydantic import BaseModel, ConfigDict


class {d_id.title().replace("_", "").replace("-", "")}Document(BaseModel):
    """Schema tự động cho domain {d_id}."""
    model_config = ConfigDict(extra="allow")

    document_id: str
    title: str
    category: str = "chung"
    content: Optional[str] = None
    source_url: Optional[str] = None
    aliases: list[str] = []
'''
    schema_py_path = target_dir / "schema.py"
    with open(schema_py_path, "w", encoding="utf-8") as fp:
        fp.write(schema_code)

    # Reset cache runtime
    _build_runtime.cache_clear()

    return {
        "status": "ok",
        "message": f"Đã khởi tạo thành công domain: {d_id}",
        "domain": config_dict,
    }


@router.post("/{domain_id}/ingest")
async def ingest_domain_data(
    domain_id: str,
    file: Optional[UploadFile] = File(None),
    raw_json: Optional[str] = Form(None),
    force_reindex: bool = Form(False),
):
    """
    Nạp dữ liệu mới vào Domain và đánh chỉ mục (Embed + Upsert Qdrant).
    Hỗ trợ upload file (.json, .csv, .xlsx, .pdf, .docx) hoặc dán JSON trực tiếp.
    """
    if not is_valid_domain(domain_id):
        raise HTTPException(
            status_code=404,
            detail=f"Domain '{domain_id}' không tồn tại.",
        )

    data_dir = Path("data") / "sources"
    data_dir.mkdir(parents=True, exist_ok=True)
    source_type = "json"
    saved_file_path = None

    if file and file.filename:
        safe_name = f"{domain_id}_{file.filename}"
        saved_file_path = data_dir / safe_name
        ext = saved_file_path.suffix.lower()

        ext_to_type = {
            ".json": "json",
            ".csv": "csv",
            ".xlsx": "xlsx",
            ".pdf": "pdf",
            ".docx": "docx",
        }
        if ext not in ext_to_type:
            raise HTTPException(
                status_code=400,
                detail=f"Định dạng tệp '{ext}' không được hỗ trợ. Vui lòng chọn .json, .csv, .xlsx, .pdf hoặc .docx.",
            )
        source_type = ext_to_type[ext]

        content_bytes = await file.read()
        with open(saved_file_path, "wb") as f:
            f.write(content_bytes)

    elif raw_json and raw_json.strip():
        # Dán JSON trực tiếp
        try:
            parsed = json.loads(raw_json)
            if not isinstance(parsed, list):
                if isinstance(parsed, dict):
                    parsed = [parsed]
                else:
                    raise ValueError("JSON phải là một mảng (list) hoặc đối tượng (dict).")
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Dữ liệu JSON không hợp lệ: {e}",
            )

        saved_file_path = data_dir / f"{domain_id}_raw_input.json"
        with open(saved_file_path, "w", encoding="utf-8") as f:
            json.dump(parsed, f, ensure_ascii=False, indent=2)
        source_type = "json"

    else:
        # Nếu không tải file lên và không dán JSON, kiểm tra xem sources trong config đã có sẵn chưa
        cfg = load_domain_config(domain_id)
        if not cfg.sources:
            raise HTTPException(
                status_code=400,
                detail="Vui lòng tải lên một tệp dữ liệu hoặc dán nội dung JSON để nạp vào domain.",
            )

    # Cập nhật source vào config.yaml nếu có file mới được nạp
    if saved_file_path:
        config_path = DOMAINS_DIR / domain_id / "config.yaml"
        current_cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        new_source = {
            "type": source_type,
            "path": str(saved_file_path).replace("\\", "/"),
        }
        existing_sources = current_cfg.get("sources", [])
        # Xóa nguồn cũ trùng tên file nếu có (ví dụ từng lưu ở data/ thay vì data/sources/)
        new_name = Path(new_source["path"]).name
        cleaned_sources = [s for s in existing_sources if Path(s.get("path", "")).name != new_name]
        cleaned_sources.append(new_source)
        current_cfg["sources"] = cleaned_sources
        if source_type in ("csv", "xlsx"):
            current_cfg["search_backend"] = "elasticsearch"
        elif source_type in ("pdf", "docx"):
            current_cfg["search_backend"] = "qdrant"

        with open(config_path, "w", encoding="utf-8") as fp:
            yaml.dump(current_cfg, fp, allow_unicode=True, sort_keys=False)

    # Chạy Ingestion Pipeline trong background thread (asyncio.to_thread)
    t_start = time.perf_counter()
    try:
        def _run_pipeline():
            pipeline = IngestionPipeline(domain_id)
            return pipeline.run(force_reindex=force_reindex)

        result = await asyncio.to_thread(_run_pipeline)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Lỗi trong quá trình Ingestion: {str(exc)}",
        )

    elapsed = round(time.perf_counter() - t_start, 2)

    # Reset runtime caches để chat nhận ngay dữ liệu mới
    _build_runtime.cache_clear()
    try:
        from rag.retrieval import _ALIAS_CATALOG
        _ALIAS_CATALOG.pop(domain_id, None)
    except Exception:
        pass
    try:
        from rag.pipeline import _PIPELINE_ANSWER_CACHE
        _PIPELINE_ANSWER_CACHE.clear()
    except Exception:
        pass

    return {
        "status": "ok",
        "domain_id": result.domain_id,
        "total_loaded": result.total_loaded,
        "total_valid": result.total_valid,
        "total_after_dedup": result.total_after_dedup,
        "total_chunks": result.total_chunks,
        "removed_duplicates": len(result.removed_duplicates),
        "validation_errors": len(result.validation_errors),
        "elapsed_seconds": elapsed,
        "message": f"Nạp thành công {result.total_chunks} chunks cho domain '{domain_id}' trong {elapsed}s.",
    }


@router.delete("/{domain_id}")
@router.delete("/{domain_id}/")
async def delete_domain(domain_id: str):
    """
    Xóa hoàn toàn một domain khỏi hệ thống:
    1. Xóa collection trên Qdrant
    2. Xóa các file dữ liệu nguồn thuộc riêng domain trong data/
    3. Xóa lịch sử nạp trong VersionTracker (data/.ingestion_versions.json)
    4. Xóa thư mục cấu hình domains/<domain_id>
    5. Xóa sạch cache runtime, alias catalog và answer cache
    """
    d_id = (domain_id or "").strip()
    if not d_id or not is_valid_domain(d_id):
        raise HTTPException(
            status_code=404,
            detail=f"Domain '{d_id}' không tồn tại.",
        )

    current_domains = list_domains()
    if len(current_domains) <= 1:
        raise HTTPException(
            status_code=400,
            detail="Không thể xóa domain duy nhất còn lại trên hệ thống.",
        )

    cfg = load_domain_config(d_id)

    # Tập hợp các file nguồn đang được các domain khác sử dụng để bảo vệ không xóa nhầm
    other_used_paths = set()
    for other_id in current_domains:
        if other_id == d_id:
            continue
        try:
            other_cfg = load_domain_config(other_id)
            for src in other_cfg.sources:
                if src.get("path"):
                    other_used_paths.add(Path(src["path"]).resolve())
        except Exception:
            pass

    # 1. Xóa collection trên Qdrant
    qdrant_deleted = False
    try:
        def _del_qdrant():
            store = QdrantVectorStore(cfg)
            store.delete_collection()
            try:
                from ingestion.elastic_store import ElasticTabularStore
                ElasticTabularStore(cfg).delete_collection()
            except Exception as e_es:
                print(f"[api/domains] Note deleting ES index: {e_es}")
        await asyncio.to_thread(_del_qdrant)
        qdrant_deleted = True
    except Exception as e:
        print(f"[api/domains] Warning deleting Qdrant collection for '{d_id}': {e}")

    # 2. Xóa file dữ liệu trong data/ và data/sources/ thuộc riêng domain này
    deleted_files = []
    data_dir = Path("data")
    sources_dir = Path("data") / "sources"
    candidate_paths = set()
    for src in cfg.sources:
        if src.get("path"):
            candidate_paths.add(Path(src["path"]))
    if data_dir.exists():
        for p in data_dir.glob(f"{d_id}*"):
            candidate_paths.add(p)
    if sources_dir.exists():
        for p in sources_dir.glob(f"{d_id}*"):
            candidate_paths.add(p)

    for file_path in candidate_paths:
        try:
            resolved = file_path.resolve()
            if file_path.is_file() and resolved not in other_used_paths:
                file_path.unlink()
                deleted_files.append(str(file_path))
        except Exception as e:
            print(f"[api/domains] Warning deleting file {file_path}: {e}")

    # 3. Xóa lịch sử VersionTracker
    try:
        VersionTracker().remove_domain(d_id)
    except Exception as e:
        print(f"[api/domains] Warning removing version tracker for '{d_id}': {e}")

    # 4. Xóa thư mục cấu hình domains/<domain_id>
    target_dir = DOMAINS_DIR / d_id
    if target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)

    # 5. Xóa sạch các bộ nhớ đệm
    _build_runtime.cache_clear()
    try:
        from rag.retrieval import _ALIAS_CATALOG
        _ALIAS_CATALOG.pop(d_id, None)
    except Exception:
        pass
    try:
        from rag.pipeline import _PIPELINE_ANSWER_CACHE
        _PIPELINE_ANSWER_CACHE.clear()
    except Exception:
        pass

    remaining = list_domains()
    return {
        "status": "ok",
        "domain_id": d_id,
        "qdrant_deleted": qdrant_deleted,
        "deleted_files": deleted_files,
        "remaining_domains": remaining,
        "message": f"Đã xóa hoàn toàn domain '{d_id}' và dữ liệu liên quan.",
    }

