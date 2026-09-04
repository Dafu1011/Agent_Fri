import pytest
import inspect
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.graph import (
    build_chat_graph,
    build_postgres_checkpointer,
    create_thread_config,
    ensure_async_postgres_event_loop_policy,
    get_thread_messages,
    run_chat_graph,
)


@tool
def echo_tool(text: str) -> str:
    """Echo text for graph tool-loop tests."""
    return f"echo:{text}"


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
    async def fake_generate_reply(
        messages: list[HumanMessage],
        memories=None,
        knowledge=None,
    ) -> str:
        assert isinstance(messages[-1], HumanMessage)
        assert messages[-1].content == "hello"
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

    async def fake_generate_reply(
        messages: list[HumanMessage],
        memories=None,
        knowledge=None,
    ) -> str:
        assert memories == ["我喜欢 LangGraph"]
        assert isinstance(messages[-1], HumanMessage)
        assert messages[-1].content == "请记住我叫小明"
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
async def test_run_chat_graph_loads_knowledge_context(monkeypatch):
    class FakeKnowledgeRepository:
        def search(self, user_id: str, query: str, limit: int = 5):
            assert user_id == "user-1"
            assert query == "怎么回答用户？"
            return ["项目规范: 回答要简洁"]

    async def fake_generate_reply(
        messages: list[dict[str, str]],
        memories=None,
        knowledge=None,
    ) -> str:
        assert memories == []
        assert knowledge == ["项目规范: 回答要简洁"]
        return "按规范简洁回答。"

    monkeypatch.setattr("app.agent.graph.generate_reply", fake_generate_reply)

    reply = await run_chat_graph(
        "怎么回答用户？",
        thread_id="thread-1",
        user_id="user-1",
        knowledge_repository=FakeKnowledgeRepository(),
    )

    assert reply == "按规范简洁回答。"


@pytest.mark.anyio
async def test_run_chat_graph_executes_tool_calls_and_returns_final_reply(monkeypatch):
    model_calls = []

    async def fake_generate_model_message(
        messages,
        memories=None,
        knowledge=None,
        tools=None,
    ):
        model_calls.append(messages)
        if len(model_calls) == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "echo_tool",
                        "args": {"text": "hello"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            )
        assert isinstance(messages[-1], ToolMessage)
        assert messages[-1].content == "echo:hello"
        return AIMessage(content="工具返回 echo:hello")

    monkeypatch.setattr(
        "app.agent.graph.generate_model_message",
        fake_generate_model_message,
    )

    reply = await run_chat_graph(
        "调用工具",
        thread_id="thread-1",
        user_id="user-1",
        tools=[echo_tool],
    )

    assert reply == "工具返回 echo:hello"
    assert len(model_calls) == 2


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


@pytest.mark.anyio
async def test_get_thread_messages_maps_langchain_ai_messages_to_assistant():
    class FakeState:
        values = {
            "messages": [
                HumanMessage(content="第一轮"),
                AIMessage(content="收到第一轮"),
            ]
        }

    class FakeGraph:
        async def aget_state(self, config):
            return FakeState()

    messages = await get_thread_messages(FakeGraph(), thread_id="thread-1")

    assert messages == [
        {"role": "user", "content": "第一轮"},
        {"role": "assistant", "content": "收到第一轮"},
    ]


@pytest.mark.anyio
async def test_run_chat_graph_preserves_history_with_checkpointer(monkeypatch):
    seen_messages = []

    async def fake_generate_reply(
        messages,
        memories=None,
        knowledge=None,
    ) -> str:
        seen_messages.append([message.content for message in messages])
        if len(seen_messages) == 1:
            return "你在哪个城市？"
        return "今天吉林省长春市南关区天气情况如下。"

    monkeypatch.setattr("app.agent.graph.generate_reply", fake_generate_reply)
    graph = build_chat_graph(checkpointer=InMemorySaver())

    first_reply = await run_chat_graph(
        "今天天气怎么样",
        thread_id="thread-weather",
        user_id="user-1",
        graph=graph,
    )
    second_reply = await run_chat_graph(
        "吉林省长春市南关区",
        thread_id="thread-weather",
        user_id="user-1",
        graph=graph,
    )

    assert first_reply == "你在哪个城市？"
    assert second_reply == "今天吉林省长春市南关区天气情况如下。"
    assert seen_messages[1] == [
        "今天天气怎么样",
        "你在哪个城市？",
        "吉林省长春市南关区",
    ]


@pytest.mark.anyio
async def test_get_thread_messages_returns_empty_when_graph_has_no_checkpointer():
    class FakeGraph:
        async def aget_state(self, config):
            raise ValueError("No checkpointer set")

    assert await get_thread_messages(FakeGraph(), thread_id="thread-1") == []
