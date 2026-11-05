import uuid

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.api.sessions import (
    USER_COOKIE_NAME,
    _require_authenticated_user_id,
)


class FakeScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDB:
    def __init__(self, existing_user_id=None):
        self.existing_user_id = existing_user_id

    async def execute(self, _statement):
        return FakeScalarResult(
            self.existing_user_id
        )


def make_request(cookies=None):
    cookies = cookies or {}

    cookie_header = "; ".join(
        f"{key}={value}"
        for key, value in cookies.items()
    )

    headers = []

    if cookie_header:
        headers.append(
            (
                b"cookie",
                cookie_header.encode("latin-1"),
            )
        )

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
        "query_string": b"",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
        "scheme": "http",
    }

    return Request(scope)


@pytest.mark.asyncio
async def test_missing_user_cookie_is_rejected():
    request = make_request()
    db = FakeDB()

    with pytest.raises(HTTPException) as exc:
        await _require_authenticated_user_id(
            request,
            db,
        )

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_invalid_user_cookie_is_rejected():
    request = make_request({
        USER_COOKIE_NAME: "not-a-valid-uuid"
    })

    db = FakeDB()

    with pytest.raises(HTTPException) as exc:
        await _require_authenticated_user_id(
            request,
            db,
        )

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_unknown_user_cookie_is_rejected():
    user_id = uuid.uuid4()

    request = make_request({
        USER_COOKIE_NAME: str(user_id)
    })

    db = FakeDB(existing_user_id=None)

    with pytest.raises(HTTPException) as exc:
        await _require_authenticated_user_id(
            request,
            db,
        )

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_existing_user_cookie_is_accepted():
    user_id = uuid.uuid4()

    request = make_request({
        USER_COOKIE_NAME: str(user_id)
    })

    db = FakeDB(
        existing_user_id=user_id
    )

    resolved = await _require_authenticated_user_id(
        request,
        db,
    )

    assert resolved == user_id


def test_sensitive_session_endpoints_use_strict_identity():
    source = open(
        "backend/api/sessions.py",
        encoding="utf-8",
    ).read()

    endpoint_names = [
        "async def switch_session(",
        "async def delete_session(",
        "async def get_session_messages(",
    ]

    for endpoint in endpoint_names:
        start = source.index(endpoint)
        section = source[start:start + 1800]

        assert (
            "_require_authenticated_user_id("
            in section
        ), (
            f"{endpoint} chưa sử dụng strict identity"
        )


def test_messages_no_longer_trusts_session_cookie_alone():
    source = open(
        "backend/api/sessions.py",
        encoding="utf-8",
    ).read()

    start = source.index(
        "async def get_session_messages("
    )

    section = source[start:start + 2200]

    forbidden_pattern = (
        "cookie_session_id == str(session_id)"
    )

    assert forbidden_pattern not in section


def test_switch_has_unconditional_owner_check():
    source = open(
        "backend/api/sessions.py",
        encoding="utf-8",
    ).read()

    start = source.index(
        "async def switch_session("
    )

    section = source[start:start + 1600]

    assert "session.user_id != user_id" in section
    assert (
        "if user_id and session.user_id"
        not in section
    )


def test_delete_has_unconditional_owner_check():
    source = open(
        "backend/api/sessions.py",
        encoding="utf-8",
    ).read()

    start = source.index(
        "async def delete_session("
    )

    section = source[start:start + 1800]

    assert "session.user_id != user_id" in section
    assert (
        "if user_id and session.user_id"
        not in section
    )
