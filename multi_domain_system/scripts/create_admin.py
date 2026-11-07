"""
Tạo hoặc đặt lại tài khoản quản trị.

    python scripts/create_admin.py --username ten_dang_nhap
    python scripts/create_admin.py --username ten_dang_nhap --disable

Mật khẩu chỉ nhập qua terminal, không truyền bằng tham số dòng lệnh để
tránh lưu vào lịch sử shell. Đổi mật khẩu hoặc khóa tài khoản sẽ hủy mọi
phiên đang mở của tài khoản đó.
"""
import argparse
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select

from backend.admin_auth import MIN_PASSWORD_LENGTH, hash_password
from context.database import AsyncSessionLocal, engine
from context.init_db import init_db
from context.models import AdminSession, AdminUser


def read_password() -> str:
    password = getpass.getpass(
        f"Mật khẩu mới (tối thiểu {MIN_PASSWORD_LENGTH} ký tự): "
    )
    if password != getpass.getpass("Nhập lại mật khẩu: "):
        raise SystemExit("Hai lần nhập mật khẩu không khớp.")
    return password


async def save_admin(username: str, password_hash: str | None) -> str:
    """password_hash là None nghĩa là khóa tài khoản."""
    await init_db()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AdminUser).where(AdminUser.username == username)
        )
        admin = result.scalar_one_or_none()

        if admin is None:
            if password_hash is None:
                raise SystemExit(f"Không tìm thấy tài khoản '{username}'.")
            db.add(AdminUser(username=username, password_hash=password_hash))
            outcome = "đã tạo"
        else:
            await db.execute(
                delete(AdminSession).where(AdminSession.admin_id == admin.id)
            )
            if password_hash is None:
                admin.is_active = False
                outcome = "đã khóa"
            else:
                admin.password_hash = password_hash
                admin.is_active = True
                outcome = "đã đặt lại mật khẩu"

        await db.commit()

    await engine.dispose()
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--username", required=True)
    parser.add_argument("--disable", action="store_true")
    args = parser.parse_args()

    username = args.username.strip()
    if not username or len(username) > 64:
        raise SystemExit("Tên đăng nhập phải dài từ 1 đến 64 ký tự.")

    password_hash = None
    if not args.disable:
        try:
            password_hash = hash_password(read_password())
        except ValueError as exc:
            raise SystemExit(str(exc))

    outcome = asyncio.run(save_admin(username, password_hash))
    print(f"Tài khoản '{username}': {outcome}.")


if __name__ == "__main__":
    main()
