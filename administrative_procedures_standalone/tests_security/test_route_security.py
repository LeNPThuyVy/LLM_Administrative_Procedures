"""Test mức route trên app thật: DB là bản giả, pipeline ingestion luôn bị thay thế.

Không kết nối Postgres, Qdrant hay llama-server.
"""
import asyncio
import importlib.util
import io
import json
import sys
import uuid
import zipfile
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import backend.api.chat as chat_api
import backend.api.ingestion as ingestion_api
import backend.api.sessions as sessions_api
import backend.main as main
import backend.upload_security as upload_security
from backend.rate_limit import ChatRateLimiter, chat_rate_limiter
from backend.schemas.chat import MAX_QUERY_CHARS
import my_config
from context.models import ChatSession, User

ADMIN_KEY = "test-admin-key-for-route-tests"
ALICE = uuid.uuid4()
BOB = uuid.uuid4()
ANONYMOUS = uuid.uuid5(uuid.NAMESPACE_DNS, "anonymous.local")
ALICE_SESSION = uuid.uuid4()
BOB_SESSION = uuid.uuid4()
ANON_SESSION = uuid.uuid4()


class FakeResult:
    def __init__(self, value=None, rows=None):
        self.value = value
        self.rows = rows or []

    def scalar_one_or_none(self):
        return self.value

    def scalar(self):
        return self.value

    def scalars(self):
        return SimpleNamespace(all=lambda: self.rows)


class FakeDatabase:
    """Chỉ trả lời các câu select theo ChatSession/User mà API dùng."""

    def __init__(self):
        self.sessions = {
            ALICE_SESSION: ALICE,
            BOB_SESSION: BOB,
            ANON_SESSION: ANONYMOUS,
        }
        self.users = {ALICE, BOB, ANONYMOUS}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    def _session(self, session_id):
        return SimpleNamespace(
            id=session_id,
            user_id=self.sessions[session_id],
            created_at=None,
        )

    async def execute(self, statement):
        column = statement.column_descriptions[0]
        entity = column["entity"]
        where = statement.whereclause

        if entity is ChatSession:
            field, value = where.left.key, where.right.value

            if field == "user_id":
                return FakeResult(rows=[
                    self._session(session_id)
                    for session_id, owner in self.sessions.items()
                    if owner == value
                ])

            if value not in self.sessions:
                return FakeResult()

            if column["name"] == "user_id":
                return FakeResult(self.sessions[value])

            return FakeResult(self._session(value))

        if entity is User:
            value = where.right.value
            if value not in self.users:
                return FakeResult()

            if column["name"] == "id":
                return FakeResult(value)

            return FakeResult(SimpleNamespace(id=value))

        return FakeResult()

    def add(self, obj):
        if isinstance(obj, ChatSession):
            self.sessions[obj.id] = obj.user_id
        elif isinstance(obj, User):
            self.users.add(obj.id)

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def delete(self, _obj):
        return None


@pytest.fixture
def database(monkeypatch):
    fake = FakeDatabase()

    for module in list(sys.modules.values()):
        name = getattr(module, "__name__", "") or ""
        if name.startswith("backend.") and hasattr(module, "AsyncSessionLocal"):
            monkeypatch.setattr(module, "AsyncSessionLocal", lambda: fake)

    return fake


@pytest.fixture
def chat_calls(monkeypatch):
    calls = []

    async def fake_get_context(session_id, query):
        calls.append(session_id)
        return {}

    async def fake_stream(**_kwargs):
        yield ("final", {
            "answer": "ok",
            "evidence_list": [],
            "needs_clarification": False,
            "clarification_question": None,
            "mode": "strict",
        })

    async def fake_update_memory(**_kwargs):
        return None

    monkeypatch.setattr(chat_api, "get_context", fake_get_context)
    monkeypatch.setattr(chat_api, "generate_answer_stream", fake_stream)
    monkeypatch.setattr(chat_api, "update_memory", fake_update_memory, raising=False)
    monkeypatch.setattr(
        chat_api, "schedule_memory_update", lambda **_kwargs: None, raising=False
    )
    return calls


@pytest.fixture
def admin_env(monkeypatch):
    """Không test nào được chạy pipeline thật, kể cả khi guard thất bại."""
    monkeypatch.setenv("INGESTION_ADMIN_KEY", ADMIN_KEY)

    class ForbiddenPipeline:
        def __init__(self, *_args):
            raise RuntimeError("pipeline giả: không được chạy thật trong test")

    monkeypatch.setattr(ingestion_api, "IngestionPipeline", ForbiddenPipeline)


def make_client(user_id=None, session_id=None):
    client = TestClient(main.app)
    if user_id:
        client.cookies.set(sessions_api.USER_COOKIE_NAME, str(user_id))
    if session_id:
        client.cookies.set(sessions_api.COOKIE_NAME, str(session_id))
    return client


def chat_body(session_id):
    return {"session_id": str(session_id), "query": "xin chao"}


# ============================================================
# Lỗi 1: /api/chat, /ws/chat, danh sách phiên, bootstrap
# ============================================================

def test_chat_rejects_session_of_another_user(database, chat_calls):
    response = make_client(user_id=ALICE).post(
        "/api/chat", json=chat_body(BOB_SESSION)
    )

    assert response.status_code == 403
    assert chat_calls == []


def test_chat_rejects_owned_session_without_user_cookie(database, chat_calls):
    response = make_client().post("/api/chat", json=chat_body(BOB_SESSION))

    assert response.status_code == 403
    assert chat_calls == []


def test_chat_allows_owner(database, chat_calls):
    response = make_client(user_id=ALICE).post(
        "/api/chat", json=chat_body(ALICE_SESSION)
    )

    assert response.status_code == 200
    assert chat_calls == [str(ALICE_SESSION)]


def test_chat_allows_new_session_without_cookie(database, chat_calls):
    """Benchmark gọi /api/chat bằng uuid4 mới và không có cookie."""
    new_session = uuid.uuid4()

    response = make_client().post("/api/chat", json=chat_body(new_session))

    assert response.status_code == 200
    assert chat_calls == [str(new_session)]


def test_chat_allows_anonymous_session(database, chat_calls):
    response = make_client().post("/api/chat", json=chat_body(ANON_SESSION))

    assert response.status_code == 200


def test_chat_rejects_invalid_user_cookie_on_owned_session(database, chat_calls):
    client = make_client(user_id="not-a-uuid")

    response = client.post("/api/chat", json=chat_body(BOB_SESSION))

    assert response.status_code == 403


def test_websocket_rejects_session_of_another_user(database):
    client = make_client(user_id=ALICE)

    with client.websocket_connect(f"/ws/chat?session_id={BOB_SESSION}") as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()

    assert exc.value.code == 4403


def test_websocket_allows_owner(database):
    client = make_client(user_id=ALICE)

    with client.websocket_connect(f"/ws/chat?session_id={ALICE_SESSION}") as ws:
        assert ws.receive_json()["type"] == "connected"


def test_session_cookie_alone_does_not_list_sessions_of_owner(database):
    response = make_client(session_id=BOB_SESSION).get("/api/sessions")

    assert response.status_code == 200
    assert response.json() == []


def test_user_cookie_lists_own_sessions(database):
    response = make_client(user_id=ALICE).get("/api/sessions")

    assert [item["id"] for item in response.json()] == [str(ALICE_SESSION)]


def test_bootstrap_replaces_session_of_another_user(database):
    response = make_client(user_id=ALICE, session_id=BOB_SESSION).get(
        "/api/session/bootstrap"
    )
    new_session = uuid.UUID(response.json()["session_id"])

    assert new_session != BOB_SESSION
    assert database.sessions[new_session] == ALICE
    assert str(new_session) in response.headers["set-cookie"]


def test_bootstrap_keeps_own_session(database):
    response = make_client(user_id=ALICE, session_id=ALICE_SESSION).get(
        "/api/session/bootstrap"
    )

    assert response.json()["session_id"] == str(ALICE_SESSION)


def test_bootstrap_recovers_when_user_cookie_is_new(database):
    """Cookie user hết hạn trước cookie session: người dùng không bị khóa."""
    response = make_client(session_id=ALICE_SESSION).get("/api/session/bootstrap")
    payload = response.json()
    new_session = uuid.UUID(payload["session_id"])

    assert new_session != ALICE_SESSION
    assert str(database.sessions[new_session]) == payload["user_id"]
    assert uuid.UUID(payload["user_id"]) in database.users


# ============================================================
# Lỗi 2: API quản trị
# ============================================================

def test_domain_details_hides_internal_fields():
    response = make_client().get("/api/domains/details")

    assert response.status_code == 200
    assert response.json()

    for item in response.json():
        assert {"domain_id", "domain_name", "description", "mode"} <= set(item)
        assert not {
            "sources",
            "persona",
            "collection_name",
            "assistant_role",
            "risk_keywords",
        } & set(item)


def test_non_ascii_admin_key_is_forbidden_not_server_error(admin_env):
    client = TestClient(main.app, raise_server_exceptions=False)

    response = client.delete(
        "/api/domains/khong_ton_tai",
        headers={"X-Admin-Key": "caf\xe9".encode("latin-1")},
    )

    assert response.status_code == 403


def test_placeholder_admin_key_is_treated_as_unconfigured(monkeypatch):
    placeholder = "change-this-to-a-long-random-secret"
    monkeypatch.setenv("INGESTION_ADMIN_KEY", placeholder)

    response = make_client().delete(
        "/api/domains/khong_ton_tai",
        headers={"X-Admin-Key": placeholder},
    )

    assert response.status_code == 503


# ============================================================
# Lỗi 3: chặn trước khi đọc body
# ============================================================

class AsgiCall:
    """Gọi app ở mức ASGI để đếm chính xác số lần body được đọc."""

    def __init__(self, headers, chunks):
        self.headers = headers
        self.chunks = list(chunks)
        self.body_reads = 0
        self.status = None

    async def receive(self):
        self.body_reads += 1
        if self.chunks:
            return {
                "type": "http.request",
                "body": self.chunks.pop(0),
                "more_body": bool(self.chunks),
            }
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(self, message):
        if message["type"] == "http.response.start":
            self.status = message["status"]

    def run(self, path="/api/domains/administrative_procedures/ingest"):
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "root_path": "",
            "query_string": b"",
            "headers": self.headers,
            "client": ("testclient", 1),
            "server": ("testserver", 80),
        }
        asyncio.run(main.app(scope, self.receive, self.send))
        return self


MULTIPART = (b"content-type", b"multipart/form-data; boundary=x")


def test_unauthenticated_upload_is_rejected_before_reading_body(admin_env):
    call = AsgiCall([MULTIPART], [b"--x\r\n" + b"a" * 1024]).run()

    assert call.status == 401
    assert call.body_reads == 0


def test_wrong_key_upload_is_rejected_before_reading_body(admin_env):
    call = AsgiCall(
        [MULTIPART, (b"x-admin-key", b"wrong")],
        [b"--x\r\n" + b"a" * 1024],
    ).run()

    assert call.status == 403
    assert call.body_reads == 0


def test_declared_oversize_body_is_rejected_before_reading_body(admin_env):
    too_large = upload_security.MAX_UPLOAD_SIZE_BYTES + 100 * 1024 * 1024

    call = AsgiCall(
        [
            MULTIPART,
            (b"x-admin-key", ADMIN_KEY.encode()),
            (b"content-length", str(too_large).encode()),
        ],
        [b""],
    ).run()

    assert call.status == 413
    assert call.body_reads == 0


def test_chunked_body_over_limit_is_stopped(admin_env, monkeypatch):
    monkeypatch.setattr(upload_security, "MAX_UPLOAD_SIZE_BYTES", 10)
    megabyte = b"a" * (1024 * 1024)

    file_part = (
        b"--x\r\n"
        b'Content-Disposition: form-data; name="file"; filename="a.json"\r\n'
        b"Content-Type: application/json\r\n\r\n"
    )

    call = AsgiCall(
        [MULTIPART, (b"x-admin-key", ADMIN_KEY.encode())],
        [file_part, megabyte, megabyte, megabyte, megabyte],
    ).run()

    assert call.status == 413
    assert call.chunks, "phải dừng trước khi đọc hết body"


def test_invalid_content_length_is_rejected(admin_env):
    call = AsgiCall(
        [
            MULTIPART,
            (b"x-admin-key", ADMIN_KEY.encode()),
            (b"content-length", b"abc"),
        ],
        [b""],
    ).run()

    assert call.status == 400
    assert call.body_reads == 0


def test_chat_is_not_affected_by_domain_write_guard(database, chat_calls, admin_env):
    response = make_client(user_id=ALICE).post(
        "/api/chat", json=chat_body(ALICE_SESSION)
    )

    assert response.status_code == 200


# ============================================================
# Lỗi 3: nội dung tệp
# ============================================================

def make_zip(path, members):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return path


DOCX_MEMBERS = {"[Content_Types].xml": "x", "word/document.xml": "<w/>"}
XLSX_MEMBERS = {"[Content_Types].xml": "x", "xl/workbook.xml": "<x/>"}


@pytest.mark.parametrize(
    "validator, members, big_member",
    [
        ("_validate_docx", DOCX_MEMBERS, "word/document.xml"),
        ("_validate_xlsx", XLSX_MEMBERS, "xl/workbook.xml"),
    ],
)
def test_zip_bomb_is_rejected(tmp_path, monkeypatch, validator, members, big_member):
    monkeypatch.setattr(
        upload_security, "MAX_UNZIPPED_SIZE_BYTES", 1024 * 1024, raising=False
    )
    bomb = make_zip(
        tmp_path / "bomb.zip",
        {**members, big_member: b"0" * (5 * 1024 * 1024)},
    )

    assert bomb.stat().st_size < 64 * 1024

    with pytest.raises(ValueError):
        getattr(upload_security, validator)(bomb)


def test_zip_with_too_many_entries_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_security, "MAX_ZIP_ENTRIES", 3, raising=False)
    archive = make_zip(
        tmp_path / "many.zip",
        {**DOCX_MEMBERS, "a.xml": "x", "b.xml": "x"},
    )

    with pytest.raises(ValueError):
        upload_security._validate_docx(archive)


@pytest.mark.parametrize(
    "validator, members",
    [("_validate_docx", DOCX_MEMBERS), ("_validate_xlsx", XLSX_MEMBERS)],
)
def test_normal_office_file_is_accepted(tmp_path, validator, members):
    getattr(upload_security, validator)(make_zip(tmp_path / "ok.zip", members))


def test_csv_split_inside_vietnamese_character_is_accepted(tmp_path):
    path = tmp_path / "ok.csv"
    path.write_bytes(b"a" * 65535 + "Đăng ký,Hồ sơ\n".encode("utf-8"))

    upload_security._validate_csv(path)


def test_csv_with_invalid_utf8_after_first_block_is_rejected(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_bytes(b"a" * 70000 + b"\xff\xfe,b\n")

    with pytest.raises(ValueError):
        upload_security._validate_csv(path)


def test_csv_truncated_multibyte_at_end_is_rejected(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_bytes("Đ".encode("utf-8")[:1])

    with pytest.raises(ValueError):
        upload_security._validate_csv(path)


def test_csv_with_bom_is_accepted(tmp_path):
    path = tmp_path / "ok.csv"
    path.write_bytes(b"\xef\xbb\xbf" + "tên,giá\n".encode("utf-8"))

    upload_security._validate_csv(path)


# ============================================================
# Lỗi 3: ingestion không để lại trạng thái dở dang
# ============================================================

@pytest.fixture
def domain_sandbox(tmp_path, monkeypatch, admin_env):
    domains = tmp_path / "domains"
    (domains / "demo").mkdir(parents=True)
    config_path = domains / "demo" / "config.yaml"
    config_path.write_text("domain_id: demo\nsources: []\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ingestion_api, "DOMAINS_DIR", domains)
    monkeypatch.setattr(ingestion_api, "is_valid_domain", lambda _domain: True)
    monkeypatch.setattr(my_config, "BASE_DIR", tmp_path)

    return SimpleNamespace(root=tmp_path, config=config_path)


def post_ingest(payload=b'[{"id": 1}]'):
    return TestClient(main.app).post(
        "/api/domains/demo/ingest",
        headers={"X-Admin-Key": ADMIN_KEY},
        files={"file": ("data.json", io.BytesIO(payload), "application/json")},
    )


def saved_uploads(root):
    data_dir = root / "data"
    return [p for p in data_dir.rglob("*") if p.is_file()] if data_dir.exists() else []


def test_busy_ingestion_returns_429_without_side_effects(domain_sandbox, monkeypatch):
    monkeypatch.setattr(ingestion_api, "_ingestion_semaphore", asyncio.Semaphore(0))
    before = domain_sandbox.config.read_bytes()

    response = post_ingest()

    assert response.status_code == 429
    assert domain_sandbox.config.read_bytes() == before
    assert saved_uploads(domain_sandbox.root) == []


def test_failed_pipeline_restores_config_and_removes_upload(domain_sandbox):
    before = domain_sandbox.config.read_bytes()

    response = post_ingest()

    assert response.status_code == 500
    assert domain_sandbox.config.read_bytes() == before
    assert saved_uploads(domain_sandbox.root) == []


def test_failed_raw_json_ingest_restores_previous_input(domain_sandbox):
    before = domain_sandbox.config.read_bytes()

    response = TestClient(main.app).post(
        "/api/domains/demo/ingest",
        headers={"X-Admin-Key": ADMIN_KEY},
        data={"raw_json": json.dumps([{"id": 1}])},
    )

    assert response.status_code == 500
    assert domain_sandbox.config.read_bytes() == before
    assert saved_uploads(domain_sandbox.root) == []


def test_raw_json_over_limit_is_rejected(domain_sandbox, monkeypatch):
    monkeypatch.setattr(upload_security, "MAX_UPLOAD_SIZE_BYTES", 5)

    response = TestClient(main.app).post(
        "/api/domains/demo/ingest",
        headers={"X-Admin-Key": ADMIN_KEY},
        data={"raw_json": json.dumps([{"id": 1, "title": "dài hơn 5 byte"}])},
    )

    assert response.status_code == 413


# ============================================================
# Hồi quy: các lỗi làm hỏng request hoặc mất dữ liệu
# ============================================================

def test_new_session_replaces_unknown_user_cookie(database):
    stale_user = str(uuid.uuid4())
    client = TestClient(
        main.app,
        cookies={sessions_api.USER_COOKIE_NAME: stale_user},
    )

    response = client.post("/api/sessions/new")

    assert response.status_code == 200
    issued_user = response.cookies[sessions_api.USER_COOKIE_NAME]
    assert issued_user != stale_user
    session_id = uuid.UUID(response.json()["session_id"])
    assert database.sessions[session_id] == uuid.UUID(issued_user)
    assert uuid.UUID(issued_user) in database.users


def test_new_session_keeps_known_user(database):
    client = TestClient(
        main.app,
        cookies={sessions_api.USER_COOKIE_NAME: str(ALICE)},
    )

    response = client.post("/api/sessions/new")

    assert response.status_code == 200
    session_id = uuid.UUID(response.json()["session_id"])
    assert database.sessions[session_id] == ALICE


def test_delete_domain_removes_only_its_own_data(
    admin_env,
    monkeypatch,
    tmp_path,
):
    domain = "poc_domain"
    longer_domain = "poc_domain_khac"
    deleted_collections = []

    class FakeStore:
        def __init__(self, _cfg):
            pass

        def delete_collection(self):
            deleted_collections.append(domain)

    data_dir = tmp_path / "data"
    sources_dir = data_dir / "sources"
    sources_dir.mkdir(parents=True)
    own_files = [
        data_dir / f"{domain}_raw_input.json",
        sources_dir / f"{domain}_raw_input.json",
        data_dir / f"{domain}.json",
    ]
    other_files = [
        data_dir / f"{longer_domain}_raw_input.json",
        sources_dir / f"{longer_domain}_raw_input.json",
        data_dir / f"{domain}x_raw_input.json",
    ]
    for path in own_files + other_files:
        path.write_text("[]", encoding="utf-8")

    domains_dir = tmp_path / "domains"
    (domains_dir / domain).mkdir(parents=True)

    configs = {
        domain: SimpleNamespace(
            sources=[{"path": str(own_files[0])}],
            domain_id=domain,
        ),
        longer_domain: SimpleNamespace(sources=[], domain_id=longer_domain),
    }

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(my_config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(ingestion_api, "DOMAINS_DIR", domains_dir)
    monkeypatch.setattr(ingestion_api, "is_valid_domain", lambda name: name in configs)
    monkeypatch.setattr(ingestion_api, "list_domains", lambda: list(configs))
    monkeypatch.setattr(ingestion_api, "load_domain_config", configs.__getitem__)
    monkeypatch.setattr(ingestion_api, "QdrantVectorStore", FakeStore)
    monkeypatch.setattr(
        ingestion_api,
        "VersionTracker",
        lambda: SimpleNamespace(remove_domain=lambda _domain: None),
    )
    if importlib.util.find_spec("ingestion.elastic_store"):
        monkeypatch.setattr(
            "ingestion.elastic_store.ElasticTabularStore",
            FakeStore,
        )

    response = make_client().delete(
        f"/api/domains/{domain}",
        headers={"X-Admin-Key": ADMIN_KEY},
    )

    assert response.status_code == 200
    assert response.json()["qdrant_deleted"] is True
    assert deleted_collections
    assert not (domains_dir / domain).exists()
    assert (data_dir / f"{domain}_raw_input.json").exists() is False
    assert (data_dir / f"{domain}.json").exists() is False
    assert all(path.exists() for path in other_files)


# ============================================================
# Hồi quy: cookie anonymous, session_id, giới hạn chat
# ============================================================

@pytest.fixture
def tight_rate_limit(monkeypatch):
    monkeypatch.setenv("CHAT_RATE_LIMIT_PER_MINUTE", "2")
    chat_rate_limiter.reset()
    yield
    chat_rate_limiter.reset()


def test_forged_anonymous_cookie_cannot_list_sessions(database):
    response = make_client(user_id=ANONYMOUS).get("/api/sessions")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("method, path", [
    ("get", "/api/sessions/{id}/messages"),
    ("post", "/api/sessions/{id}/switch"),
    ("delete", "/api/sessions/{id}"),
])
def test_forged_anonymous_cookie_cannot_touch_anonymous_session(
    database,
    method,
    path,
):
    client = make_client(user_id=ANONYMOUS)

    response = getattr(client, method)(path.format(id=ANON_SESSION))

    assert response.status_code == 401


def test_new_session_does_not_adopt_anonymous_cookie(database):
    response = make_client(user_id=ANONYMOUS).post("/api/sessions/new")

    assert response.status_code == 200
    session_id = uuid.UUID(response.json()["session_id"])
    assert database.sessions[session_id] != ANONYMOUS


def test_bootstrap_replaces_anonymous_cookie(database):
    response = make_client(user_id=ANONYMOUS).get("/api/session/bootstrap")

    assert response.status_code == 200
    assert uuid.UUID(response.json()["user_id"]) != ANONYMOUS


def test_chat_keeps_working_for_anonymous_session(database, chat_calls):
    response = make_client().post("/api/chat", json=chat_body(ANON_SESSION))

    assert response.status_code == 200
    assert chat_calls == [str(ANON_SESSION)]


def test_chat_rejects_non_uuid_session_id(database, chat_calls):
    response = make_client().post("/api/chat", json=chat_body("abc"))

    assert response.status_code == 422
    assert chat_calls == []


def test_chat_accepts_query_at_length_limit(database, chat_calls):
    body = chat_body(ANON_SESSION) | {"query": "a" * MAX_QUERY_CHARS}

    response = make_client().post("/api/chat", json=body)

    assert response.status_code == 200


def test_chat_rejects_query_over_length_limit(database, chat_calls):
    body = chat_body(ANON_SESSION) | {"query": "a" * (MAX_QUERY_CHARS + 1)}

    response = make_client().post("/api/chat", json=body)

    assert response.status_code == 422
    assert chat_calls == []


def test_chat_rate_limit_returns_429(database, chat_calls, tight_rate_limit):
    client = make_client()

    statuses = [
        client.post("/api/chat", json=chat_body(ANON_SESSION)).status_code
        for _ in range(3)
    ]

    assert statuses == [200, 200, 429]
    assert len(chat_calls) == 2


def test_chat_rate_limit_ignores_cookie_changes(
    database,
    chat_calls,
    tight_rate_limit,
):
    statuses = [
        make_client(user_id=uuid.uuid4())
        .post("/api/chat", json=chat_body(ANON_SESSION))
        .status_code
        for _ in range(3)
    ]

    assert statuses == [200, 200, 429]


def test_chat_rate_limit_can_be_disabled(database, chat_calls, monkeypatch):
    monkeypatch.setenv("CHAT_RATE_LIMIT_PER_MINUTE", "0")
    client = make_client()

    statuses = {
        client.post("/api/chat", json=chat_body(ANON_SESSION)).status_code
        for _ in range(5)
    }

    assert statuses == {200}


def test_rate_limit_window_recovers():
    now = [0.0]
    limiter = ChatRateLimiter(clock=lambda: now[0])

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("CHAT_RATE_LIMIT_PER_MINUTE", "1")

        assert limiter.allow("ip") is True
        assert limiter.allow("ip") is False
        assert limiter.allow("ip-khac") is True

        now[0] = 60.0
        assert limiter.allow("ip") is True


def test_websocket_rejects_query_over_length_limit(database):
    client = make_client(user_id=ALICE)

    with client.websocket_connect(f"/ws/chat?session_id={ALICE_SESSION}") as ws:
        assert ws.receive_json()["type"] == "connected"
        ws.send_json({
            "query": "a" * (MAX_QUERY_CHARS + 1),
            "domain": "administrative_procedures",
        })
        message = ws.receive_json()

    assert message["type"] == "error"
    assert message["data"]["code"] == 413


def test_websocket_rate_limit_keeps_connection_open(database, tight_rate_limit):
    chat_rate_limiter.allow("testclient")
    chat_rate_limiter.allow("testclient")
    client = make_client(user_id=ALICE)

    with client.websocket_connect(f"/ws/chat?session_id={ALICE_SESSION}") as ws:
        assert ws.receive_json()["type"] == "connected"
        payload = {"query": "xin chao", "domain": "administrative_procedures"}

        ws.send_json(payload)
        first = ws.receive_json()
        ws.send_json(payload)
        second = ws.receive_json()

    assert first["data"]["code"] == 429
    assert second["data"]["code"] == 429
