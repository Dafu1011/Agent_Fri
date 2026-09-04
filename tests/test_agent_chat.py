from app.agent.chat import build_model_messages
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


def test_build_model_messages_keeps_history_and_adds_system_message():
    messages = build_model_messages(
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "remember this"},
        ]
    )

    assert isinstance(messages[0], SystemMessage)
    assert "Chinese-language AI assistant" in messages[0].content
    assert messages[1:] == [
        HumanMessage(content="hello"),
        AIMessage(content="hi"),
        HumanMessage(content="remember this"),
    ]


def test_build_model_messages_tells_model_to_use_tools_for_realtime_questions():
    messages = build_model_messages([{"role": "user", "content": "今天长春天气怎么样？"}])

    assert "Use available tools for real-time information" in messages[0].content
    assert "weather" in messages[0].content


def test_build_model_messages_accepts_langchain_messages():
    messages = build_model_messages(
        [
            HumanMessage(content="hello"),
            AIMessage(content="hi"),
        ]
    )

    assert isinstance(messages[0], SystemMessage)
    assert messages[1:] == [
        HumanMessage(content="hello"),
        AIMessage(content="hi"),
    ]


def test_build_model_messages_includes_long_term_memories():
    messages = build_model_messages(
        [{"role": "user", "content": "我是谁？"}],
        memories=["我叫小明", "我喜欢 LangGraph"],
    )

    assert "Known long-term memories about this user" in messages[0].content
    assert "- 我叫小明" in messages[0].content
    assert "- 我喜欢 LangGraph" in messages[0].content


def test_build_model_messages_includes_knowledge_context():
    messages = build_model_messages(
        [{"role": "user", "content": "项目怎么部署？"}],
        knowledge=["部署文档: 使用 Docker Compose 启动 postgres"],
    )

    assert "Relevant knowledge base context" in messages[0].content
    assert "- 部署文档: 使用 Docker Compose 启动 postgres" in messages[0].content
