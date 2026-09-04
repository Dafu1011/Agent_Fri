from fastapi.testclient import TestClient

from app.main import app


def test_status_endpoint_reports_persistence_and_tool_names(monkeypatch):
    monkeypatch.setattr("app.main.settings.searxng_base_url", "http://localhost:8080")
    app.state.persistence_status = "postgres"
    app.state.checkpointer_status = "postgres"
    app.state.memory_status = "postgres"
    app.state.knowledge_status = "postgres"
    app.state.startup_errors = {}
    app.state.agent_tools = [
        type("Tool", (), {"name": "web_search"})(),
    ]

    client = TestClient(app)
    response = client.get("/status")

    assert response.status_code == 200
    assert response.json() == {
        "persistence": "postgres",
        "checkpointer": "postgres",
        "memory": "postgres",
        "knowledge": "postgres",
        "tools": ["web_search"],
        "searxng_configured": True,
        "startup_errors": {},
    }


def test_status_endpoint_does_not_call_memory_only_graph_persistence_postgres(monkeypatch):
    monkeypatch.setattr("app.main.settings.searxng_base_url", "")
    app.state.persistence_status = "disabled"
    app.state.checkpointer_status = "disabled"
    app.state.memory_status = "postgres"
    app.state.knowledge_status = "disabled"
    app.state.agent_tools = []
    app.state.startup_errors = {
        "checkpointer": "connection failed",
    }

    client = TestClient(app)
    response = client.get("/status")

    assert response.status_code == 200
    assert response.json()["persistence"] == "disabled"
    assert response.json()["checkpointer"] == "disabled"
    assert response.json()["memory"] == "postgres"
    assert response.json()["startup_errors"] == {
        "checkpointer": "connection failed",
    }


def test_status_endpoint_reports_in_memory_checkpointer_fallback(monkeypatch):
    monkeypatch.setattr("app.main.settings.searxng_base_url", "http://localhost:8080")
    app.state.persistence_status = "memory"
    app.state.checkpointer_status = "memory"
    app.state.memory_status = "postgres"
    app.state.knowledge_status = "postgres"
    app.state.agent_tools = []
    app.state.startup_errors = {
        "checkpointer": "No module named 'langgraph.checkpoint.postgres'",
    }

    client = TestClient(app)
    response = client.get("/status")

    assert response.status_code == 200
    assert response.json()["persistence"] == "memory"
    assert response.json()["checkpointer"] == "memory"
    assert response.json()["memory"] == "postgres"
