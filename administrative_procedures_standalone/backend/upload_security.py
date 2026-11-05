import json
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status


MAX_UPLOAD_SIZE_MB = max(
    1,
    int(os.getenv("MAX_UPLOAD_SIZE_MB", "20")),
)
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024

UPLOAD_CHUNK_SIZE = 1024 * 1024

EXTENSION_TO_TYPE = {
    ".json": "json",
    ".csv": "csv",
    ".xlsx": "xlsx",
    ".pdf": "pdf",
    ".docx": "docx",
}

ALLOWED_CONTENT_TYPES = {
    ".json": {
        "application/json",
        "text/json",
        "text/plain",
        "application/octet-stream",
    },
    ".csv": {
        "text/csv",
        "application/csv",
        "text/plain",
        "application/vnd.ms-excel",
        "application/octet-stream",
    },
    ".xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",
        "application/octet-stream",
    },
    ".pdf": {
        "application/pdf",
        "application/octet-stream",
    },
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
        "application/octet-stream",
    },
}


@dataclass(frozen=True)
class StoredUpload:
    path: Path
    source_type: str
    original_filename: str
    size_bytes: int


def validate_raw_json_size(raw_json: str) -> None:
    size = len(raw_json.encode("utf-8"))

    if size > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                f"Dữ liệu vượt quá giới hạn "
                f"{MAX_UPLOAD_SIZE_MB} MB."
            ),
        )


def _get_extension(file: UploadFile) -> str:
    original_name = file.filename or ""
    extension = Path(original_name).suffix.lower()

    if extension not in EXTENSION_TO_TYPE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Định dạng tệp '{extension or '(không có)'}' "
                "không được hỗ trợ. Chỉ chấp nhận "
                ".json, .csv, .xlsx, .pdf hoặc .docx."
            ),
        )

    return extension


def _validate_declared_content_type(
    file: UploadFile,
    extension: str,
) -> None:
    content_type = (file.content_type or "").lower().strip()

    if not content_type:
        return

    allowed = ALLOWED_CONTENT_TYPES[extension]

    if content_type not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Content-Type '{content_type}' không phù hợp "
                f"với định dạng '{extension}'."
            ),
        )


def _validate_json(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8-sig")
        json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "Nội dung tệp không phải JSON UTF-8 hợp lệ."
        ) from exc


def _validate_csv(path: Path) -> None:
    sample = path.read_bytes()[:65536]

    if b"\x00" in sample:
        raise ValueError(
            "Tệp CSV chứa dữ liệu nhị phân không hợp lệ."
        )

    try:
        sample.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(
            "Tệp CSV phải là văn bản UTF-8 hợp lệ."
        ) from exc


def _validate_pdf(path: Path) -> None:
    with path.open("rb") as fp:
        signature = fp.read(5)

    if signature != b"%PDF-":
        raise ValueError(
            "Nội dung tệp không có chữ ký PDF hợp lệ."
        )


def _validate_xlsx(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        raise ValueError(
            "Nội dung tệp không phải XLSX hợp lệ."
        )

    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())

    if (
        "[Content_Types].xml" not in names
        or not any(name.startswith("xl/") for name in names)
    ):
        raise ValueError(
            "Cấu trúc tệp XLSX không hợp lệ."
        )


def _validate_docx(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        raise ValueError(
            "Nội dung tệp không phải DOCX hợp lệ."
        )

    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())

    if (
        "[Content_Types].xml" not in names
        or "word/document.xml" not in names
    ):
        raise ValueError(
            "Cấu trúc tệp DOCX không hợp lệ."
        )


def _validate_file_content(
    path: Path,
    extension: str,
) -> None:
    validators = {
        ".json": _validate_json,
        ".csv": _validate_csv,
        ".xlsx": _validate_xlsx,
        ".pdf": _validate_pdf,
        ".docx": _validate_docx,
    }

    try:
        validators[extension](path)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


async def save_and_validate_upload(
    file: UploadFile,
    domain_id: str,
    data_dir: Path,
) -> StoredUpload:
    """
    Lưu upload theo từng chunk thay vì đọc toàn bộ vào RAM.

    Tên tệp lưu trên server do server tự sinh, không sử dụng trực tiếp
    file.filename nên tránh path traversal và tên tệp nguy hiểm.
    """
    extension = _get_extension(file)
    _validate_declared_content_type(file, extension)

    data_dir.mkdir(parents=True, exist_ok=True)

    original_filename = file.filename or f"upload{extension}"

    server_filename = (
        f"{domain_id}_{uuid4().hex}{extension}"
    )

    saved_path = data_dir / server_filename

    total_size = 0

    try:
        with saved_path.open("wb") as output:
            while True:
                chunk = await file.read(UPLOAD_CHUNK_SIZE)

                if not chunk:
                    break

                total_size += len(chunk)

                if total_size > MAX_UPLOAD_SIZE_BYTES:
                    raise HTTPException(
                        status_code=(
                            status.HTTP_413_CONTENT_TOO_LARGE
                        ),
                        detail=(
                            f"Tệp vượt quá giới hạn "
                            f"{MAX_UPLOAD_SIZE_MB} MB."
                        ),
                    )

                output.write(chunk)

        if total_size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không chấp nhận tệp rỗng.",
            )

        _validate_file_content(
            saved_path,
            extension,
        )

        return StoredUpload(
            path=saved_path,
            source_type=EXTENSION_TO_TYPE[extension],
            original_filename=original_filename,
            size_bytes=total_size,
        )

    except HTTPException:
        saved_path.unlink(missing_ok=True)
        raise

    except Exception as exc:
        saved_path.unlink(missing_ok=True)

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tệp tải lên không hợp lệ: {exc}",
        ) from exc

    finally:
        await file.close()
