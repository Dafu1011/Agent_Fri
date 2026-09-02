from fastapi.testclient import TestClient

from app.main import app


def test_root_serves_landing_chat_page():
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert '<div id="root"></div>' in response.text
    assert 'data-testid="chat-panel"' in response.text
    assert 'fetch("/chat"' in response.text
    assert "thread_id: threadId" in response.text
    assert "user_id: userId" not in response.text
    assert '"Authorization": `Bearer ${token}`' in response.text
    assert 'fetch(`/chat/${threadId}`' in response.text
    assert 'fetch(authMode === "login" ? "/auth/login" : "/auth/register"' in response.text
    assert "window.Motion = window.Motion || window.FramerMotion" in response.text


def test_hero_centers_chat_without_marketing_copy():
    client = TestClient(app)
    response = client.get("/")

    assert "hero-chat-center" in response.text
    assert "Venture Past Our Sky Across the Universe" not in response.text
    assert "Maiden Crewed Voyage to Mars Arrives 2026" not in response.text
    assert "Start Your Voyage" not in response.text
    assert "Average Videos Watch Time" not in response.text
    assert "Collaborating with top aerospace pioneers globally" not in response.text
