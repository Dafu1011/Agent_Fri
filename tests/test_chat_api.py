from fastapi.testclient import TestClient

from app.main import app


def test_chat_endpoint_returns_model_reply(monkeypatch):
    monkeypatch.setattr("app.api.chat.get_current_user_id", lambda request: "user-1")
    monkeypatch.setattr(
        "app.api.chat.get_auth_repository",
        lambda request: type(
            "Repo",
            (),
            {"thread_belongs_to_user": lambda self, thread_id, user_id: True},
        )(),
    )

    async def fake_run_chat_graph(
        message: str,
        thread_id: str,
        user_id: str,
        graph=None,
        memory_repository=None,
        knowledge_repository=None,
        tools=None,
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
            "thread_id": "thread-1",
            "message": "\u4f60\u597d",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "reply": "\u4f60\u597d\uff0c\u6211\u662f\u6d4b\u8bd5\u56de\u590d\u3002",
        "attachments": [],
    }


def test_chat_endpoint_adds_user_document_tools_to_model_tools(monkeypatch):
    monkeypatch.setattr("app.api.chat.get_current_user_id", lambda request: "user-1")
    monkeypatch.setattr(
        "app.api.chat.get_auth_repository",
        lambda request: type(
            "Repo",
            (),
            {"thread_belongs_to_user": lambda self, thread_id, user_id: True},
        )(),
    )

    async def fake_parse_document_message(*args, **kwargs):
        return None

    async def fake_parse_media_message(*args, **kwargs):
        return None

    async def fake_parse_image_generation_message(*args, **kwargs):
        return None

    async def fake_run_chat_graph(
        message,
        thread_id,
        user_id,
        graph=None,
        memory_repository=None,
        knowledge_repository=None,
        tools=None,
    ):
        assert tools == ["base-tool", "document-tool", "image-tool"]
        return "模型回复"

    def fake_build_document_tools(user_id, service):
        assert user_id == "user-1"
        assert service is app.state.document_conversion_service
        return ["document-tool"]

    def fake_build_image_generation_tools(user_id, service):
        assert user_id == "user-1"
        assert service is app.state.image_generation_service
        return ["image-tool"]

    app.state.agent_tools = ["base-tool"]
    app.state.document_conversion_service = object()
    app.state.image_generation_service = object()
    app.state.image_generation_job_store = object()
    monkeypatch.setattr("app.api.chat.parse_document_message", fake_parse_document_message)
    monkeypatch.setattr("app.api.chat.parse_media_message", fake_parse_media_message)
    monkeypatch.setattr("app.api.chat.parse_image_generation_message", fake_parse_image_generation_message, raising=False)
    monkeypatch.setattr("app.api.chat.run_chat_graph", fake_run_chat_graph)
    monkeypatch.setattr("app.api.chat.build_document_tools", fake_build_document_tools, raising=False)
    monkeypatch.setattr("app.api.chat.build_image_generation_tools", fake_build_image_generation_tools, raising=False)

    client = TestClient(app)
    response = client.post(
        "/chat",
        json={"thread_id": "thread-1", "message": "你好"},
    )

    assert response.status_code == 200
    assert response.json() == {"reply": "模型回复", "attachments": []}


def test_chat_endpoint_returns_media_attachment_for_parse_request(monkeypatch):
    monkeypatch.setattr("app.api.chat.get_current_user_id", lambda request: "user-1")
    monkeypatch.setattr(
        "app.api.chat.get_auth_repository",
        lambda request: type(
            "Repo",
            (),
            {"thread_belongs_to_user": lambda self, thread_id, user_id: True},
        )(),
    )

    async def fake_parse_media_message(message: str):
        assert message == "https://v.douyin.com/demo/ 解析"
        return {
            "reply": "已解析到抖音视频：城市夜景",
            "attachments": [
                {
                    "platform": "douyin",
                    "media_type": "video",
                    "title": "城市夜景",
                    "author": "摄影师",
                    "cover": "https://example.com/cover.jpg",
                    "video_url": "/media/preview/parse-123",
                    "source_url": "https://example.com/video.mp4",
                    "images": [],
                    "source_images": [],
                    "parse_id": "parse-123",
                }
            ],
        }

    async def fail_run_chat_graph(*args, **kwargs):
        raise AssertionError("model graph should not run for direct media parse requests")

    monkeypatch.setattr("app.api.chat.parse_media_message", fake_parse_media_message)
    monkeypatch.setattr("app.api.chat.run_chat_graph", fail_run_chat_graph)

    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "thread_id": "thread-1",
            "message": "https://v.douyin.com/demo/ 解析",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "reply": "已解析到抖音视频：城市夜景",
        "attachments": [
            {
                "platform": "douyin",
                "media_type": "video",
                "title": "城市夜景",
                "author": "摄影师",
                "cover": "https://example.com/cover.jpg",
                "video_url": "/media/preview/parse-123",
                "source_url": "https://example.com/video.mp4",
                "images": [],
                "source_images": [],
                "parse_id": "parse-123",
            }
        ],
    }


def test_chat_endpoint_returns_document_attachment_for_file_conversion(monkeypatch):
    monkeypatch.setattr("app.api.chat.get_current_user_id", lambda request: "user-1")
    monkeypatch.setattr(
        "app.api.chat.get_auth_repository",
        lambda request: type(
            "Repo",
            (),
            {"thread_belongs_to_user": lambda self, thread_id, user_id: True},
        )(),
    )

    async def fake_parse_document_message(message, file_ids, user_id, service):
        assert message == "转成 PDF"
        assert file_ids == ["file-1"]
        assert user_id == "user-1"
        assert service is app.state.document_conversion_service
        return {
            "reply": "已转换为 PDF。",
            "attachments": [
                {
                    "platform": "document",
                    "media_type": "file",
                    "title": "receipt.pdf",
                    "file_id": "file-2",
                    "filename": "receipt.pdf",
                    "mime_type": "application/pdf",
                    "download_url": "/documents/files/file-2/download",
                    "preview_url": "/documents/files/file-2/download",
                    "size_bytes": 1200,
                    "status": "ready",
                    "message": "已转换为 PDF。",
                    "operation": "images_to_pdf",
                }
            ],
        }

    async def fail_parse_media_message(*args, **kwargs):
        raise AssertionError("media parser should not run for uploaded file conversions")

    async def fail_run_chat_graph(*args, **kwargs):
        raise AssertionError("model graph should not run for direct document conversions")

    app.state.document_conversion_service = object()
    monkeypatch.setattr("app.api.chat.parse_document_message", fake_parse_document_message, raising=False)
    monkeypatch.setattr("app.api.chat.parse_media_message", fail_parse_media_message)
    monkeypatch.setattr("app.api.chat.run_chat_graph", fail_run_chat_graph)

    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "thread_id": "thread-1",
            "message": "转成 PDF",
            "file_ids": ["file-1"],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "reply": "已转换为 PDF。",
        "attachments": [
            {
                "platform": "document",
                "media_type": "file",
                "title": "receipt.pdf",
                "file_id": "file-2",
                "filename": "receipt.pdf",
                "mime_type": "application/pdf",
                "download_url": "/documents/files/file-2/download",
                "preview_url": "/documents/files/file-2/download",
                "size_bytes": 1200,
                "status": "ready",
                "message": "已转换为 PDF。",
                "operation": "images_to_pdf",
            }
        ],
    }


def test_chat_endpoint_returns_image_generation_job_for_direct_request(monkeypatch):
    monkeypatch.setattr("app.api.chat.get_current_user_id", lambda request: "user-1")
    monkeypatch.setattr(
        "app.api.chat.get_auth_repository",
        lambda request: type(
            "Repo",
            (),
            {"thread_belongs_to_user": lambda self, thread_id, user_id: True},
        )(),
    )

    async def fake_parse_document_message(*args, **kwargs):
        return None

    async def fake_parse_media_message(*args, **kwargs):
        return None

    async def fake_parse_image_generation_message(message, user_id, job_store):
        assert message == "帮我生成一张猫咖海报"
        assert user_id == "user-1"
        assert job_store is app.state.image_generation_job_store
        return {
            "reply": "已开始生成图片，我会在完成后展示。",
            "attachments": [
                {
                    "platform": "image-generation",
                    "media_type": "image_generation_job",
                    "job_id": "imgjob-1",
                    "status": "queued",
                    "poll_url": "/images/jobs/imgjob-1",
                    "prompt": "帮我生成一张猫咖海报",
                }
            ],
        }

    async def fail_run_chat_graph(*args, **kwargs):
        raise AssertionError("model graph should not run for direct image generation requests")

    app.state.image_generation_job_store = object()
    monkeypatch.setattr("app.api.chat.parse_document_message", fake_parse_document_message, raising=False)
    monkeypatch.setattr("app.api.chat.parse_media_message", fake_parse_media_message)
    monkeypatch.setattr("app.api.chat.parse_image_generation_message", fake_parse_image_generation_message, raising=False)
    monkeypatch.setattr("app.api.chat.run_chat_graph", fail_run_chat_graph)

    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "thread_id": "thread-1",
            "message": "帮我生成一张猫咖海报",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "reply": "已开始生成图片，我会在完成后展示。",
        "attachments": [
            {
                "platform": "image-generation",
                "media_type": "image_generation_job",
                "job_id": "imgjob-1",
                "status": "queued",
                "poll_url": "/images/jobs/imgjob-1",
                "prompt": "帮我生成一张猫咖海报",
            }
        ],
    }


def test_chat_endpoint_rejects_missing_thread_id():
    client = TestClient(app)
    response = client.post("/chat", json={"message": "hello"})

    assert response.status_code == 422


def test_chat_endpoint_returns_clear_error_when_model_is_not_configured(monkeypatch):
    monkeypatch.setattr("app.api.chat.get_current_user_id", lambda request: "user-1")
    monkeypatch.setattr(
        "app.api.chat.get_auth_repository",
        lambda request: type(
            "Repo",
            (),
            {"thread_belongs_to_user": lambda self, thread_id, user_id: True},
        )(),
    )
    async def fake_parse_media_message(message: str):
        return None

    monkeypatch.setattr("app.api.chat.parse_media_message", fake_parse_media_message)

    async def fake_run_chat_graph(*args, **kwargs):
        raise RuntimeError("OPENAI_API_KEY is not configured")

    monkeypatch.setattr("app.api.chat.run_chat_graph", fake_run_chat_graph)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/chat",
        json={"thread_id": "thread-1", "message": "hello"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "模型服务未配置：请设置 OPENAI_API_KEY 后重启服务。"}


def test_chat_endpoint_rejects_thread_owned_by_another_user(monkeypatch):
    monkeypatch.setattr("app.api.chat.get_current_user_id", lambda request: "user-1")
    monkeypatch.setattr(
        "app.api.chat.get_auth_repository",
        lambda request: type(
            "Repo",
            (),
            {"thread_belongs_to_user": lambda self, thread_id, user_id: False},
        )(),
    )

    client = TestClient(app)
    response = client.post(
        "/chat",
        json={"thread_id": "thread-2", "message": "hello"},
    )

    assert response.status_code == 404


def test_chat_history_endpoint_returns_thread_messages(monkeypatch):
    monkeypatch.setattr("app.api.chat.get_current_user_id", lambda request: "user-1")
    monkeypatch.setattr(
        "app.api.chat.get_auth_repository",
        lambda request: type(
            "Repo",
            (),
            {"thread_belongs_to_user": lambda self, thread_id, user_id: True},
        )(),
    )

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
            {"role": "user", "text": "第一轮", "attachments": []},
            {"role": "assistant", "text": "收到第一轮", "attachments": []},
        ]
    }
