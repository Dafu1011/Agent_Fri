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
    class FakeStoredFile:
        file_id = "file-1"
        filename = "receipt.png"
        mime_type = "image/png"
        size_bytes = 1200

    class FakeStorage:
        def get_file(self, user_id, file_id):
            assert user_id == "user-1"
            assert file_id == "file-1"
            return FakeStoredFile()

    class FakeDocumentService:
        storage = FakeStorage()

    app.state.document_conversion_service = FakeDocumentService()
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


def test_chat_endpoint_passes_uploaded_images_to_simple_chat_graph(monkeypatch, tmp_path):
    image_path = tmp_path / "prompt.png"
    image_path.write_bytes(b"fake-png-bytes")
    captured_messages = []

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
        captured_messages.append(message)
        return "我已经看到图片。"

    class FakeStoredFile:
        file_id = "file-1"
        filename = "prompt.png"
        mime_type = "image/png"
        size_bytes = 14
        path = image_path

    class FakeStorage:
        def get_file(self, user_id, file_id):
            assert user_id == "user-1"
            assert file_id == "file-1"
            return FakeStoredFile()

    class FakeDocumentService:
        storage = FakeStorage()

    app.state.document_conversion_service = FakeDocumentService()
    app.state.image_generation_job_store = object()
    monkeypatch.setattr("app.api.chat.parse_document_message", fake_parse_document_message)
    monkeypatch.setattr("app.api.chat.parse_media_message", fake_parse_media_message)
    monkeypatch.setattr("app.api.chat.parse_image_generation_message", fake_parse_image_generation_message, raising=False)
    monkeypatch.setattr("app.api.chat.run_chat_graph", fake_run_chat_graph)

    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "thread_id": "thread-1",
            "message": "反推图片的提示词",
            "file_ids": ["file-1"],
        },
    )

    assert response.status_code == 200
    assert captured_messages
    content = captured_messages[0].content
    assert content[0] == {"type": "text", "text": "反推图片的提示词"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_chat_endpoint_routes_complex_task_to_multi_agent(monkeypatch):
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

    async def fake_run_multi_agent_graph_with_result(
        message,
        thread_id,
        user_id,
        graph,
        memories=None,
        knowledge=None,
    ):
        assert message == "读取这个 Excel，计算利润，然后生成 Word 总结"
        assert thread_id == "thread-1"
        assert user_id == "user-1"
        return type("Result", (), {"reply": "多 agent 已完成", "attachments": []})()

    async def fail_run_chat_graph(*args, **kwargs):
        raise AssertionError("complex task should not use the simple chat graph")

    monkeypatch.setattr("app.api.chat.parse_document_message", fake_parse_document_message)
    monkeypatch.setattr("app.api.chat.parse_media_message", fake_parse_media_message)
    monkeypatch.setattr("app.api.chat.parse_image_generation_message", fake_parse_image_generation_message, raising=False)
    monkeypatch.setattr("app.api.chat.run_multi_agent_graph_with_result", fake_run_multi_agent_graph_with_result)
    monkeypatch.setattr("app.api.chat.run_chat_graph", fail_run_chat_graph)

    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "thread_id": "thread-1",
            "message": "读取这个 Excel，计算利润，然后生成 Word 总结",
            "file_ids": ["file-1"],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"reply": "多 agent 已完成", "attachments": []}


def test_chat_endpoint_passes_context_to_multi_agent(monkeypatch):
    monkeypatch.setattr("app.api.chat.get_current_user_id", lambda request: "user-1")
    monkeypatch.setattr(
        "app.api.chat.get_auth_repository",
        lambda request: type(
            "Repo",
            (),
            {"thread_belongs_to_user": lambda self, thread_id, user_id: True},
        )(),
    )

    class FakeMemoryRepository:
        def search_memories(self, user_id, query, limit=5):
            assert user_id == "user-1"
            assert query == "查询资料，然后生成 Word 总结"
            return ["用户偏好: 用中文"]

    class FakeKnowledgeRepository:
        def search(self, user_id, query, limit=5):
            assert user_id == "user-1"
            assert query == "查询资料，然后生成 Word 总结"
            return ["项目知识: 总结要简洁"]

    async def fake_parse_document_message(*args, **kwargs):
        return None

    async def fake_parse_media_message(*args, **kwargs):
        return None

    async def fake_parse_image_generation_message(*args, **kwargs):
        return None

    async def fake_run_multi_agent_graph_with_result(
        message,
        thread_id,
        user_id,
        graph,
        memories=None,
        knowledge=None,
    ):
        assert memories == ["用户偏好: 用中文"]
        assert knowledge == ["项目知识: 总结要简洁"]
        return type("Result", (), {"reply": "带上下文完成", "attachments": []})()

    monkeypatch.setattr("app.api.chat.parse_document_message", fake_parse_document_message)
    monkeypatch.setattr("app.api.chat.parse_media_message", fake_parse_media_message)
    monkeypatch.setattr("app.api.chat.parse_image_generation_message", fake_parse_image_generation_message, raising=False)
    monkeypatch.setattr("app.api.chat.run_multi_agent_graph_with_result", fake_run_multi_agent_graph_with_result)
    app.state.memory_repository = FakeMemoryRepository()
    app.state.knowledge_repository = FakeKnowledgeRepository()

    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "thread_id": "thread-1",
            "message": "查询资料，然后生成 Word 总结",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"reply": "带上下文完成", "attachments": []}


def test_chat_endpoint_returns_multi_agent_attachments(monkeypatch):
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

    async def fake_run_multi_agent_graph_with_result(*args, **kwargs):
        return type(
            "Result",
            (),
            {
                "reply": "已生成 Word 总结。",
                "attachments": [
                    {
                        "platform": "document",
                        "media_type": "file",
                        "filename": "summary.docx",
                        "download_url": "/documents/files/file-1/download",
                        "file_id": "file-1",
                    }
                ],
            },
        )()

    monkeypatch.setattr("app.api.chat.parse_document_message", fake_parse_document_message)
    monkeypatch.setattr("app.api.chat.parse_media_message", fake_parse_media_message)
    monkeypatch.setattr("app.api.chat.parse_image_generation_message", fake_parse_image_generation_message, raising=False)
    monkeypatch.setattr(
        "app.api.chat.run_multi_agent_graph_with_result",
        fake_run_multi_agent_graph_with_result,
        raising=False,
    )

    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "thread_id": "thread-1",
            "message": "查询资料，然后生成 Word 总结",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "reply": "已生成 Word 总结。",
        "attachments": [
            {
                "platform": "document",
                "media_type": "file",
                "filename": "summary.docx",
                "download_url": "/documents/files/file-1/download",
                "file_id": "file-1",
            }
        ],
    }


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

    class FakeStoredFile:
        file_id = "file-1"
        filename = "receipt.png"
        mime_type = "image/png"
        size_bytes = 1200

    class FakeStorage:
        def get_file(self, user_id, file_id):
            assert user_id == "user-1"
            assert file_id == "file-1"
            return FakeStoredFile()

    class FakeDocumentService:
        storage = FakeStorage()

    app.state.document_conversion_service = FakeDocumentService()
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


def test_chat_endpoint_persists_direct_document_messages(monkeypatch):
    saved_messages = []

    monkeypatch.setattr("app.api.chat.get_current_user_id", lambda request: "user-1")

    class FakeRepository:
        def thread_belongs_to_user(self, thread_id, user_id):
            return True

        def save_thread_message(self, *, user_id, thread_id, role, text, attachments=None):
            saved_messages.append(
                {
                    "user_id": user_id,
                    "thread_id": thread_id,
                    "role": role,
                    "text": text,
                    "attachments": attachments or [],
                }
            )

    monkeypatch.setattr("app.api.chat.get_auth_repository", lambda request: FakeRepository())

    async def fake_parse_document_message(message, file_ids, user_id, service):
        return {
            "reply": "已转换为 PDF。",
            "attachments": [
                {
                    "platform": "document",
                    "media_type": "file",
                    "filename": "receipt.pdf",
                    "download_url": "/documents/files/file-2/download",
                    "file_id": "file-2",
                }
            ],
        }

    async def fail_parse_media_message(*args, **kwargs):
        raise AssertionError("document request should return before media parsing")

    class FakeStoredFile:
        file_id = "file-1"
        filename = "receipt.png"
        mime_type = "image/png"
        size_bytes = 1200

    class FakeStorage:
        def get_file(self, user_id, file_id):
            assert user_id == "user-1"
            assert file_id == "file-1"
            return FakeStoredFile()

    class FakeDocumentService:
        storage = FakeStorage()

    app.state.document_conversion_service = FakeDocumentService()
    monkeypatch.setattr("app.api.chat.parse_document_message", fake_parse_document_message, raising=False)
    monkeypatch.setattr("app.api.chat.parse_media_message", fail_parse_media_message)

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
    assert saved_messages == [
        {
            "user_id": "user-1",
            "thread_id": "thread-1",
            "role": "user",
            "text": "转成 PDF",
            "attachments": [
                {
                    "platform": "document",
                    "media_type": "file",
                    "title": "receipt.png",
                    "file_id": "file-1",
                    "filename": "receipt.png",
                    "mime_type": "image/png",
                    "download_url": "/documents/files/file-1/download",
                    "preview_url": "/documents/files/file-1/download",
                    "size_bytes": 1200,
                    "status": "uploaded",
                    "message": "已上传，等待处理。",
                }
            ],
        },
        {
            "user_id": "user-1",
            "thread_id": "thread-1",
            "role": "assistant",
            "text": "已转换为 PDF。",
            "attachments": [
                {
                    "platform": "document",
                    "media_type": "file",
                    "filename": "receipt.pdf",
                    "download_url": "/documents/files/file-2/download",
                    "file_id": "file-2",
                }
            ],
        },
    ]


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

    class FakeMessage:
        def __init__(self, role, text, attachments=None):
            self.role = role
            self.text = text
            self.attachments = attachments or []

    class FakeRepository:
        def thread_belongs_to_user(self, thread_id, user_id):
            return True

        def list_thread_messages(self, user_id, thread_id):
            assert user_id == "user-1"
            assert thread_id == "thread-1"
            return [
                FakeMessage("user", "第一轮"),
                FakeMessage(
                    "assistant",
                    "收到第一轮",
                    [{"media_type": "file", "download_url": "/documents/files/file-1/download"}],
                ),
            ]

    monkeypatch.setattr("app.api.chat.get_auth_repository", lambda request: FakeRepository())

    client = TestClient(app)
    response = client.get("/chat/thread-1")

    assert response.status_code == 200
    assert response.json() == {
        "messages": [
            {"role": "user", "text": "第一轮", "attachments": []},
            {
                "role": "assistant",
                "text": "收到第一轮",
                "attachments": [{"media_type": "file", "download_url": "/documents/files/file-1/download"}],
            },
        ]
    }


def test_chat_stream_endpoint_emits_sse_chunks_and_done(monkeypatch):
    monkeypatch.setattr("app.api.chat.get_current_user_id", lambda request: "user-1")
    monkeypatch.setattr(
        "app.api.chat.get_auth_repository",
        lambda request: type(
            "Repo",
            (),
            {
                "thread_belongs_to_user": lambda self, thread_id, user_id: True,
                "save_thread_message": lambda self, **kwargs: None,
            },
        )(),
    )

    async def fake_handle_chat_request(*args, **kwargs):
        return {"reply": "流式回复", "attachments": [{"media_type": "file"}]}

    monkeypatch.setattr("app.api.chat.handle_chat_request", fake_handle_chat_request, raising=False)

    client = TestClient(app)
    with client.stream(
        "POST",
        "/chat/stream",
        json={"thread_id": "thread-1", "message": "你好"},
    ) as response:
        body = response.read().decode("utf-8")

    assert response.status_code == 200
    assert "event: message_delta" in body
    assert 'data: {"delta":"流"}' in body
    assert 'event: attachments' in body
    assert 'data: {"attachments":[{"media_type":"file"}]}' in body
    assert "event: done" in body
