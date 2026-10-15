"""
scripts/cleanup_deprecated_tables.py — Dọn dẹp an toàn các bảng DB deprecated.

Các bảng được đánh dấu deprecated sau khi triển khai Slim Context:
- long_term_memories (Phase 1)
- conversation_summary (Phase 1)
- structured_contexts (Phase 3)

LƯU Ý AN TOÀN:
- Mặc định chỉ chạy ở chế độ DRY-RUN (chỉ kiểm tra và đếm số lượng bản ghi).
- Chỉ thực hiện DROP TABLE khi có cờ --confirm-drop và được sự đồng ý của Owner.

Cách dùng:
    py -3.12 scripts/cleanup_deprecated_tables.py --dry-run
    py -3.12 scripts/cleanup_deprecated_tables.py --confirm-drop
"""

import argparse
import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import text
from context.database import AsyncSessionLocal, engine

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


DEPRECATED_TABLES = [
    "long_term_memories",
    "conversation_summary",
    "structured_contexts",
]


async def inspect_and_cleanup(dry_run: bool = True):
    print("=" * 60)
    print("KIỂM TRA VÀ DỌN DẸP BẢNG DEPRECATED")
    print(f"Chế độ: {'DRY-RUN (Chỉ kiểm tra, KHÔNG xóa)' if dry_run else 'THỰC THI DROP TABLE'}")
    print("=" * 60)

    async with AsyncSessionLocal() as session:
        for table in DEPRECATED_TABLES:
            try:
                # Kiểm tra sự tồn tại của bảng
                check_query = text(
                    "SELECT EXISTS ("
                    "  SELECT FROM information_schema.tables "
                    "  WHERE table_name = :tname"
                    ");"
                )
                res = await session.execute(check_query, {"tname": table})
                exists = res.scalar()

                if not exists:
                    print(f"[-] Bảng '{table}': Không tồn tại trong cơ sở dữ liệu.")
                    continue

                # Đếm số bản ghi hiện có
                count_query = text(f"SELECT COUNT(*) FROM {table};")
                count_res = await session.execute(count_query)
                row_count = count_res.scalar()

                print(f"[+] Bảng '{table}': Tồn tại, hiện có {row_count} bản ghi.")

                if not dry_run:
                    print(f"    -> Đang DROP TABLE '{table}'...")
                    await session.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE;"))
                    await session.commit()
                    print(f"    -> ĐÃ XÓA THÀNH CÔNG BẢNG '{table}'.")

            except Exception as e:
                print(f"[!] Lỗi khi xử lý bảng '{table}': {e}")

    await engine.dispose()
    print("=" * 60)
    if dry_run:
        print("HOÀN THÀNH DRY-RUN. Cơ sở dữ liệu không bị thay đổi.")
        print("Để thực hiện xóa, hãy chạy với cờ: --confirm-drop")
    else:
        print("HOÀN THÀNH XÓA CÁC BẢNG DEPRECATED.")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Cleanup Deprecated Database Tables")
    parser.add_argument(
        "--confirm-drop",
        action="store_true",
        help="Thực hiện DROP TABLE thực sự (chỉ chạy khi được owner cho phép)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Chỉ kiểm tra thông tin, không xóa bảng (mặc định)",
    )
    args = parser.parse_args()

    is_dry_run = not args.confirm_drop
    asyncio.run(inspect_and_cleanup(dry_run=is_dry_run))


if __name__ == "__main__":
    main()
