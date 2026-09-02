from types import SimpleNamespace

from app.agent.memory import (
    MemoryRecord,
    PostgresMemoryRepository,
    StoreMemoryRepository,
    extract_memory_items,
    extract_memories,
)


class FakeStore:
    def __init__(self):
        self.items = {}
        self.deleted = []

    def put(self, namespace, key, value):
        self.items[(namespace, key)] = value

    def search(self, namespace, query=None, filter=None, limit=10):
        results = []
        for (item_namespace, key), value in self.items.items():
            if item_namespace != namespace:
                continue
            if filter and any(value.get(name) != expected for name, expected in filter.items()):
                continue
            results.append(
                SimpleNamespace(
                    key=key,
                    value=value,
                    created_at=value["created_at"],
                    updated_at=value["updated_at"],
                )
            )
        return results[:limit]

    def delete(self, namespace, key):
        self.deleted.append((namespace, key))
        self.items.pop((namespace, key), None)


def test_extract_memories_finds_basic_user_facts():
    memories = extract_memories("请记住我叫小明，我喜欢 LangGraph，以后用中文回答")

    assert "我叫小明" in memories
    assert "我喜欢 LangGraph" in memories
    assert "以后用中文回答" in memories


def test_extract_memory_items_creates_structured_records():
    items = extract_memory_items("请记住我叫小明，我喜欢 LangGraph，以后用中文回答")

    assert {
        "content": "我叫小明",
        "kind": "fact",
        "type": "identity",
        "title": "我叫小明",
        "facts": ["我叫小明"],
        "concepts": ["identity"],
    } in items
    assert {
        "content": "我喜欢 LangGraph",
        "kind": "fact",
        "type": "preference",
        "title": "我喜欢 LangGraph",
        "facts": ["我喜欢 LangGraph"],
        "concepts": ["preference"],
    } in items
    assert {
        "content": "以后用中文回答",
        "kind": "instruction",
        "type": "preference",
        "title": "以后用中文回答",
        "facts": ["以后用中文回答"],
        "concepts": ["preference"],
    } in items


def test_store_memory_repository_add_list_and_delete():
    store = FakeStore()
    repository = StoreMemoryRepository(store)

    memory = repository.add_memory(
        user_id="user-1",
        content="我喜欢 LangGraph",
        source_thread_id="thread-1",
    )

    assert memory.content == "我喜欢 LangGraph"
    assert memory.kind == "manual"
    assert memory.type == "note"
    assert memory.title == "我喜欢 LangGraph"
    assert memory.facts == ["我喜欢 LangGraph"]
    assert memory.concepts == ["manual"]
    assert repository.list_memories("user-1") == [memory]

    assert repository.delete_memory("user-1", memory.id) is True
    assert repository.list_memories("user-1") == []


def test_memory_record_from_store_item_reads_metadata():
    item = SimpleNamespace(
        key="memory-1",
        value={
            "content": "我叫小明",
            "source_thread_id": "thread-1",
            "kind": "fact",
            "type": "identity",
            "title": "用户身份",
            "facts": ["我叫小明"],
            "concepts": ["identity"],
            "created_at": "2026-09-01T10:00:00+00:00",
            "updated_at": "2026-09-01T10:00:00+00:00",
        },
    )

    record = MemoryRecord.from_store_item(item)

    assert record.id == "memory-1"
    assert record.content == "我叫小明"
    assert record.source_thread_id == "thread-1"
    assert record.kind == "fact"
    assert record.type == "identity"
    assert record.title == "用户身份"
    assert record.facts == ["我叫小明"]
    assert record.concepts == ["identity"]


def test_save_from_message_writes_structured_memory_items():
    store = FakeStore()
    repository = StoreMemoryRepository(store)

    records = repository.save_from_message(
        user_id="user-1",
        thread_id="thread-1",
        message="请记住我叫小明，我喜欢 LangGraph",
    )

    assert [record.type for record in records] == ["identity", "preference"]
    stored_values = [value for (_namespace, _key), value in store.items.items()]
    assert stored_values[0]["kind"] == "fact"
    assert stored_values[0]["facts"] == ["我叫小明"]
    assert stored_values[0]["concepts"] == ["identity"]


def test_search_memories_matches_structured_fields():
    store = FakeStore()
    repository = StoreMemoryRepository(store)
    repository.add_memory(
        user_id="user-1",
        content="以后用中文回答",
        source_thread_id="thread-1",
        kind="instruction",
        type="preference",
        title="语言偏好",
        facts=["以后用中文回答"],
        concepts=["language", "preference"],
    )

    assert repository.search_memories("user-1", query="language", limit=5) == [
        "语言偏好: 以后用中文回答"
    ]


def test_postgres_memory_repository_setup_creates_agent_memories_table():
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
    repository = PostgresMemoryRepository(lambda: connection)

    repository.setup()

    assert any("CREATE TABLE IF NOT EXISTS agent_memories" in stmt for stmt in connection.statements)
    assert any("CREATE INDEX IF NOT EXISTS idx_agent_memories_user_updated" in stmt for stmt in connection.statements)
