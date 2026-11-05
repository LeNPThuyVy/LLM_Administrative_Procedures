import os
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from backend.security import require_ingestion_admin
import backend.upload_security as upload_security


# ============================================================
# LỖI 2 - Authentication / Authorization
# ============================================================

def test_admin_key_not_configured_returns_503(monkeypatch):
    monkeypatch.delenv("INGESTION_ADMIN_KEY", raising=False)

    with pytest.raises(HTTPException) as exc:
        require_ingestion_admin(x_admin_key=None)

    assert exc.value.status_code == 503


def test_missing_admin_key_returns_401(monkeypatch):
    monkeypatch.setenv("INGESTION_ADMIN_KEY", "server-secret")

    with pytest.raises(HTTPException) as exc:
        require_ingestion_admin(x_admin_key=None)

    assert exc.value.status_code == 401


def test_wrong_admin_key_returns_403(monkeypatch):
    monkeypatch.setenv("INGESTION_ADMIN_KEY", "server-secret")

    with pytest.raises(HTTPException) as exc:
        require_ingestion_admin(x_admin_key="wrong-secret")

    assert exc.value.status_code == 403


def test_correct_admin_key_is_accepted(monkeypatch):
    monkeypatch.setenv("INGESTION_ADMIN_KEY", "server-secret")

    result = require_ingestion_admin(
        x_admin_key="server-secret"
    )

    assert result is None


# ============================================================
# LỖI 3 - Upload security
# ============================================================

def make_upload(
    filename: str,
    content: bytes,
    content_type: str,
) -> UploadFile:
    return UploadFile(
        filename=filename,
        file=BytesIO(content),
        headers=Headers({
            "content-type": content_type,
        }),
    )


@pytest.mark.asyncio
async def test_unsupported_extension_is_rejected(tmp_path):
    upload = make_upload(
        "malware.exe",
        b"MZ fake executable",
        "application/octet-stream",
    )

    with pytest.raises(HTTPException) as exc:
        await upload_security.save_and_validate_upload(
            file=upload,
            domain_id="test_domain",
            data_dir=tmp_path,
        )

    assert exc.value.status_code == 400
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_fake_pdf_is_rejected(tmp_path):
    upload = make_upload(
        "fake.pdf",
        b"this is not a real pdf",
        "application/pdf",
    )

    with pytest.raises(HTTPException) as exc:
        await upload_security.save_and_validate_upload(
            file=upload,
            domain_id="test_domain",
            data_dir=tmp_path,
        )

    assert exc.value.status_code == 400
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_fake_xlsx_is_rejected(tmp_path):
    upload = make_upload(
        "fake.xlsx",
        b"not-a-zip-file",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    with pytest.raises(HTTPException) as exc:
        await upload_security.save_and_validate_upload(
            file=upload,
            domain_id="test_domain",
            data_dir=tmp_path,
        )

    assert exc.value.status_code == 400
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_fake_docx_is_rejected(tmp_path):
    upload = make_upload(
        "fake.docx",
        b"not-a-docx-file",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    with pytest.raises(HTTPException) as exc:
        await upload_security.save_and_validate_upload(
            file=upload,
            domain_id="test_domain",
            data_dir=tmp_path,
        )

    assert exc.value.status_code == 400
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_invalid_json_file_is_rejected(tmp_path):
    upload = make_upload(
        "bad.json",
        b'{"broken": ',
        "application/json",
    )

    with pytest.raises(HTTPException) as exc:
        await upload_security.save_and_validate_upload(
            file=upload,
            domain_id="test_domain",
            data_dir=tmp_path,
        )

    assert exc.value.status_code == 400
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_empty_file_is_rejected(tmp_path):
    upload = make_upload(
        "empty.json",
        b"",
        "application/json",
    )

    with pytest.raises(HTTPException) as exc:
        await upload_security.save_and_validate_upload(
            file=upload,
            domain_id="test_domain",
            data_dir=tmp_path,
        )

    assert exc.value.status_code == 400
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_oversized_upload_is_rejected_and_removed(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        upload_security,
        "MAX_UPLOAD_SIZE_BYTES",
        10,
    )
    monkeypatch.setattr(
        upload_security,
        "MAX_UPLOAD_SIZE_MB",
        1,
    )

    upload = make_upload(
        "large.json",
        b'{"data":"' + (b"x" * 100) + b'"}',
        "application/json",
    )

    with pytest.raises(HTTPException) as exc:
        await upload_security.save_and_validate_upload(
            file=upload,
            domain_id="test_domain",
            data_dir=tmp_path,
        )

    assert exc.value.status_code == 413
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_path_traversal_filename_is_not_used(
    tmp_path,
):
    upload = make_upload(
        "../../evil.json",
        b'{"status":"ok"}',
        "application/json",
    )

    stored = await upload_security.save_and_validate_upload(
        file=upload,
        domain_id="safe_domain",
        data_dir=tmp_path,
    )

    assert stored.path.parent.resolve() == tmp_path.resolve()
    assert ".." not in stored.path.name
    assert "evil.json" not in stored.path.name
    assert stored.path.name.startswith("safe_domain_")
    assert stored.path.suffix == ".json"
    assert stored.path.exists()


@pytest.mark.asyncio
async def test_valid_json_upload_succeeds(tmp_path):
    upload = make_upload(
        "valid.json",
        b'[{"id": 1, "title": "Test"}]',
        "application/json",
    )

    stored = await upload_security.save_and_validate_upload(
        file=upload,
        domain_id="test_domain",
        data_dir=tmp_path,
    )

    assert stored.source_type == "json"
    assert stored.size_bytes > 0
    assert stored.path.exists()
    assert stored.path.parent.resolve() == tmp_path.resolve()


def test_raw_json_over_limit_returns_413(monkeypatch):
    monkeypatch.setattr(
        upload_security,
        "MAX_UPLOAD_SIZE_BYTES",
        10,
    )
    monkeypatch.setattr(
        upload_security,
        "MAX_UPLOAD_SIZE_MB",
        1,
    )

    with pytest.raises(HTTPException) as exc:
        upload_security.validate_raw_json_size(
            '{"value":"this is larger than ten bytes"}'
        )

    assert exc.value.status_code == 413

def test_all_mutating_domain_endpoints_use_admin_dependency():
    source = Path(
        "backend/api/ingestion.py"
    ).read_text(encoding="utf-8")

    expected_functions = [
        "async def create_domain(",
        "async def ingest_domain_data(",
        "async def delete_domain(",
    ]

    for function_name in expected_functions:
        start = source.index(function_name)
        section = source[start:start + 500]

        assert (
            "Depends(require_ingestion_admin)"
            in section
        ), (
            f"{function_name} chưa được bảo vệ "
            "bởi require_ingestion_admin"
        )
