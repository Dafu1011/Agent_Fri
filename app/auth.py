from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import smtplib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_email(email: str) -> str:
    return email.strip().lower()


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


def hash_email_code(code: str, email: str) -> str:
    normalized = normalize_email(email)
    digest = hashlib.sha256(f"{normalized}:{code}".encode()).hexdigest()
    return f"sha256${digest}"


def verify_email_code(code: str, email: str, code_hash: str) -> bool:
    return hmac.compare_digest(hash_email_code(code, email), code_hash)


@dataclass(frozen=True)
class User:
    id: str
    username: str
    email: str | None
    display_name: str | None


@dataclass(frozen=True)
class ChatThread:
    id: str
    user_id: str
    title: str | None
    created_at: str
    updated_at: str
    pinned_at: str | None = None


@dataclass(frozen=True)
class ChatStoredMessage:
    id: str
    thread_id: str
    user_id: str
    role: str
    text: str
    attachments: list[dict[str, Any]]
    created_at: str


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
                    email TEXT UNIQUE,
                    password_hash TEXT NOT NULL,
                    display_name TEXT,
                    avatar_path TEXT,
                    avatar_mime_type TEXT,
                    avatar_updated_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            connection.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT")
            connection.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_path TEXT")
            connection.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_mime_type TEXT")
            connection.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_updated_at TIMESTAMPTZ")
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
                    pinned_at TIMESTAMPTZ,
                    deleted_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            connection.execute("ALTER TABLE chat_threads ADD COLUMN IF NOT EXISTS pinned_at TIMESTAMPTZ")
            connection.execute("ALTER TABLE chat_threads ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    text TEXT NOT NULL,
                    attachments JSONB NOT NULL DEFAULT '[]'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL
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
                """
                CREATE TABLE IF NOT EXISTS email_verification_codes (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    code_hash TEXT NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    used_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_sessions_token ON user_sessions(token_hash)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_threads_user_updated ON chat_threads(user_id, updated_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_messages_thread_created ON chat_messages(thread_id, created_at ASC)"
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_lower ON users (lower(email)) WHERE email IS NOT NULL"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_email_codes_lookup ON email_verification_codes(email, purpose, created_at DESC)"
            )

    def create_user(
        self,
        username: str,
        password: str,
        display_name: str | None = None,
        email: str | None = None,
    ) -> User:
        user_id = f"user-{secrets.token_urlsafe(16)}"
        now = _utc_now()
        normalized_email = normalize_email(email) if email else None
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                INSERT INTO users (id, username, email, password_hash, display_name, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, username, email, display_name
                """,
                (user_id, username, normalized_email, hash_password(password), display_name, now, now),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO user_profiles (user_id, display_name, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
                """,
                (user_id, display_name, now),
            )
        return User(id=row[0], username=row[1], email=row[2], display_name=row[3])

    def authenticate(self, identifier: str, password: str) -> User | None:
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                SELECT id, username, email, password_hash, display_name
                FROM users
                WHERE username = %s OR lower(email) = lower(%s)
                LIMIT 1
                """,
                (identifier, identifier),
            ).fetchone()
        if row is None or not verify_password(password, row[3]):
            return None
        return User(id=row[0], username=row[1], email=row[2], display_name=row[4])

    def issue_email_verification_code(self, email: str, purpose: str) -> str:
        normalized_email = normalize_email(email)
        now = _utc_now()
        cooldown_started_at = now - timedelta(seconds=settings.auth_email_code_cooldown_seconds)
        with self.connection_factory() as connection:
            recent = connection.execute(
                """
                SELECT id
                FROM email_verification_codes
                WHERE email = %s AND purpose = %s AND created_at > %s
                LIMIT 1
                """,
                (normalized_email, purpose, cooldown_started_at),
            ).fetchone()
            if recent is not None:
                raise ValueError("Email verification code was requested too recently")

            code = f"{secrets.randbelow(1_000_000):06d}"
            connection.execute(
                """
                INSERT INTO email_verification_codes
                    (id, email, purpose, code_hash, expires_at, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    f"email-code-{secrets.token_urlsafe(16)}",
                    normalized_email,
                    purpose,
                    hash_email_code(code, normalized_email),
                    now + timedelta(seconds=settings.auth_email_code_ttl_seconds),
                    now,
                ),
            )
        return code

    def consume_email_verification_code(self, email: str, code: str, purpose: str) -> bool:
        normalized_email = normalize_email(email)
        now = _utc_now()
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                SELECT id, code_hash, expires_at, used_at
                FROM email_verification_codes
                WHERE email = %s AND purpose = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (normalized_email, purpose),
            ).fetchone()
            if row is None or row[3] is not None or row[2] <= now:
                return False
            if not verify_email_code(code, normalized_email, row[1]):
                return False
            connection.execute(
                "UPDATE email_verification_codes SET used_at = %s WHERE id = %s",
                (now, row[0]),
            )
        return True

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
                RETURNING id, user_id, title, created_at, updated_at, pinned_at
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
                WHERE id = %s AND user_id = %s AND deleted_at IS NULL
                LIMIT 1
                """,
                (thread_id, user_id),
            ).fetchone()
        return row is not None

    def list_threads(self, user_id: str, limit: int = 50) -> list[ChatThread]:
        with self.connection_factory() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, title, created_at, updated_at, pinned_at
                FROM chat_threads
                WHERE user_id = %s AND deleted_at IS NULL
                ORDER BY
                    CASE WHEN pinned_at IS NULL THEN 1 ELSE 0 END ASC,
                    pinned_at DESC,
                    updated_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            ).fetchall()
        return [self._thread_from_row(row) for row in rows]

    def rename_thread(self, user_id: str, thread_id: str, title: str) -> ChatThread | None:
        now = _utc_now()
        clean_title = " ".join(title.split())[:80]
        if not clean_title:
            clean_title = "New chat"
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                UPDATE chat_threads
                SET title = %s,
                    updated_at = %s
                WHERE id = %s AND user_id = %s AND deleted_at IS NULL
                RETURNING id, user_id, title, created_at, updated_at, pinned_at
                """,
                (clean_title, now, thread_id, user_id),
            ).fetchone()
        return self._thread_from_row(row) if row is not None else None

    def set_thread_pinned(self, user_id: str, thread_id: str, pinned: bool) -> ChatThread | None:
        now = _utc_now()
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                UPDATE chat_threads
                SET pinned_at = %s,
                    updated_at = %s
                WHERE id = %s AND user_id = %s AND deleted_at IS NULL
                RETURNING id, user_id, title, created_at, updated_at, pinned_at
                """,
                (now if pinned else None, now, thread_id, user_id),
            ).fetchone()
        return self._thread_from_row(row) if row is not None else None

    def delete_thread(self, user_id: str, thread_id: str) -> bool:
        now = _utc_now()
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                UPDATE chat_threads
                SET deleted_at = %s,
                    updated_at = %s
                WHERE id = %s AND user_id = %s AND deleted_at IS NULL
                RETURNING id, user_id, title, created_at, updated_at, pinned_at
                """,
                (now, now, thread_id, user_id),
            ).fetchone()
        return row is not None

    def save_thread_message(
        self,
        *,
        user_id: str,
        thread_id: str,
        role: str,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> ChatStoredMessage:
        from psycopg.types.json import Jsonb

        if role not in {"user", "assistant"}:
            raise ValueError("role must be user or assistant")
        now = _utc_now()
        message_id = f"msg-{secrets.token_urlsafe(16)}"
        safe_attachments = attachments or []
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                INSERT INTO chat_messages (
                    id, thread_id, user_id, role, text, attachments, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, thread_id, user_id, role, text, attachments, created_at
                """,
                (
                    message_id,
                    thread_id,
                    user_id,
                    role,
                    text,
                    Jsonb(safe_attachments),
                    now,
                ),
            ).fetchone()
            connection.execute(
                """
                UPDATE chat_threads
                SET updated_at = %s,
                    title = COALESCE(title, %s)
                WHERE id = %s AND user_id = %s AND deleted_at IS NULL
                """,
                (
                    now,
                    _thread_title_from_message(text) if role == "user" else None,
                    thread_id,
                    user_id,
                ),
            )
        return self._stored_message_from_row(row)

    def list_thread_messages(
        self,
        user_id: str,
        thread_id: str,
        limit: int = 200,
    ) -> list[ChatStoredMessage]:
        with self.connection_factory() as connection:
            rows = connection.execute(
                """
                SELECT id, thread_id, user_id, role, text, attachments, created_at
                FROM chat_messages
                WHERE user_id = %s AND thread_id = %s
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (user_id, thread_id, limit),
            ).fetchall()
        return [self._stored_message_from_row(row) for row in rows]

    def get_profile(self, user_id: str) -> dict[str, Any]:
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                SELECT u.username,
                       u.email,
                       COALESCE(p.display_name, u.display_name),
                       COALESCE(p.summary, ''),
                       COALESCE(p.preferences, '{}'::jsonb),
                       COALESCE(p.traits, '{}'::jsonb),
                       u.avatar_path IS NOT NULL
                FROM users u
                LEFT JOIN user_profiles p ON p.user_id = u.id
                WHERE u.id = %s
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return {
                "username": None,
                "email": None,
                "display_name": None,
                "has_avatar": False,
                "summary": "",
                "preferences": {},
                "traits": {},
            }
        return {
            "username": row[0],
            "email": row[1],
            "display_name": row[2],
            "summary": row[3],
            "preferences": row[4],
            "traits": row[5],
            "has_avatar": bool(row[6]),
        }

    def update_user_email(self, user_id: str, email: str) -> None:
        with self.connection_factory() as connection:
            connection.execute(
                """
                UPDATE users
                SET email = %s, updated_at = %s
                WHERE id = %s
                """,
                (normalize_email(email), _utc_now(), user_id),
            )

    def set_user_avatar(self, user_id: str, path: Path, mime_type: str) -> None:
        with self.connection_factory() as connection:
            connection.execute(
                """
                UPDATE users
                SET avatar_path = %s,
                    avatar_mime_type = %s,
                    avatar_updated_at = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (str(path), mime_type, _utc_now(), _utc_now(), user_id),
            )

    def get_user_avatar(self, user_id: str) -> tuple[Path, str] | None:
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                SELECT avatar_path, avatar_mime_type
                FROM users
                WHERE id = %s
                """,
                (user_id,),
            ).fetchone()
        if row is None or not row[0]:
            return None
        path = Path(str(row[0]))
        if not path.exists():
            return None
        return path, row[1] or "application/octet-stream"

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
            pinned_at=str(row[5]) if len(row) > 5 and row[5] is not None else None,
        )

    def _stored_message_from_row(self, row: Any) -> ChatStoredMessage:
        return ChatStoredMessage(
            id=row[0],
            thread_id=row[1],
            user_id=row[2],
            role=row[3],
            text=row[4],
            attachments=list(row[5] or []),
            created_at=str(row[6]),
        )


def _thread_title_from_message(text: str) -> str:
    compact = " ".join(text.split())
    return compact[:40] if compact else "New chat"


def build_auth_repository() -> AuthRepository:
    repository = AuthRepository.from_conn_string(settings.database_url)
    repository.setup()
    return repository


class EmailCodeSender:
    def send_verification_code(self, email: str, code: str, purpose: str) -> None:
        if not settings.auth_smtp_host.strip():
            logger.warning("SMTP is not configured; verification code for %s is %s", email, code)
            return

        sender = settings.auth_smtp_from_email or settings.auth_smtp_username
        if not sender:
            raise RuntimeError("AUTH_SMTP_FROM_EMAIL or AUTH_SMTP_USERNAME must be configured")

        message = EmailMessage()
        message["Subject"] = "Your verification code"
        message["From"] = sender
        message["To"] = email
        action = "register your account" if purpose == "register" else "change your email"
        message.set_content(
            f"Your verification code is {code}.\n\n"
            f"Use it to {action}. It expires in {settings.auth_email_code_ttl_seconds // 60} minutes."
        )

        with smtplib.SMTP(settings.auth_smtp_host, settings.auth_smtp_port, timeout=10) as smtp:
            if settings.auth_smtp_use_tls:
                smtp.starttls()
            if settings.auth_smtp_username:
                smtp.login(settings.auth_smtp_username, settings.auth_smtp_password)
            smtp.send_message(message)
