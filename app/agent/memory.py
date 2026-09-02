from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    content: str
    source_thread_id: str | None
    created_at: str
    updated_at: str
    kind: str = "manual"
    type: str = "note"
    title: str | None = None
    facts: list[str] | None = None
    concepts: list[str] | None = None

    @classmethod
    def from_store_item(cls, item: Any) -> "MemoryRecord":
        value = item.value
        content = value.get("content") or value.get("text") or value.get("narrative", "")
        return cls(
            id=item.key,
            content=content,
            source_thread_id=value.get("source_thread_id"),
            created_at=value["created_at"],
            updated_at=value["updated_at"],
            kind=value.get("kind", "manual"),
            type=value.get("type", "note"),
            title=value.get("title") or content,
            facts=value.get("facts", [content] if content else []),
            concepts=value.get("concepts", []),
        )


class MemoryRepository(Protocol):
    def list_memories(self, user_id: str, limit: int = 20) -> list[MemoryRecord]:
        ...

    def search_memories(self, user_id: str, query: str, limit: int = 5) -> list[str]:
        ...

    def add_memory(
        self,
        user_id: str,
        content: str,
        source_thread_id: str | None = None,
    ) -> MemoryRecord:
        ...

    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        ...

    def save_from_message(
        self,
        user_id: str,
        thread_id: str,
        message: str,
    ) -> list[MemoryRecord]:
        ...


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _memory_key(content: str) -> str:
    # Stable keys make repeated facts idempotent for the same user namespace.
    digest = hashlib.sha256(content.strip().lower().encode("utf-8")).hexdigest()
    return f"memory-{digest[:24]}"


def _clean_memory(text: str) -> str:
    text = text.strip(" ，。,.!！?？\n\t")
    return re.sub(r"\s+", " ", text)


def extract_memories(message: str) -> list[str]:
    """Extract simple user facts without using an LLM.

    This is deliberately conservative for a beginner project. Later you can
    replace this with an LLM extractor node that returns structured memories.
    """
    patterns = [
        r"(我叫[^，。,.!！?？\n]+)",
        r"(我是[^，。,.!！?？\n]+)",
        r"(我喜欢[^，。,.!！?？\n]+)",
        r"(我不喜欢[^，。,.!！?？\n]+)",
        r"(以后[^，。,.!！?？\n]+)",
        r"(请记住[^，。,.!！?？\n]+)",
    ]

    memories: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in re.findall(pattern, message):
            memory = _clean_memory(match)
            if memory and memory not in seen:
                memories.append(memory)
                seen.add(memory)
    return memories


def _classify_memory(content: str) -> tuple[str, str, list[str]]:
    if content.startswith(("我叫", "我是")):
        return "fact", "identity", ["identity"]
    if content.startswith(("我喜欢", "我不喜欢")):
        return "fact", "preference", ["preference"]
    if content.startswith(("以后", "请记住")):
        return "instruction", "preference", ["preference"]
    return "fact", "note", ["general"]


def extract_memory_items(message: str) -> list[dict[str, Any]]:
    """Extract claude-mem-style structured memory items from one user message."""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for content in extract_memories(message):
        content = content.removeprefix("请记住")
        content = _clean_memory(content)
        if not content or content in seen:
            continue
        seen.add(content)
        kind, memory_type, concepts = _classify_memory(content)
        items.append(
            {
                "content": content,
                "kind": kind,
                "type": memory_type,
                "title": content,
                "facts": [content],
                "concepts": concepts,
            }
        )
    return items


class StoreMemoryRepository:
    """Long-term memory wrapper around LangGraph PostgresStore."""

    def __init__(self, store: Any):
        self.store = store

    def _namespace(self, user_id: str) -> tuple[str, str]:
        # A namespace isolates one user's long-term facts from all other users.
        return ("memories", user_id)

    def list_memories(self, user_id: str, limit: int = 20) -> list[MemoryRecord]:
        items = self.store.search(self._namespace(user_id), limit=limit)
        return [MemoryRecord.from_store_item(item) for item in items]

    def search_memories(self, user_id: str, query: str, limit: int = 5) -> list[str]:
        # Without an embedding index this is recency-based retrieval. The API
        # shape is ready for pgvector semantic search once embeddings are added.
        memories = self.list_memories(user_id=user_id, limit=max(limit, 20))
        query_terms = [term for term in re.split(r"\s+", query.strip()) if term]

        def score(memory: MemoryRecord) -> int:
            searchable = " ".join(
                [
                    memory.content,
                    memory.title or "",
                    memory.kind,
                    memory.type,
                    " ".join(memory.facts or []),
                    " ".join(memory.concepts or []),
                ]
            )
            return sum(1 for term in query_terms if term in searchable)

        ranked = sorted(memories, key=score, reverse=True)
        return [self._format_memory(memory) for memory in ranked[:limit]]

    def _format_memory(self, memory: MemoryRecord) -> str:
        if memory.title and memory.title != memory.content:
            return f"{memory.title}: {memory.content}"
        return memory.content

    def add_memory(
        self,
        user_id: str,
        content: str,
        source_thread_id: str | None = None,
        kind: str = "manual",
        type: str = "note",
        title: str | None = None,
        facts: list[str] | None = None,
        concepts: list[str] | None = None,
    ) -> MemoryRecord:
        content = _clean_memory(content)
        memory_id = _memory_key(content)
        now = _utc_now()
        previous = self.store.search(
            self._namespace(user_id),
            filter={"content": content},
            limit=1,
        )
        created_at = previous[0].value["created_at"] if previous else now
        value = {
            "content": content,
            "source_thread_id": source_thread_id,
            "kind": kind,
            "type": type,
            "title": title or content,
            "facts": facts or [content],
            "concepts": concepts or [kind],
            "created_at": created_at,
            "updated_at": now,
        }
        self.store.put(self._namespace(user_id), memory_id, value)
        return MemoryRecord(
            id=memory_id,
            content=content,
            source_thread_id=source_thread_id,
            created_at=created_at,
            updated_at=now,
            kind=kind,
            type=type,
            title=title or content,
            facts=facts or [content],
            concepts=concepts or [kind],
        )

    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        memories = self.list_memories(user_id, limit=100)
        if not any(memory.id == memory_id for memory in memories):
            return False
        self.store.delete(self._namespace(user_id), memory_id)
        return True

    def save_from_message(
        self,
        user_id: str,
        thread_id: str,
        message: str,
    ) -> list[MemoryRecord]:
        return [
            self.add_memory(
                user_id,
                item["content"],
                source_thread_id=thread_id,
                kind=item["kind"],
                type=item["type"],
                title=item["title"],
                facts=item["facts"],
                concepts=item["concepts"],
            )
            for item in extract_memory_items(message)
        ]


class PostgresMemoryRepository:
    """Structured long-term memory stored in the app-owned agent_memories table."""

    def __init__(self, connection_factory: Any):
        self.connection_factory = connection_factory

    @classmethod
    def from_conn_string(cls, database_url: str) -> "PostgresMemoryRepository":
        def connect():
            import psycopg

            return psycopg.connect(database_url)

        return cls(connect)

    def setup(self) -> None:
        with self.connection_factory() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_memories (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    source_thread_id TEXT,
                    content TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'manual',
                    type TEXT NOT NULL DEFAULT 'note',
                    title TEXT,
                    facts JSONB NOT NULL DEFAULT '[]'::jsonb,
                    concepts JSONB NOT NULL DEFAULT '[]'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_memories_user_updated
                ON agent_memories(user_id, updated_at DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_memories_user_type
                ON agent_memories(user_id, type)
                """
            )

    def list_memories(self, user_id: str, limit: int = 20) -> list[MemoryRecord]:
        with self.connection_factory() as connection:
            rows = connection.execute(
                """
                SELECT id, content, source_thread_id, created_at, updated_at,
                       kind, type, title, facts, concepts
                FROM agent_memories
                WHERE user_id = %s
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            ).fetchall()
        return [self._record_from_row(row) for row in rows]

    def search_memories(self, user_id: str, query: str, limit: int = 5) -> list[str]:
        memories = self.list_memories(user_id=user_id, limit=max(limit, 20))
        query_terms = [term for term in re.split(r"\s+", query.strip()) if term]

        def score(memory: MemoryRecord) -> int:
            searchable = " ".join(
                [
                    memory.content,
                    memory.title or "",
                    memory.kind,
                    memory.type,
                    " ".join(memory.facts or []),
                    " ".join(memory.concepts or []),
                ]
            )
            return sum(1 for term in query_terms if term in searchable)

        ranked = sorted(memories, key=score, reverse=True)
        return [self._format_memory(memory) for memory in ranked[:limit]]

    def add_memory(
        self,
        user_id: str,
        content: str,
        source_thread_id: str | None = None,
        kind: str = "manual",
        type: str = "note",
        title: str | None = None,
        facts: list[str] | None = None,
        concepts: list[str] | None = None,
    ) -> MemoryRecord:
        from psycopg.types.json import Jsonb

        content = _clean_memory(content)
        memory_id = _memory_key(content)
        now = _utc_now()
        facts = facts or [content]
        concepts = concepts or [kind]
        title = title or content

        with self.connection_factory() as connection:
            previous = connection.execute(
                """
                SELECT created_at
                FROM agent_memories
                WHERE user_id = %s AND content = %s
                LIMIT 1
                """,
                (user_id, content),
            ).fetchone()
            created_at = str(previous[0]) if previous else now
            connection.execute(
                """
                INSERT INTO agent_memories (
                    id, user_id, source_thread_id, content, kind, type, title,
                    facts, concepts, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    source_thread_id = EXCLUDED.source_thread_id,
                    content = EXCLUDED.content,
                    kind = EXCLUDED.kind,
                    type = EXCLUDED.type,
                    title = EXCLUDED.title,
                    facts = EXCLUDED.facts,
                    concepts = EXCLUDED.concepts,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    memory_id,
                    user_id,
                    source_thread_id,
                    content,
                    kind,
                    type,
                    title,
                    Jsonb(facts),
                    Jsonb(concepts),
                    created_at,
                    now,
                ),
            )

        return MemoryRecord(
            id=memory_id,
            content=content,
            source_thread_id=source_thread_id,
            created_at=created_at,
            updated_at=now,
            kind=kind,
            type=type,
            title=title,
            facts=facts,
            concepts=concepts,
        )

    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        with self.connection_factory() as connection:
            deleted = connection.execute(
                """
                DELETE FROM agent_memories
                WHERE user_id = %s AND id = %s
                RETURNING id
                """,
                (user_id, memory_id),
            ).fetchone()
        return deleted is not None

    def save_from_message(
        self,
        user_id: str,
        thread_id: str,
        message: str,
    ) -> list[MemoryRecord]:
        return [
            self.add_memory(
                user_id,
                item["content"],
                source_thread_id=thread_id,
                kind=item["kind"],
                type=item["type"],
                title=item["title"],
                facts=item["facts"],
                concepts=item["concepts"],
            )
            for item in extract_memory_items(message)
        ]

    def _format_memory(self, memory: MemoryRecord) -> str:
        if memory.title and memory.title != memory.content:
            return f"{memory.title}: {memory.content}"
        return memory.content

    def _record_from_row(self, row: Any) -> MemoryRecord:
        return MemoryRecord(
            id=row[0],
            content=row[1],
            source_thread_id=row[2],
            created_at=str(row[3]),
            updated_at=str(row[4]),
            kind=row[5],
            type=row[6],
            title=row[7],
            facts=list(row[8] or []),
            concepts=list(row[9] or []),
        )
