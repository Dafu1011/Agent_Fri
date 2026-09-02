from app.agent.chat import build_model_messages


def test_build_model_messages_keeps_history_and_adds_system_message():
    messages = build_model_messages(
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "remember this"},
        ]
    )

    assert messages[0][0] == "system"
    assert "Chinese-language AI assistant" in messages[0][1]
    assert messages[1:] == [
        ("human", "hello"),
        ("assistant", "hi"),
        ("human", "remember this"),
    ]


def test_build_model_messages_includes_long_term_memories():
    messages = build_model_messages(
        [{"role": "user", "content": "我是谁？"}],
        memories=["我叫小明", "我喜欢 LangGraph"],
    )

    assert "Known long-term memories about this user" in messages[0][1]
    assert "- 我叫小明" in messages[0][1]
    assert "- 我喜欢 LangGraph" in messages[0][1]


def test_build_model_messages_includes_knowledge_context():
    messages = build_model_messages(
        [{"role": "user", "content": "项目怎么部署？"}],
        knowledge=["部署文档: 使用 Docker Compose 启动 postgres"],
    )

    assert "Relevant knowledge base context" in messages[0][1]
    assert "- 部署文档: 使用 Docker Compose 启动 postgres" in messages[0][1]
