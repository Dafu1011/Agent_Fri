from fastapi.testclient import TestClient

from app.agent.memory import MemoryRecord
from app.main import app


class FakeMemoryRepository:
    def __init__(self):
        self.memories = [
            MemoryRecord(
                id="memory-1",
                content="我喜欢 LangGraph",
                source_thread_id="thread-1",
                created_at="2026-09-01T10:00:00+00:00",
                updated_at="2026-09-01T10:00:00+00:00",
                kind="fact",
                type="preference",
                title="技术偏好",
                facts=["我喜欢 LangGraph"],
                concepts=["preference", "technology"],
            )
        ]

    def list_memories(self, user_id: str, limit: int = 20):
        assert user_id == "user-1"
        return self.memories[:limit]

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
    ):
        assert user_id == "user-1"
        memory = MemoryRecord(
            id="memory-2",
            content=content,
            source_thread_id=source_thread_id,
            created_at="2026-09-01T11:00:00+00:00",
            updated_at="2026-09-01T11:00:00+00:00",
            kind=kind,
            type=type,
            title=title or content,
            facts=facts or [content],
            concepts=concepts or [kind],
        )
        self.memories.append(memory)
        return memory

    def delete_memory(self, user_id: str, memory_id: str):
        assert user_id == "user-1"
        assert memory_id == "memory-1"
        return True


def test_memory_management_endpoints(monkeypatch):
    repository = FakeMemoryRepository()
    monkeypatch.setattr("app.api.memory.get_memory_repository", lambda request: repository)

    client = TestClient(app)

    list_response = client.get("/memories", params={"user_id": "user-1"})
    assert list_response.status_code == 200
    assert list_response.json()["memories"][0]["content"] == "我喜欢 LangGraph"
    assert list_response.json()["memories"][0]["type"] == "preference"
    assert list_response.json()["memories"][0]["title"] == "技术偏好"
    assert list_response.json()["memories"][0]["facts"] == ["我喜欢 LangGraph"]
    assert list_response.json()["memories"][0]["concepts"] == ["preference", "technology"]

    create_response = client.post(
        "/memories",
        json={
            "user_id": "user-1",
            "content": "我叫小明",
            "source_thread_id": "thread-1",
            "kind": "fact",
            "type": "identity",
            "title": "用户身份",
            "facts": ["我叫小明"],
            "concepts": ["identity"],
        },
    )
    assert create_response.status_code == 200
    assert create_response.json()["content"] == "我叫小明"
    assert create_response.json()["type"] == "identity"
    assert create_response.json()["title"] == "用户身份"

    delete_response = client.delete(
        "/memories/memory-1",
        params={"user_id": "user-1"},
    )
    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted": True}
