import json
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT_DIR / "data" / "procedures.json"


def get_procedure_detail_data(document_id: str) -> dict[str, Any]:
    """
    Đọc chi tiết thủ tục từ data/procedures.json.

    Tool read-only:
    - không sửa file
    - không ghi database
    - không thay đổi dữ liệu
    """
    if not document_id:
        return {
            "success": False,
            "error": "document_id is required",
        }

    if not DATA_PATH.exists():
        return {
            "success": False,
            "error": f"Data file not found: {DATA_PATH}",
        }

    try:
        records = json.loads(
            DATA_PATH.read_text(encoding="utf-8")
        )
    except Exception as exc:
        return {
            "success": False,
            "error": f"Failed to read procedures data: {exc}",
        }

    for record in records:
        if record.get("document_id") == document_id:
            return {
                "success": True,
                "document": record,
            }

    return {
        "success": False,
        "error": f"Procedure not found: {document_id}",
    }