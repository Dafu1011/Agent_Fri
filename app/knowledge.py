from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

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


@dataclass(frozen=True)
class KnowledgeSearchResult:
    chunk_id: str
    document_id: str
    title: str
    content: str
    score: float
    sources: list[str]


class EmbeddingProvider(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...


class OpenAIEmbeddingProvider:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._client().embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._client().embed_query(text)

    def _client(self):
        from langchain_openai import OpenAIEmbeddings

        api_key = (
            settings.openai_embedding_api_key
            if settings.openai_embedding_base_url
            else settings.openai_embedding_api_key or settings.openai_api_key
        )
        return OpenAIEmbeddings(
            model=settings.openai_embedding_model,
            api_key=api_key,
            base_url=settings.openai_embedding_base_url or settings.openai_base_url,
            check_embedding_ctx_length=False,
            dimensions=settings.openai_embedding_dimensions,
        )


def format_vector(vector: list[float]) -> str:
    return "[" + ",".join(str(value) for value in vector) + "]"


def chunk_text(text: str, chunk_size: int = 900, chunk_overlap: int = 120) -> list[str]:
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not normalized:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be non-negative and smaller than chunk_size")

    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        chunk = normalized[start : start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        if start + chunk_size >= len(normalized):
            break
        start += chunk_size - chunk_overlap
    return chunks


def reciprocal_rank_fusion(
    keyword_ids: list[str],
    vector_ids: list[str],
    k: int = 60,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranked_ids in (keyword_ids, vector_ids):
        for index, chunk_id in enumerate(ranked_ids, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + (1.0 / (k + index))
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


class KnowledgeRepository:
    def __init__(
        self,
        connection_factory: Any,
        embedding_provider: EmbeddingProvider | None = None,
        chunk_size: int = 900,
        chunk_overlap: int = 120,
    ):
        self.connection_factory = connection_factory
        self.embedding_provider = embedding_provider
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    @classmethod
    def from_conn_string(
        cls,
        database_url: str,
        embedding_provider: EmbeddingProvider | None = None,
        chunk_size: int = 900,
        chunk_overlap: int = 120,
    ) -> "KnowledgeRepository":
        def connect():
            import psycopg

            return psycopg.connect(database_url)

        return cls(
            connect,
            embedding_provider=embedding_provider,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

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
                    search_tsv TSVECTOR,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            connection.execute(
                """
                ALTER TABLE knowledge_chunks
                ADD COLUMN IF NOT EXISTS search_tsv TSVECTOR
                """
            )
            connection.execute(
                """
                UPDATE knowledge_chunks
                SET search_tsv = to_tsvector('simple', content)
                WHERE search_tsv IS NULL
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
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_search_tsv
                ON knowledge_chunks USING GIN (search_tsv)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding_hnsw
                ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)
                WHERE embedding IS NOT NULL
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
        chunks = chunk_text(content, chunk_size=self.chunk_size, chunk_overlap=self.chunk_overlap)
        if not chunks:
            raise ValueError("content must not be empty")
        embeddings = self._embed_documents(chunks)
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
            for index, chunk in enumerate(chunks):
                embedding = embeddings[index] if index < len(embeddings) else None
                connection.execute(
                    """
                    INSERT INTO knowledge_chunks (
                        id, document_id, content, embedding, search_tsv, metadata, created_at
                    )
                    VALUES (
                        %s, %s, %s, %s::vector,
                        to_tsvector('simple', %s),
                        %s::jsonb,
                        %s
                    )
                    """,
                    (
                        f"chunk-{secrets.token_urlsafe(16)}",
                        document_id,
                        chunk,
                        format_vector(embedding) if embedding else None,
                        chunk,
                        '{"chunk_index": %d}' % index,
                        now,
                    ),
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
        query_embedding = self._embed_query(query)
        results = self.hybrid_search(
            user_id=user_id,
            query=query,
            query_embedding=query_embedding,
            limit=limit,
        )
        return [f"{result.title}: {result.content}" for result in results]

    def hybrid_search(
        self,
        user_id: str,
        query: str,
        query_embedding: list[float] | None = None,
        limit: int = 5,
    ) -> list[KnowledgeSearchResult]:
        keyword_rows = self.keyword_search(user_id=user_id, query=query, limit=max(limit * 4, limit))
        vector_rows = (
            self.vector_search(
                user_id=user_id,
                query_embedding=query_embedding,
                limit=max(limit * 4, limit),
            )
            if query_embedding
            else []
        )
        if not vector_rows:
            return [
                KnowledgeSearchResult(
                    chunk_id=row[0],
                    content=row[1],
                    title=row[2],
                    document_id=row[3],
                    score=float(row[4] or 0),
                    sources=["keyword"],
                )
                for row in keyword_rows[:limit]
            ]

        rows_by_id = {
            row[0]: row for row in [*keyword_rows, *vector_rows]
        }
        keyword_ids = [row[0] for row in keyword_rows]
        vector_ids = [row[0] for row in vector_rows]
        vector_id_set = set(vector_ids)
        keyword_id_set = set(keyword_ids)
        fused = reciprocal_rank_fusion(keyword_ids=keyword_ids, vector_ids=vector_ids)
        results: list[KnowledgeSearchResult] = []
        for chunk_id, score in fused[:limit]:
            row = rows_by_id[chunk_id]
            sources = []
            if chunk_id in keyword_id_set:
                sources.append("keyword")
            if chunk_id in vector_id_set:
                sources.append("vector")
            results.append(
                KnowledgeSearchResult(
                    chunk_id=row[0],
                    content=row[1],
                    title=row[2],
                    document_id=row[3],
                    score=score,
                    sources=sources,
                )
            )
        return results

    def keyword_search(self, user_id: str, query: str, limit: int) -> list[Any]:
        terms = [term for term in query.split() if term]
        pattern = f"%{terms[0] if terms else query}%"
        with self.connection_factory() as connection:
            return connection.execute(
                """
                SELECT c.id, c.content, d.title, d.id,
                       ts_rank_cd(c.search_tsv, websearch_to_tsquery('simple', %s)) AS rank
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON d.id = c.document_id
                WHERE (d.owner_user_id = %s OR d.visibility = 'public')
                  AND (
                    %s = ''
                    OR c.search_tsv @@ websearch_to_tsquery('simple', %s)
                    OR c.content ILIKE %s
                    OR d.title ILIKE %s
                  )
                ORDER BY rank DESC, c.created_at DESC
                LIMIT %s
                """,
                (query.strip(), user_id, query.strip(), query.strip(), pattern, pattern, limit),
            ).fetchall()

    def vector_search(
        self,
        user_id: str,
        query_embedding: list[float],
        limit: int,
    ) -> list[Any]:
        with self.connection_factory() as connection:
            return connection.execute(
                """
                SELECT c.id, c.content, d.title, d.id,
                       c.embedding <=> %s::vector AS distance
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON d.id = c.document_id
                WHERE (d.owner_user_id = %s OR d.visibility = 'public')
                  AND c.embedding IS NOT NULL
                ORDER BY c.embedding <=> %s::vector ASC
                LIMIT %s
                """,
                (format_vector(query_embedding), user_id, format_vector(query_embedding), limit),
            ).fetchall()

    def _embed_documents(self, chunks: list[str]) -> list[list[float]]:
        if self.embedding_provider is None:
            return []
        return self.embedding_provider.embed_documents(chunks)

    def _embed_query(self, query: str) -> list[float] | None:
        if self.embedding_provider is None or not query.strip():
            return None
        return self.embedding_provider.embed_query(query)


def build_knowledge_repository() -> KnowledgeRepository:
    embedding_api_key = (
        settings.openai_embedding_api_key
        if settings.openai_embedding_base_url
        else settings.openai_embedding_api_key or settings.openai_api_key
    )
    embedding_provider = OpenAIEmbeddingProvider() if embedding_api_key else None
    repository = KnowledgeRepository.from_conn_string(
        settings.database_url,
        embedding_provider=embedding_provider,
    )
    repository.setup()
    return repository
