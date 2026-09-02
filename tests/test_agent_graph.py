import pytest
import inspect

from app.agent.graph import (
    build_postgres_checkpointer,
    create_thread_config,
    ensure_async_postgres_event_loop_policy,
    get_thread_messages,
    run_chat_graph,
)


def test_create_thread_config_uses_langgraph_thread_id():
    assert create_thread_config("thread-1") == {
        "configurable": {"thread_id": "thread-1"}
    }


def test_postgres_checkpointer_builder_is_async_for_ainvoke():
    assert inspect.iscoroutinefunction(build_postgres_checkpointer)


def test_windows_selector_policy_helper_is_available_for_async_psycopg():
    assert callable(ensure_async_postgres_event_loop_policy)


@pytest.mark.anyio
async def test_run_chat_graph_returns_reply_from_message_history(monkeypatch):
    async def fake_generate_reply(messages: list[dict[str, str]], memories=None) -> str:
        assert messages[-1] == {"role": "user", "content": "hello"}
        return "hi from graph"

    monkeypatch.setattr("app.agent.graph.generate_reply", fake_generate_reply)

    reply = await run_chat_graph("hello", thread_id="thread-1", user_id="user-1")

    assert reply == "hi from graph"


@pytest.mark.anyio
async def test_run_chat_graph_loads_and_saves_long_term_memory(monkeypatch):
    class FakeMemoryRepository:
        def __init__(self):
            self.saved = []

        def search_memories(self, user_id: str, query: str, limit: int = 5):
            assert user_id == "user-1"
            assert query == "请记住我叫小明"
            return ["我喜欢 LangGraph"]

        def save_from_message(self, user_id: str, thread_id: str, message: str):
            self.saved.append((user_id, thread_id, message))
            return []

    repository = FakeMemoryRepository()

    async def fake_generate_reply(messages: list[dict[str, str]], memories=None) -> str:
        assert memories == ["我喜欢 LangGraph"]
        assert messages[-1] == {"role": "user", "content": "请记住我叫小明"}
        return "我记住了。"

    monkeypatch.setattr("app.agent.graph.generate_reply", fake_generate_reply)

    reply = await run_chat_graph(
        "请记住我叫小明",
        thread_id="thread-1",
        user_id="user-1",
        memory_repository=repository,
    )

    assert reply == "我记住了。"
    assert repository.saved == [("user-1", "thread-1", "请记住我叫小明")]


@pytest.mark.anyio
async def test_get_thread_messages_reads_checkpointed_history():
    class FakeState:
        values = {
            "messages": [
                {"role": "user", "content": "第一轮"},
                {"role": "assistant", "content": "收到第一轮"},
            ]
        }

    class FakeGraph:
        async def aget_state(self, config):
            assert config == {"configurable": {"thread_id": "thread-1"}}
            return FakeState()

    messages = await get_thread_messages(FakeGraph(), thread_id="thread-1")

    assert messages == [
        {"role": "user", "content": "第一轮"},
        {"role": "assistant", "content": "收到第一轮"},
    ]
