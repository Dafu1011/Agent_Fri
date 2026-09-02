from fastapi.testclient import TestClient

from app.main import app


def test_chat_endpoint_returns_model_reply(monkeypatch):
    async def fake_run_chat_graph(
        message: str,
        thread_id: str,
        user_id: str,
        graph=None,
        memory_repository=None,
    ) -> str:
        assert message == "\u4f60\u597d"
        assert thread_id == "thread-1"
        assert user_id == "user-1"
        return "\u4f60\u597d\uff0c\u6211\u662f\u6d4b\u8bd5\u56de\u590d\u3002"

    monkeypatch.setattr("app.api.chat.run_chat_graph", fake_run_chat_graph)

    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "user_id": "user-1",
            "thread_id": "thread-1",
            "message": "\u4f60\u597d",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"reply": "\u4f60\u597d\uff0c\u6211\u662f\u6d4b\u8bd5\u56de\u590d\u3002"}


def test_chat_endpoint_rejects_missing_thread_id():
    client = TestClient(app)
    response = client.post("/chat", json={"user_id": "user-1", "message": "hello"})

    assert response.status_code == 422


def test_chat_history_endpoint_returns_thread_messages(monkeypatch):
    async def fake_get_thread_messages(graph, thread_id: str):
        assert thread_id == "thread-1"
        assert graph is app.state.chat_graph
        return [
            {"role": "user", "content": "第一轮"},
            {"role": "assistant", "content": "收到第一轮"},
        ]

    monkeypatch.setattr("app.api.chat.get_thread_messages", fake_get_thread_messages)
    app.state.chat_graph = object()

    client = TestClient(app)
    response = client.get("/chat/thread-1")

    assert response.status_code == 200
    assert response.json() == {
        "messages": [
            {"role": "user", "text": "第一轮"},
            {"role": "assistant", "text": "收到第一轮"},
        ]
    }
