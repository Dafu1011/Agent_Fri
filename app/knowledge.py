from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.config import settings


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class KnowledgeDocument:
    id: str
    owner_user_id: str | None
    title: str
    source: str | None
    visibility: str
    created_at: str


class KnowledgeRepository:
    def __init__(self, connection_factory: Any):
        self.connection_factory = connection_factory

    @classmethod
    def from_conn_string(cls, database_url: str) -> "KnowledgeRepository":
        def connect():
            import psycopg

            return psycopg.connect(database_url)

        return cls(connect)

    def setup(self) -> None:
        with self.connection_factory() as connection:
            connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT,
                    title TEXT NOT NULL,
                    source TEXT,
                    visibility TEXT NOT NULL DEFAULT 'private'
                        CHECK (visibility IN ('private', 'public')),
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
                    content TEXT NOT NULL,
                    embedding vector(1536),
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_knowledge_documents_owner
                ON knowledge_documents(owner_user_id, visibility)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document
                ON knowledge_chunks(document_id)
                """
            )

    def add_document(
        self,
        owner_user_id: str,
        title: str,
        content: str,
        source: str | None = None,
        visibility: str = "private",
    ) -> KnowledgeDocument:
        if visibility not in {"private", "public"}:
            raise ValueError("visibility must be private or public")
        document_id = f"doc-{secrets.token_urlsafe(16)}"
        chunk_id = f"chunk-{secrets.token_urlsafe(16)}"
        now = _utc_now()
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                INSERT INTO knowledge_documents (id, owner_user_id, title, source, visibility, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, owner_user_id, title, source, visibility, created_at
                """,
                (document_id, owner_user_id, title, source, visibility, now),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO knowledge_chunks (id, document_id, content, created_at)
                VALUES (%s, %s, %s, %s)
                """,
                (chunk_id, document_id, content, now),
            )
        return KnowledgeDocument(
            id=row[0],
            owner_user_id=row[1],
            title=row[2],
            source=row[3],
            visibility=row[4],
            created_at=str(row[5]),
        )

    def search(self, user_id: str, query: str, limit: int = 5) -> list[str]:
        terms = [term for term in query.split() if term]
        pattern = f"%{terms[0] if terms else query}%"
        with self.connection_factory() as connection:
            rows = connection.execute(
                """
                SELECT c.content, d.title, d.id
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON d.id = c.document_id
                WHERE (d.owner_user_id = %s OR d.visibility = 'public')
                  AND (%s = '' OR c.content ILIKE %s OR d.title ILIKE %s)
                ORDER BY c.created_at DESC
                LIMIT %s
                """,
                (user_id, query.strip(), pattern, pattern, limit),
            ).fetchall()
        return [f"{row[1]}: {row[0]}" for row in rows]


def build_knowledge_repository() -> KnowledgeRepository:
    repository = KnowledgeRepository.from_conn_string(settings.database_url)
    repository.setup()
    return repository
