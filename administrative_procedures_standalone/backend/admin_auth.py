import asyncio
import base64
import hashlib
import hmac
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from context.database import AsyncSessionLocal
from context.models import AdminAuditLog, AdminSession, AdminUser


ADMIN_COOKIE_NAME = "hcc_admin_session"

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256

SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_KEY_BYTES = 32


@dataclass(frozen=True)
class AdminIdentity:
    id: uuid.UUID
    username: str


def admin_session_hours() -> int:
    return max(1, int(os.getenv("ADMIN_SESSION_HOURS", "8")))


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=SCRYPT_KEY_BYTES,
    )


def hash_password(password: str) -> str:
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise ValueError(
            f"Mật khẩu phải dài từ {MIN_PASSWORD_LENGTH} "
            f"đến {MAX_PASSWORD_LENGTH} ký tự."
        )

    salt = secrets.token_bytes(16)
    derived = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)

    return "$".join([
        "scrypt",
        str(SCRYPT_N),
        str(SCRYPT_R),
        str(SCRYPT_P),
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(derived).decode("ascii"),
    ])


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = stored_hash.split("$")
        if scheme != "scrypt":
            return False

        derived = _scrypt(
            password,
            base64.b64decode(salt),
            int(n),
            int(r),
            int(p),
        )
        return hmac.compare_digest(derived, base64.b64decode(expected))
    except ValueError:
        return False


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return hash_password(secrets.token_urlsafe(24))


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _find_admin(username: str) -> AdminUser | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AdminUser).where(AdminUser.username == username)
        )
        return result.scalar_one_or_none()


async def _save_session(
    admin_id: uuid.UUID,
    token_hash: str,
    expires_at: datetime,
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(AdminSession(
            token_hash=token_hash,
            admin_id=admin_id,
            expires_at=expires_at,
        ))
        await db.commit()


async def _find_session(
    token_hash: str,
) -> tuple[AdminSession, AdminUser] | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AdminSession, AdminUser)
            .join(AdminUser, AdminUser.id == AdminSession.admin_id)
            .where(AdminSession.token_hash == token_hash)
        )
        row = result.first()
        return (row[0], row[1]) if row else None


async def _delete_session(token_hash: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(AdminSession).where(AdminSession.token_hash == token_hash)
        )
        await db.commit()


async def login(
    username: str,
    password: str,
) -> tuple[AdminIdentity, str, datetime] | None:
    """
    Trả về (admin, token, hạn dùng), hoặc None nếu sai thông tin.

    Vẫn băm mật khẩu khi tài khoản không tồn tại, để thời gian phản hồi
    không tiết lộ tên đăng nhập nào có thật.
    """
    admin = await _find_admin(username)
    stored_hash = admin.password_hash if admin else _dummy_hash()
    password_ok = await asyncio.to_thread(
        verify_password,
        password,
        stored_hash,
    )

    if admin is None or not admin.is_active or not password_ok:
        return None

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(
        hours=admin_session_hours()
    )
    await _save_session(admin.id, _hash_token(token), expires_at)

    return AdminIdentity(id=admin.id, username=admin.username), token, expires_at


async def authenticate(token: str | None) -> AdminIdentity | None:
    if not token:
        return None

    token_hash = _hash_token(token)
    found = await _find_session(token_hash)
    if found is None:
        return None

    session, admin = found

    if session.expires_at <= datetime.now(timezone.utc):
        await _delete_session(token_hash)
        return None

    if not admin.is_active:
        return None

    return AdminIdentity(id=admin.id, username=admin.username)


async def logout(token: str | None) -> None:
    if token:
        await _delete_session(_hash_token(token))


async def record_audit(
    action: str,
    username: str,
    ip_address: str,
    status_code: int | None,
) -> None:
    """Lỗi ghi audit không được làm hỏng thao tác đã hoàn tất."""
    try:
        async with AsyncSessionLocal() as db:
            db.add(AdminAuditLog(
                action=action[:255],
                username=username[:64],
                ip_address=ip_address[:64],
                status_code=status_code,
            ))
            await db.commit()
    except (SQLAlchemyError, OSError) as exc:
        print(
            f"[AUDIT] không ghi được action={action!r} "
            f"user={username!r}: {exc!r}"
        )
