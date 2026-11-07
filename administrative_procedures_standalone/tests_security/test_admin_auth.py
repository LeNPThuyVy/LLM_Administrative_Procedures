"""Đăng nhập quản trị, phiên và audit log. Kho dữ liệu là bản giả trong bộ nhớ."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

import backend.admin_auth as admin_auth
import backend.api.admin as admin_api
import backend.main as main
from backend.security import require_ingestion_admin


PASSWORD = "mat-khau-du-dai-123"


@pytest.fixture(scope="module")
def stored_hash():
    return admin_auth.hash_password(PASSWORD)


@pytest.fixture
def store(monkeypatch, stored_hash):
    data = SimpleNamespace(
        admin=SimpleNamespace(
            id=uuid.uuid4(),
            username="quantri",
            password_hash=stored_hash,
            is_active=True,
        ),
        sessions={},
        audit=[],
    )

    async def find_admin(username):
        return data.admin if username == data.admin.username else None

    async def save_session(admin_id, token_hash, expires_at):
        data.sessions[token_hash] = SimpleNamespace(
            admin_id=admin_id,
            expires_at=expires_at,
        )

    async def find_session(token_hash):
        session = data.sessions.get(token_hash)
        return (session, data.admin) if session else None

    async def delete_session(token_hash):
        data.sessions.pop(token_hash, None)

    async def record_audit(action, username, ip_address, status_code):
        data.audit.append((action, username, status_code))

    monkeypatch.setattr(admin_auth, "_find_admin", find_admin)
    monkeypatch.setattr(admin_auth, "_save_session", save_session)
    monkeypatch.setattr(admin_auth, "_find_session", find_session)
    monkeypatch.setattr(admin_auth, "_delete_session", delete_session)
    monkeypatch.setattr(admin_auth, "record_audit", record_audit)
    admin_api.login_rate_limiter.reset()
    yield data
    admin_api.login_rate_limiter.reset()


def login_client(username="quantri", password=PASSWORD):
    client = TestClient(main.app)
    response = client.post(
        "/api/admin/login",
        json={"username": username, "password": password},
    )
    return client, response


# ============================================================
# Mật khẩu
# ============================================================

def test_password_hash_verifies_only_the_right_password(stored_hash):
    assert PASSWORD not in stored_hash
    assert admin_auth.verify_password(PASSWORD, stored_hash) is True
    assert admin_auth.verify_password("sai-mat-khau-123", stored_hash) is False


def test_same_password_gets_different_hashes():
    assert admin_auth.hash_password(PASSWORD) != admin_auth.hash_password(PASSWORD)


def test_short_password_is_rejected():
    with pytest.raises(ValueError):
        admin_auth.hash_password("ngan")


@pytest.mark.parametrize("stored", ["", "khong-dung-dinh-dang", "md5$1$1$1$a$b"])
def test_malformed_hash_is_not_accepted(stored):
    assert admin_auth.verify_password(PASSWORD, stored) is False


# ============================================================
# Đăng nhập
# ============================================================

def test_login_sets_protected_cookie_and_keeps_only_token_hash(store):
    _, response = login_client()

    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie

    token = response.cookies[admin_auth.ADMIN_COOKIE_NAME]
    assert token not in store.sessions
    assert admin_auth._hash_token(token) in store.sessions
    assert ("LOGIN", "quantri", 200) in store.audit


@pytest.mark.parametrize("username, password", [
    ("quantri", "sai-mat-khau-123"),
    ("khong-ton-tai", PASSWORD),
])
def test_bad_credentials_get_the_same_answer(store, username, password):
    _, response = login_client(username, password)

    assert response.status_code == 401
    assert "không đúng" in response.json()["detail"]
    assert store.sessions == {}
    assert ("LOGIN_FAILED", username, 401) in store.audit


def test_disabled_admin_cannot_login(store):
    store.admin.is_active = False

    _, response = login_client()

    assert response.status_code == 401


def test_login_attempts_are_rate_limited(store):
    statuses = [
        login_client(password="sai-mat-khau-123")[1].status_code
        for _ in range(11)
    ]

    assert statuses == [401] * 10 + [429]


def test_login_returns_503_when_database_is_down(store, monkeypatch):
    async def broken(_username):
        raise OperationalError("select", {}, OSError("db down"))

    monkeypatch.setattr(admin_auth, "_find_admin", broken)

    _, response = login_client()

    assert response.status_code == 503


# ============================================================
# Phiên
# ============================================================

def test_me_requires_login(store):
    assert TestClient(main.app).get("/api/admin/me").status_code == 401


def test_me_after_login_and_after_logout(store):
    client, _ = login_client()

    assert client.get("/api/admin/me").json() == {"username": "quantri"}

    client.post("/api/admin/logout")

    assert store.sessions == {}
    assert client.get("/api/admin/me").status_code == 401


def test_expired_session_is_rejected_and_removed(store):
    client, response = login_client()
    token_hash = admin_auth._hash_token(
        response.cookies[admin_auth.ADMIN_COOKIE_NAME]
    )
    store.sessions[token_hash].expires_at = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    )

    assert client.get("/api/admin/me").status_code == 401
    assert store.sessions == {}


def test_disabled_admin_loses_open_session(store):
    client, _ = login_client()
    store.admin.is_active = False

    assert client.get("/api/admin/me").status_code == 401


# ============================================================
# API ghi domain
# ============================================================

def test_domain_write_requires_login(store):
    response = TestClient(main.app).delete("/api/domains/khong_ton_tai")

    assert response.status_code == 401
    assert store.audit == []


def test_regular_user_cookie_is_not_admin(store):
    client = TestClient(main.app)
    client.cookies.set("user_id", str(uuid.uuid4()))
    client.cookies.set("hcc_user_id", str(uuid.uuid4()))

    assert client.delete("/api/domains/khong_ton_tai").status_code == 401


def test_admin_write_is_audited_with_username_and_status(store):
    client, _ = login_client()
    store.audit.clear()

    response = client.delete("/api/domains/khong_ton_tai")

    assert response.status_code == 404
    assert store.audit == [
        ("DELETE /api/domains/khong_ton_tai", "quantri", 404),
    ]


def test_domain_write_returns_503_when_session_check_fails(store, monkeypatch):
    async def broken(_token_hash):
        raise OperationalError("select", {}, OSError("db down"))

    client, _ = login_client()
    monkeypatch.setattr(admin_auth, "_find_session", broken)

    assert client.delete("/api/domains/khong_ton_tai").status_code == 503


def test_dependency_reuses_identity_from_middleware():
    admin = admin_auth.AdminIdentity(id=uuid.uuid4(), username="quantri")
    request = SimpleNamespace(state=SimpleNamespace(admin=admin), cookies={})

    assert asyncio.run(require_ingestion_admin(request)) is admin


def test_dependency_rejects_request_without_session():
    request = SimpleNamespace(state=SimpleNamespace(), cookies={})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_ingestion_admin(request))

    assert exc.value.status_code == 401
