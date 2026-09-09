from datetime import UTC, datetime, timedelta
import base64
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app.auth import AuthRepository, hash_email_code, hash_password, verify_email_code, verify_password
from app.main import app


def test_password_hash_verification():
    password_hash = hash_password("secret")

    assert verify_password("secret", password_hash) is True
    assert verify_password("wrong", password_hash) is False


def test_auth_repository_setup_creates_user_tables():
    class FakeConnection:
        def __init__(self):
            self.statements = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            self.statements.append(str(statement))

    connection = FakeConnection()
    repository = AuthRepository(lambda: connection)

    repository.setup()

    assert any("CREATE TABLE IF NOT EXISTS users" in stmt for stmt in connection.statements)
    assert any("CREATE TABLE IF NOT EXISTS user_sessions" in stmt for stmt in connection.statements)
    assert any("CREATE TABLE IF NOT EXISTS chat_threads" in stmt for stmt in connection.statements)
    assert any("CREATE TABLE IF NOT EXISTS chat_messages" in stmt for stmt in connection.statements)
    assert any("ADD COLUMN IF NOT EXISTS pinned_at" in stmt for stmt in connection.statements)
    assert any("ADD COLUMN IF NOT EXISTS deleted_at" in stmt for stmt in connection.statements)
    assert any("CREATE TABLE IF NOT EXISTS user_profiles" in stmt for stmt in connection.statements)
    assert any("CREATE TABLE IF NOT EXISTS email_verification_codes" in stmt for stmt in connection.statements)
    assert any("ADD COLUMN IF NOT EXISTS email" in stmt for stmt in connection.statements)
    assert any("idx_users_email_lower" in stmt for stmt in connection.statements)


def test_auth_repository_saves_and_lists_thread_messages():
    class FakeInsertResult:
        def fetchone(self):
            return (
                "msg-1",
                "thread-1",
                "user-1",
                "assistant",
                "已生成文档。",
                [{"media_type": "file", "download_url": "/documents/files/file-1/download"}],
                "2026-09-09T00:00:00+00:00",
            )

    class FakeListResult:
        def fetchall(self):
            return [
                (
                    "msg-1",
                    "thread-1",
                    "user-1",
                    "assistant",
                    "已生成文档。",
                    [{"media_type": "file", "download_url": "/documents/files/file-1/download"}],
                    "2026-09-09T00:00:00+00:00",
                )
            ]

    class FakeConnection:
        def __init__(self):
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            text = str(statement)
            self.calls.append((text, params))
            if "INSERT INTO chat_messages" in text:
                return FakeInsertResult()
            return FakeListResult()

    connection = FakeConnection()
    repository = AuthRepository(lambda: connection)

    saved = repository.save_thread_message(
        user_id="user-1",
        thread_id="thread-1",
        role="assistant",
        text="已生成文档。",
        attachments=[{"media_type": "file", "download_url": "/documents/files/file-1/download"}],
    )
    messages = repository.list_thread_messages("user-1", "thread-1")

    assert saved.text == "已生成文档。"
    assert saved.attachments == [{"media_type": "file", "download_url": "/documents/files/file-1/download"}]
    assert messages[0].role == "assistant"
    assert messages[0].attachments[0]["media_type"] == "file"
    assert any("UPDATE chat_threads" in call[0] for call in connection.calls)


def test_auth_repository_summarizes_thread_title_from_first_user_message():
    class FakeInsertResult:
        def fetchone(self):
            return (
                "msg-1",
                "thread-1",
                "user-1",
                "user",
                "请帮我分析多Agent系统的任务拆分与工具选择流程",
                [],
                "2026-09-09T00:00:00+00:00",
            )

    class FakeConnection:
        def __init__(self):
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            self.calls.append((str(statement), params))
            return FakeInsertResult()

    connection = FakeConnection()
    repository = AuthRepository(lambda: connection)

    repository.save_thread_message(
        user_id="user-1",
        thread_id="thread-1",
        role="user",
        text="请帮我分析多Agent系统的任务拆分与工具选择流程",
    )

    update_call = next(call for call in connection.calls if "UPDATE chat_threads" in call[0])
    assert update_call[1][1] == "请帮我分析多Agent系统的任务拆分与工具选择流程"


def test_auth_repository_manages_thread_title_pin_and_delete():
    class FakeThreadResult:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

    class FakeConnection:
        def __init__(self):
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            text = str(statement)
            self.calls.append((text, params))
            if "SET title" in text:
                return FakeThreadResult(
                    ("thread-1", "user-1", "重命名标题", "2026-09-09", "2026-09-09", None)
                )
            if "SET pinned_at" in text:
                return FakeThreadResult(
                    ("thread-1", "user-1", "重命名标题", "2026-09-09", "2026-09-09", "2026-09-09")
                )
            if "SET deleted_at" in text:
                return FakeThreadResult(
                    ("thread-1", "user-1", "重命名标题", "2026-09-09", "2026-09-09", "2026-09-09")
                )
            return FakeThreadResult(None)

    connection = FakeConnection()
    repository = AuthRepository(lambda: connection)

    renamed = repository.rename_thread("user-1", "thread-1", "  重命名标题  ")
    pinned = repository.set_thread_pinned("user-1", "thread-1", True)
    deleted = repository.delete_thread("user-1", "thread-1")

    assert renamed is not None
    assert renamed.title == "重命名标题"
    assert pinned is not None
    assert pinned.pinned_at is not None
    assert deleted is True
    assert any("deleted_at IS NULL" in call[0] for call in connection.calls)


def test_auth_repository_checks_thread_ownership():
    class FakeResult:
        def fetchone(self):
            return ("thread-1",)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            assert "WHERE id = %s AND user_id = %s" in str(statement)
            assert params == ("thread-1", "user-1")
            return FakeResult()

    repository = AuthRepository(lambda: FakeConnection())

    assert repository.thread_belongs_to_user("thread-1", "user-1") is True


def test_auth_repository_rejects_expired_session():
    class FakeResult:
        def fetchone(self):
            return None

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            assert "expires_at > %s" in str(statement)
            assert isinstance(params[1], datetime)
            return FakeResult()

    repository = AuthRepository(lambda: FakeConnection())

    assert repository.get_user_id_for_token("token") is None


def test_email_code_hash_verification():
    code_hash = hash_email_code("654321", "user@example.com")

    assert verify_email_code("654321", "USER@example.com", code_hash) is True
    assert verify_email_code("000000", "user@example.com", code_hash) is False


def test_auth_repository_authenticates_by_username_or_email():
    password_hash = hash_password("secret123")
    calls = []

    class FakeResult:
        def fetchone(self):
            return ("user-1", "agent", "agent@example.com", password_hash, "Agent")

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            calls.append((str(statement), params))
            return FakeResult()

    repository = AuthRepository(lambda: FakeConnection())

    user = repository.authenticate("AGENT@example.com", "secret123")

    assert user is not None
    assert user.id == "user-1"
    assert user.username == "agent"
    assert user.email == "agent@example.com"
    assert "username = %s OR lower(email) = lower(%s)" in calls[0][0]
    assert calls[0][1] == ("AGENT@example.com", "AGENT@example.com")


def test_auth_email_code_endpoint_sends_verification_code(monkeypatch):
    sent = []

    class FakeRepository:
        def issue_email_verification_code(self, email, purpose):
            assert email == "new@example.com"
            assert purpose == "register"
            return "123456"

    class FakeSender:
        def send_verification_code(self, email, code, purpose):
            sent.append((email, code, purpose))

    monkeypatch.setattr("app.api.auth.get_auth_repository", lambda request: FakeRepository())
    monkeypatch.setattr("app.api.auth.get_email_code_sender", lambda request: FakeSender())

    client = TestClient(app)
    response = client.post(
        "/auth/email-code",
        json={"email": "new@example.com", "purpose": "register"},
    )

    assert response.status_code == 200
    assert response.json() == {"cooldown_seconds": 60}
    assert sent == [("new@example.com", "123456", "register")]


def test_register_endpoint_requires_consumed_email_code(monkeypatch):
    created = []

    class FakeUser:
        id = "user-1"

    class FakeRepository:
        def consume_email_verification_code(self, email, code, purpose):
            assert (email, code, purpose) == ("new@example.com", "123456", "register")
            return True

        def create_user(self, username, password, display_name=None, email=None):
            created.append((username, password, display_name, email))
            return FakeUser()

        def create_session(self, user_id):
            assert user_id == "user-1"
            return "token-1"

    monkeypatch.setattr("app.api.auth.get_auth_repository", lambda request: FakeRepository())

    client = TestClient(app)
    response = client.post(
        "/auth/register",
        data={
            "email": "new@example.com",
            "username": "agent",
            "password": "secret123",
            "verification_code": "123456",
            "display_name": "Agent",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"user_id": "user-1", "token": "token-1"}
    assert created == [("agent", "secret123", "Agent", "new@example.com")]


def test_profile_endpoint_updates_display_name(monkeypatch):
    updates = []

    class FakeRepository:
        def get_profile(self, user_id):
            assert user_id == "user-1"
            return {
                "username": "agent",
                "email": "agent@example.com",
                "display_name": "Old",
                "has_avatar": False,
                "summary": "summary",
                "preferences": {},
                "traits": {},
            }

        def upsert_profile(self, user_id, display_name, summary, preferences, traits):
            updates.append((user_id, display_name, summary, preferences, traits))

    monkeypatch.setattr("app.api.auth.get_current_user_id", lambda request: "user-1")
    monkeypatch.setattr("app.api.auth.get_auth_repository", lambda request: FakeRepository())

    client = TestClient(app)
    response = client.patch("/profile", json={"display_name": "New"})

    assert response.status_code == 200
    assert response.json()["display_name"] == "New"
    assert updates == [("user-1", "New", "summary", {}, {})]


def test_thread_management_endpoints_rename_pin_and_delete(monkeypatch):
    calls = []

    class FakeThread:
        id = "thread-1"
        user_id = "user-1"
        title = "Renamed"
        created_at = "2026-09-09"
        updated_at = "2026-09-09"
        pinned_at = "2026-09-09"

    class FakeRepository:
        def rename_thread(self, user_id, thread_id, title):
            calls.append(("rename", user_id, thread_id, title))
            return FakeThread()

        def set_thread_pinned(self, user_id, thread_id, pinned):
            calls.append(("pin", user_id, thread_id, pinned))
            return FakeThread()

        def delete_thread(self, user_id, thread_id):
            calls.append(("delete", user_id, thread_id))
            return True

    monkeypatch.setattr("app.api.auth.get_current_user_id", lambda request: "user-1")
    monkeypatch.setattr("app.api.auth.get_auth_repository", lambda request: FakeRepository())

    client = TestClient(app)
    rename_response = client.patch("/threads/thread-1", json={"title": "Renamed"})
    pin_response = client.patch("/threads/thread-1/pin", json={"pinned": True})
    delete_response = client.delete("/threads/thread-1")

    assert rename_response.status_code == 200
    assert rename_response.json()["title"] == "Renamed"
    assert rename_response.json()["pinned_at"] == "2026-09-09"
    assert pin_response.status_code == 200
    assert pin_response.json()["pinned_at"] == "2026-09-09"
    assert delete_response.status_code == 204
    assert calls == [
        ("rename", "user-1", "thread-1", "Renamed"),
        ("pin", "user-1", "thread-1", True),
        ("delete", "user-1", "thread-1"),
    ]


def test_profile_endpoint_changes_email_with_code(monkeypatch):
    calls = []

    class FakeRepository:
        def consume_email_verification_code(self, email, code, purpose):
            calls.append(("consume", email, code, purpose))
            return True

        def update_user_email(self, user_id, email):
            calls.append(("update", user_id, email))

        def get_profile(self, user_id):
            return {
                "username": "agent",
                "email": "new@example.com",
                "display_name": "Agent",
                "has_avatar": False,
                "summary": "",
                "preferences": {},
                "traits": {},
            }

    monkeypatch.setattr("app.api.auth.get_current_user_id", lambda request: "user-1")
    monkeypatch.setattr("app.api.auth.get_auth_repository", lambda request: FakeRepository())

    client = TestClient(app)
    response = client.patch(
        "/profile/email",
        json={"email": "new@example.com", "verification_code": "123456"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "new@example.com"
    assert calls == [
        ("consume", "new@example.com", "123456", "email_change"),
        ("update", "user-1", "new@example.com"),
    ]


def test_profile_avatar_endpoint_validates_and_saves_image(monkeypatch):
    calls = []
    png_buffer = BytesIO()
    Image.new("RGBA", (1, 1), (255, 255, 255, 255)).save(png_buffer, format="PNG")
    png_bytes = png_buffer.getvalue()

    class FakeRepository:
        def set_user_avatar(self, user_id, path, mime_type):
            calls.append((user_id, path.name, mime_type))

        def get_profile(self, user_id):
            return {
                "username": "agent",
                "email": "agent@example.com",
                "display_name": "Agent",
                "has_avatar": True,
                "summary": "",
                "preferences": {},
                "traits": {},
            }

    monkeypatch.setattr("app.api.auth.get_current_user_id", lambda request: "user-1")
    monkeypatch.setattr("app.api.auth.get_auth_repository", lambda request: FakeRepository())

    client = TestClient(app)
    response = client.post(
        "/profile/avatar",
        files={"avatar": ("avatar.png", png_bytes, "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["has_avatar"] is True
    assert calls == [("user-1", "avatar.png", "image/png")]


def test_profile_avatar_endpoint_rejects_corrupt_image(monkeypatch):
    class FakeRepository:
        def set_user_avatar(self, user_id, path, mime_type):
            raise AssertionError("corrupt image should not be saved")

    monkeypatch.setattr("app.api.auth.get_current_user_id", lambda request: "user-1")
    monkeypatch.setattr("app.api.auth.get_auth_repository", lambda request: FakeRepository())

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/profile/avatar",
        files={"avatar": ("avatar.png", b"not-really-a-png", "image/png")},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Avatar is not a valid image"}


def test_profile_avatar_endpoint_rejects_png_with_bad_crc(monkeypatch):
    corrupt_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lQnU7wAAAABJRU5ErkJggg=="
    )

    class FakeRepository:
        def set_user_avatar(self, user_id, path, mime_type):
            raise AssertionError("corrupt image should not be saved")

    monkeypatch.setattr("app.api.auth.get_current_user_id", lambda request: "user-1")
    monkeypatch.setattr("app.api.auth.get_auth_repository", lambda request: FakeRepository())

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/profile/avatar",
        files={"avatar": ("avatar.png", corrupt_png, "image/png")},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Avatar is not a valid image"}


def test_profile_avatar_file_endpoint_returns_current_avatar(monkeypatch, tmp_path):
    avatar_path = tmp_path / "avatar.png"
    avatar_path.write_bytes(b"avatar-bytes")

    class FakeRepository:
        def get_user_avatar(self, user_id):
            assert user_id == "user-1"
            return avatar_path, "image/png"

    monkeypatch.setattr("app.api.auth.get_current_user_id", lambda request: "user-1")
    monkeypatch.setattr("app.api.auth.get_auth_repository", lambda request: FakeRepository())

    client = TestClient(app)
    response = client.get("/profile/avatar")

    assert response.status_code == 200
    assert response.content == b"avatar-bytes"
    assert response.headers["content-type"] == "image/png"
