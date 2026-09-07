import base64
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.image_generation.api.image_router import router
from app.image_generation.chat import is_image_generation_request
from app.image_generation.jobs import ImageGenerationJob, ImageGenerationJobStore
from app.image_generation.schemas import GeneratedImagePayload
from app.image_generation.service import ImageGenerationClient, ImageGenerationError, ImageGenerationService
from app.image_generation.storage import ImageGenerationStorage
from app.main import app as main_app


ROOT = Path(__file__).resolve().parents[1]
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lNX5xwAAAABJRU5ErkJggg=="
)


def test_image_generation_request_matches_visual_prompt_generation_wording():
    assert is_image_generation_request("帮我生成masterpiece, best quality, photorealistic, raw photo, portrait")
    assert is_image_generation_request("Help me generate masterpiece, photorealistic, raw photo, portrait")
    assert not is_image_generation_request("帮我生成一段适合朋友圈的文字")


def test_image_generation_storage_saves_generated_image_with_user_scope(tmp_path):
    storage = ImageGenerationStorage(tmp_path)

    stored = storage.save_image(
        user_id="user-1",
        prompt="画一张海报",
        content=PNG_BYTES,
        mime_type="image/png",
        model="gpt-image-2",
        size="1024x1024",
        quality="medium",
    )

    assert stored.image_id.startswith("img-")
    assert stored.filename == "image.png"
    assert stored.mime_type == "image/png"
    assert storage.get_image("user-1", stored.image_id) == stored
    assert storage.get_image("user-2", stored.image_id) is None
    assert stored.path.read_bytes() == PNG_BYTES


@pytest.mark.anyio
async def test_image_generation_client_uses_dedicated_credentials_and_decodes_base64():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "created": 1,
                "data": [
                    {
                        "b64_json": base64.b64encode(PNG_BYTES).decode("ascii"),
                        "revised_prompt": "画一张细节更丰富的海报",
                    }
                ],
            },
        )

    client = ImageGenerationClient(
        api_key="image-key",
        base_url="https://images.example/v1",
        model="gpt-image-2",
        timeout_seconds=12,
        transport=httpx.MockTransport(handler),
    )

    payloads = await client.generate(
        prompt="画一张海报",
        size="1024x1024",
        quality="medium",
        count=1,
    )

    assert captured["url"] == "https://images.example/v1/images/generations"
    assert captured["authorization"] == "Bearer image-key"
    assert captured["body"] == {
        "model": "gpt-image-2",
        "prompt": "画一张海报",
        "size": "1024x1024",
        "quality": "medium",
        "n": 1,
    }
    assert payloads == [GeneratedImagePayload(content=PNG_BYTES, revised_prompt="画一张细节更丰富的海报")]


@pytest.mark.anyio
async def test_image_generation_client_downloads_url_images():
    requested_urls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if str(request.url) == "https://images.example/v1/images/generations":
            return httpx.Response(
                200,
                json={
                    "created": 1,
                    "data": [
                        {
                            "url": "https://cdn.example/generated.png",
                            "revised_prompt": "画一张更清晰的封面图",
                        }
                    ],
                },
            )
        if str(request.url) == "https://cdn.example/generated.png":
            return httpx.Response(
                200,
                content=PNG_BYTES,
                headers={"content-type": "image/png; charset=binary"},
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    client = ImageGenerationClient(
        api_key="image-key",
        base_url="https://images.example/v1",
        model="gpt-image-2",
        timeout_seconds=12,
        transport=httpx.MockTransport(handler),
    )

    payloads = await client.generate(
        prompt="画一张封面图",
        size="1024x1024",
        quality="medium",
        count=1,
    )

    assert requested_urls == [
        "https://images.example/v1/images/generations",
        "https://cdn.example/generated.png",
    ]
    assert payloads == [
        GeneratedImagePayload(
            content=PNG_BYTES,
            revised_prompt="画一张更清晰的封面图",
            mime_type="image/png",
        )
    ]


@pytest.mark.anyio
async def test_image_generation_client_reports_url_download_connection_errors():
    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://images.example/v1/images/generations":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "url": "https://cdn.example/generated.png",
                        }
                    ],
                },
            )
        raise httpx.ConnectError("connection refused", request=request)

    client = ImageGenerationClient(
        api_key="image-key",
        base_url="https://images.example/v1",
        model="gpt-image-2",
        timeout_seconds=12,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ImageGenerationError, match="图片下载失败.*cdn.example"):
        await client.generate(prompt="画一张封面图", size="1024x1024", quality="medium", count=1)


@pytest.mark.anyio
async def test_image_generation_client_returns_clear_timeout_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = ImageGenerationClient(
        api_key="image-key",
        base_url="https://images.example/v1",
        model="gpt-image-2",
        timeout_seconds=12,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ImageGenerationError, match="图片生成接口请求超时"):
        await client.generate(prompt="画一张海报", size="1024x1024", quality="medium", count=1)


def test_image_generation_client_requires_image_specific_key(monkeypatch):
    monkeypatch.setattr("app.image_generation.service.settings.openai_api_key", "chat-key")
    monkeypatch.setattr("app.image_generation.service.settings.image_openai_api_key", "")

    with pytest.raises(ImageGenerationError, match="IMAGE_OPENAI_API_KEY"):
        ImageGenerationClient.from_settings()


@pytest.mark.anyio
async def test_image_generation_service_stores_generated_images_as_chat_attachments(tmp_path):
    class FakeClient:
        async def generate(self, *, prompt, size, quality, count):
            assert prompt == "画一张猫咖海报"
            assert size == "1024x1024"
            assert quality == "medium"
            assert count == 1
            return [GeneratedImagePayload(content=PNG_BYTES, revised_prompt="猫咖海报，暖光")]

    storage = ImageGenerationStorage(tmp_path)
    service = ImageGenerationService(storage, client=FakeClient())

    result = await service.generate(
        user_id="user-1",
        prompt="画一张猫咖海报",
        size="1024x1024",
        quality="medium",
        count=1,
    )

    assert result.message == "图片已生成。"
    assert len(result.attachments) == 1
    attachment = result.attachments[0]
    stored = storage.get_image("user-1", attachment["image_id"])
    assert stored is not None
    assert stored.path.read_bytes() == PNG_BYTES
    assert attachment["media_type"] == "generated_image"
    assert attachment["image_url"] == f"/images/files/{stored.image_id}"
    assert attachment["download_url"] == f"/images/files/{stored.image_id}/download"
    assert attachment["model"] == "gpt-image-2"
    assert attachment["revised_prompt"] == "猫咖海报，暖光"


@pytest.mark.anyio
async def test_image_generation_job_store_runs_generation_and_scopes_by_user(tmp_path):
    class FakeClient:
        async def generate(self, *, prompt, size, quality, count):
            return [GeneratedImagePayload(content=PNG_BYTES, revised_prompt="")]

    service = ImageGenerationService(ImageGenerationStorage(tmp_path), client=FakeClient())
    jobs = ImageGenerationJobStore(service)

    job = jobs.create_job(
        user_id="user-1",
        prompt="生成一张封面图",
        size="1024x1024",
        quality="medium",
        count=1,
    )

    assert job.status in {"queued", "running"}
    for _ in range(10):
        current = jobs.get_job("user-1", job.job_id)
        if current and current.status == "ready":
            break
        await jobs.wait_for_progress()

    ready = jobs.get_job("user-1", job.job_id)
    assert ready is not None
    assert ready.status == "ready"
    assert ready.attachments[0]["media_type"] == "generated_image"
    assert jobs.get_job("user-2", job.job_id) is None


def test_image_generation_router_creates_job_and_returns_ready_result(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.image_generation.api.image_router.get_current_user_id",
        lambda request: "user-1",
    )

    ready_job = ImageGenerationJob(
        job_id="imgjob-1",
        user_id="user-1",
        prompt="生成一张封面图",
        size="1024x1024",
        quality="medium",
        count=1,
        status="ready",
        reply="图片已生成。",
        attachments=[
            {
                "platform": "image-generation",
                "media_type": "generated_image",
                "image_id": "img-1",
                "image_url": "/images/files/img-1",
                "download_url": "/images/files/img-1/download",
            }
        ],
    )

    class FakeJobStore:
        def create_job(self, *, user_id, prompt, size, quality, count):
            assert user_id == "user-1"
            assert prompt == "生成一张封面图"
            return ImageGenerationJob(
                job_id="imgjob-1",
                user_id=user_id,
                prompt=prompt,
                size=size,
                quality=quality,
                count=count,
                status="queued",
                reply="已开始生成图片，我会在完成后展示。",
            )

        def get_job(self, user_id, job_id):
            assert user_id == "user-1"
            assert job_id == "imgjob-1"
            return ready_job

    app = FastAPI()
    app.state.image_generation_job_store = FakeJobStore()
    app.include_router(router)
    client = TestClient(app)

    create_response = client.post(
        "/images/generate",
        json={"prompt": "生成一张封面图", "size": "1024x1024", "quality": "medium", "count": 1},
        headers={"Authorization": "Bearer token"},
    )
    assert create_response.status_code == 200
    assert create_response.json()["attachments"][0]["media_type"] == "image_generation_job"
    assert create_response.json()["attachments"][0]["poll_url"] == "/images/jobs/imgjob-1"

    poll_response = client.get(
        "/images/jobs/imgjob-1",
        headers={"Authorization": "Bearer token"},
    )
    assert poll_response.status_code == 200
    assert poll_response.json()["status"] == "ready"
    assert poll_response.json()["attachments"][0]["image_url"] == "/images/files/img-1"


def test_main_app_mounts_image_generation_routes():
    route_paths = set(main_app.openapi()["paths"])

    assert "/images/generate" in route_paths
    assert "/images/jobs/{job_id}" in route_paths
    assert "/images/files/{image_id}" in route_paths


def test_env_example_includes_dedicated_image_generation_settings():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")

    for name in (
        "IMAGE_OPENAI_API_KEY",
        "IMAGE_OPENAI_BASE_URL",
        "IMAGE_GENERATION_MODEL",
        "IMAGE_GENERATION_DEFAULT_SIZE",
        "IMAGE_GENERATION_DEFAULT_QUALITY",
        "IMAGE_GENERATION_TIMEOUT_SECONDS",
        "IMAGE_GENERATION_MAX_IMAGES",
    ):
        assert name in text
