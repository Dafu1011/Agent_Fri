from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from psycopg.types.json import Jsonb

from app.config import settings
from app.agent.multi_agent.state import MultiAgentState


@dataclass(frozen=True)
class LearningRecord:
    id: str
    user_id: str
    thread_id: str
    kind: str
    content: str
    created_at: str


class LearningRepository(Protocol):
    def save_from_state(self, state: MultiAgentState) -> LearningRecord | None:
        ...


class InMemoryLearningRepository:
    def __init__(self):
        self.records: list[LearningRecord] = []

    def save_from_state(self, state: MultiAgentState) -> LearningRecord | None:
        record = build_learning_record(state)
        if record is not None:
            self.records.append(record)
        return record


class PostgresLearningRepository:
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    @classmethod
    def from_conn_string(cls, database_url: str) -> "PostgresLearningRepository":
        def connect():
            import psycopg

            return psycopg.connect(database_url)

        return cls(connect)

    def setup(self) -> None:
        with self.connection_factory() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_learnings (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_learnings_user_created
                ON agent_learnings(user_id, created_at DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_learnings_kind
                ON agent_learnings(kind)
                """
            )

    def save_from_state(self, state: MultiAgentState) -> LearningRecord | None:
        record = build_learning_record(state)
        if record is None:
            return None
        metadata = {
            "task": state["task"],
            "plan": state.get("plan", []),
            "selected_tool_names": state.get("selected_tool_names", []),
            "worker_outputs": state.get("worker_outputs", []),
            "verification": state.get("verification", {}),
        }
        with self.connection_factory() as connection:
            connection.execute(
                """
                INSERT INTO agent_learnings (
                    id, user_id, thread_id, kind, content, metadata, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    record.id,
                    record.user_id,
                    record.thread_id,
                    record.kind,
                    record.content,
                    Jsonb(metadata),
                    record.created_at,
                ),
            )
        return record


def build_postgres_learning_repository() -> PostgresLearningRepository:
    repository = PostgresLearningRepository.from_conn_string(settings.database_url)
    repository.setup()
    return repository


def build_learning_record(state: MultiAgentState) -> LearningRecord | None:
    verification = state.get("verification", {})
    if not verification.get("passed"):
        return None
    plan = state.get("plan", [])
    outputs = state.get("worker_outputs", [])
    if not plan or not outputs:
        return None

    tool_names = []
    for step in plan:
        tool_names.extend(step.get("tool_names", []))
    unique_tool_names = list(dict.fromkeys(tool_names))
    content = (
        f"任务模式: {state['task']}\n"
        f"工具组合: {', '.join(unique_tool_names) or '无'}\n"
        f"成功标准: {verification.get('reason', '步骤完成并通过校验')}"
    )
    digest = hashlib.sha256(
        f"{state['user_id']}:{state['thread_id']}:{content}".encode("utf-8")
    ).hexdigest()
    return LearningRecord(
        id=f"learning-{digest[:24]}",
        user_id=state["user_id"],
        thread_id=state["thread_id"],
        kind="task_pattern",
        content=content,
        created_at=datetime.now(UTC).isoformat(),
    )
