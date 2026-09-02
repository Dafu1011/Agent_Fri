from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import settings


def _utc_now() -> datetime:
    return datetime.now(UTC)


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, salt, expected = password_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    actual = hash_password(password, salt).split("$", 2)[2]
    return hmac.compare_digest(actual, expected)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class User:
    id: str
    username: str
    display_name: str | None


@dataclass(frozen=True)
class ChatThread:
    id: str
    user_id: str
    title: str | None
    created_at: str
    updated_at: str


class AuthRepository:
    def __init__(self, connection_factory: Any):
        self.connection_factory = connection_factory

    @classmethod
    def from_conn_string(cls, database_url: str) -> "AuthRepository":
        def connect():
            import psycopg

            return psycopg.connect(database_url)

        return cls(connect)

    def setup(self) -> None:
        with self.connection_factory() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    display_name TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE,
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_threads (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    title TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    display_name TEXT,
                    summary TEXT NOT NULL DEFAULT '',
                    preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
                    traits JSONB NOT NULL DEFAULT '{}'::jsonb,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_sessions_token ON user_sessions(token_hash)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_threads_user_updated ON chat_threads(user_id, updated_at DESC)"
            )

    def create_user(self, username: str, password: str, display_name: str | None = None) -> User:
        user_id = f"user-{secrets.token_urlsafe(16)}"
        now = _utc_now()
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                INSERT INTO users (id, username, password_hash, display_name, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, username, display_name
                """,
                (user_id, username, hash_password(password), display_name, now, now),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO user_profiles (user_id, display_name, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
                """,
                (user_id, display_name, now),
            )
        return User(id=row[0], username=row[1], display_name=row[2])

    def authenticate(self, username: str, password: str) -> User | None:
        with self.connection_factory() as connection:
            row = connection.execute(
                "SELECT id, username, password_hash, display_name FROM users WHERE username = %s",
                (username,),
            ).fetchone()
        if row is None or not verify_password(password, row[2]):
            return None
        return User(id=row[0], username=row[1], display_name=row[3])

    def create_session(self, user_id: str, ttl: timedelta = timedelta(days=7)) -> str:
        token = secrets.token_urlsafe(32)
        now = _utc_now()
        with self.connection_factory() as connection:
            connection.execute(
                """
                INSERT INTO user_sessions (id, user_id, token_hash, expires_at, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (f"session-{secrets.token_urlsafe(16)}", user_id, hash_token(token), now + ttl, now),
            )
        return token

    def get_user_id_for_token(self, token: str) -> str | None:
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                SELECT user_id
                FROM user_sessions
                WHERE token_hash = %s AND expires_at > %s
                LIMIT 1
                """,
                (hash_token(token), _utc_now()),
            ).fetchone()
        return row[0] if row else None

    def create_thread(self, user_id: str, title: str | None = None) -> ChatThread:
        thread_id = f"thread-{secrets.token_urlsafe(16)}"
        now = _utc_now()
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                INSERT INTO chat_threads (id, user_id, title, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, user_id, title, created_at, updated_at
                """,
                (thread_id, user_id, title, now, now),
            ).fetchone()
        return self._thread_from_row(row)

    def thread_belongs_to_user(self, thread_id: str, user_id: str) -> bool:
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                SELECT id
                FROM chat_threads
                WHERE id = %s AND user_id = %s
                LIMIT 1
                """,
                (thread_id, user_id),
            ).fetchone()
        return row is not None

    def list_threads(self, user_id: str, limit: int = 50) -> list[ChatThread]:
        with self.connection_factory() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, title, created_at, updated_at
                FROM chat_threads
                WHERE user_id = %s
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            ).fetchall()
        return [self._thread_from_row(row) for row in rows]

    def get_profile(self, user_id: str) -> dict[str, Any]:
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                SELECT display_name, summary, preferences, traits
                FROM user_profiles
                WHERE user_id = %s
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return {
                "display_name": None,
                "summary": "",
                "preferences": {},
                "traits": {},
            }
        return {
            "display_name": row[0],
            "summary": row[1],
            "preferences": row[2],
            "traits": row[3],
        }

    def upsert_profile(
        self,
        user_id: str,
        display_name: str | None,
        summary: str,
        preferences: dict[str, Any],
        traits: dict[str, Any],
    ) -> None:
        from psycopg.types.json import Jsonb

        with self.connection_factory() as connection:
            connection.execute(
                """
                INSERT INTO user_profiles (user_id, display_name, summary, preferences, traits, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE
                SET display_name = EXCLUDED.display_name,
                    summary = EXCLUDED.summary,
                    preferences = EXCLUDED.preferences,
                    traits = EXCLUDED.traits,
                    updated_at = EXCLUDED.updated_at
                """,
                (user_id, display_name, summary, Jsonb(preferences), Jsonb(traits), _utc_now()),
            )

    def _thread_from_row(self, row: Any) -> ChatThread:
        return ChatThread(
            id=row[0],
            user_id=row[1],
            title=row[2],
            created_at=str(row[3]),
            updated_at=str(row[4]),
        )


def build_auth_repository() -> AuthRepository:
    repository = AuthRepository.from_conn_string(settings.database_url)
    repository.setup()
    return repository
