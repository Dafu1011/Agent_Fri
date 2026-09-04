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
    assert "<Capabilities />" not in response.text
    assert "function Capabilities()" not in response.text
    assert "#capabilities" not in response.text
    assert "Production<br />evolved" not in response.text
    assert "Venture Past Our Sky Across the Universe" not in response.text
    assert "Maiden Crewed Voyage to Mars Arrives 2026" not in response.text
    assert "Start Your Voyage" not in response.text
    assert "Average Videos Watch Time" not in response.text
    assert "Collaborating with top aerospace pioneers globally" not in response.text


def test_chat_messages_render_markdown_safely_and_scroll_responsively():
    client = TestClient(app)
    response = client.get("/")

    assert "marked.min.js" in response.text
    assert "purify.min.js" in response.text
    assert "function MessageContent({ text })" in response.text
    assert "DOMPurify.sanitize(marked.parse(text || \"\"))" in response.text
    assert "<MessageContent text={message.text} />" in response.text
    assert "message-markdown" in response.text
    assert "h-[calc(100dvh-2rem)]" in response.text
    assert "max-h-[calc(100dvh-2rem)]" in response.text
    assert "flex-1 min-h-0 flex-col gap-3 overflow-y-auto" in response.text
    assert "shrink-0 max-w-[86%] rounded-[1.1rem]" in response.text
    assert "scrollbar-gutter: stable" in response.text
    assert "max-h-[52vh]" not in response.text
    assert "h-[520px]" not in response.text
    assert "prefers-reduced-motion: reduce" in response.text


def test_chat_request_errors_display_backend_detail():
    client = TestClient(app)
    response = client.get("/")

    assert "async function readErrorMessage(response)" in response.text
    assert "data.detail || data.error || `Chat request failed: ${response.status}`" in response.text
    assert "setError(message)" in response.text
    assert "Transmission failed. Check the FastAPI server and model gateway." not in response.text


def test_chat_messages_render_media_attachments():
    client = TestClient(app)
    response = client.get("/")

    assert "function MediaAttachments({ attachments })" in response.text
    assert "<MediaAttachments attachments={message.attachments} />" in response.text
    assert "<video controls" in response.text
    assert "attachment.media_type === \"image_gallery\"" in response.text
    assert "<PhotoStack images={attachment.images} title={attachment.title} sourceImages={attachment.source_images} />" in response.text
    assert "data.attachments || []" in response.text
    assert "function MediaVideo({ attachment })" in response.text
    assert "onError={() => setFailed(true)}" in response.text
    assert "attachment.source_url" in response.text


def test_image_gallery_uses_stacked_cards_interaction():
    client = TestClient(app)
    response = client.get("/")

    assert "function PhotoStack({ images, title, sourceImages })" in response.text
    assert "visibleCards" in response.text
    assert "Math.min(3, images.length)" in response.text
    assert "onPointerDown" in response.text
    assert "onPointerMove" in response.text
    assert "onPointerUp" in response.text
    assert "dragVelocity" in response.text
    assert "peakOffset" in response.text
    assert "dragProgress" in response.text
    assert "isDragging" in response.text
    assert "interpolateCardPose" in response.text
    assert "stackDirection" in response.text
    assert "transitionClass" in response.text
    assert "openImageLink" in response.text
    assert "<a key={`${src}-${layer}`}" not in response.text
    assert "<PhotoStack images={attachment.images} title={attachment.title} sourceImages={attachment.source_images} />" in response.text
