from datetime import UTC, datetime, timedelta

from app.auth import AuthRepository, hash_password, verify_password


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
    assert any("CREATE TABLE IF NOT EXISTS user_profiles" in stmt for stmt in connection.statements)


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
