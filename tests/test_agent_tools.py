import sys
from types import ModuleType

import pytest

from app.config import parse_mcp_servers_json
from app.agent.tools.documents import build_document_tools
from app.agent.tools.images import build_image_generation_tools
from app.agent.tools.mcp import load_mcp_tools_from_config
from app.agent.tools.registry import build_builtin_tools, build_runtime_tools, build_tools
from app.agent.tools import web
from app.agent.tools.web import build_web_tools, get_open_meteo_weather


def test_build_builtin_tools_includes_weather_without_optional_configuration(monkeypatch):
    monkeypatch.setattr("app.agent.tools.web.settings.searxng_base_url", "")

    assert [tool.name for tool in build_builtin_tools()] == [
        "get_current_weather",
        "parse_social_media_link",
    ]


def test_build_tools_includes_injected_tools_after_builtin_tools(monkeypatch):
    monkeypatch.setattr("app.agent.tools.web.settings.searxng_base_url", "")
    first_tool = object()
    second_tool = object()

    tools = build_tools(extra_tools=[first_tool, second_tool])

    assert tools[0].name == "get_current_weather"
    assert tools[1].name == "parse_social_media_link"
    assert tools[2:] == [first_tool, second_tool]


@pytest.mark.anyio
async def test_build_document_tools_converts_files_for_current_user():
    class FakeResult:
        attachment = {"file_id": "file-2", "download_url": "/documents/files/file-2/download"}
        message = "已转换为 PDF。"

    class FakeService:
        def __getattr__(self, name):
            def fake_method(*args, **kwargs):
                raise AssertionError(f"{name} should not be called")

            return fake_method

        def convert(self, *, user_id, file_ids, instruction="", target_format=""):
            assert user_id == "user-1"
            assert file_ids == ["file-1"]
            assert instruction == "转成 PDF"
            assert target_format == "pdf"
            return FakeResult()

    tools = build_document_tools(user_id="user-1", service=FakeService())

    assert [tool.name for tool in tools] == [
        "convert_uploaded_file",
        "word_create",
        "word_read",
        "word_format",
        "word_edit_text",
        "excel_create",
        "excel_read",
        "excel_calculate",
        "excel_format_table",
        "pdf_create",
        "pdf_read",
    ]
    result = await tools[0].ainvoke(
        {
            "file_ids": ["file-1"],
            "instruction": "转成 PDF",
            "target_format": "pdf",
        }
    )
    assert result == {
        "message": "已转换为 PDF。",
        "attachment": {"file_id": "file-2", "download_url": "/documents/files/file-2/download"},
    }


@pytest.mark.anyio
async def test_build_document_tools_exposes_specialized_document_tools_for_current_user():
    class FakeResult:
        attachment = {"file_id": "file-3", "download_url": "/documents/files/file-3/download"}
        message = "已创建 Word 文档。"

    class FakeService:
        def create_word(self, *, user_id, filename="", title="", blocks=None, style=None):
            assert user_id == "user-1"
            assert filename == "report.docx"
            assert title == "Report"
            assert blocks == [{"type": "paragraph", "text": "Body"}]
            assert style == {"preset": "chinese_report"}
            return FakeResult()

    tools = {tool.name: tool for tool in build_document_tools(user_id="user-1", service=FakeService())}

    result = await tools["word_create"].ainvoke(
        {
            "filename": "report.docx",
            "title": "Report",
            "blocks": [{"type": "paragraph", "text": "Body"}],
            "style": {"preset": "chinese_report"},
        }
    )

    assert result == {
        "message": "已创建 Word 文档。",
        "attachment": {"file_id": "file-3", "download_url": "/documents/files/file-3/download"},
    }


@pytest.mark.anyio
async def test_build_document_tools_ingests_files_to_knowledge_for_current_user():
    class FakeResponse:
        reply = "已将 1 个文件解析到知识库。"
        attachments = [{"platform": "knowledge", "document_id": "doc-1"}]

    class FakeIngestionService:
        def ingest_files(self, *, user_id, file_ids, instruction="", visibility="private"):
            assert user_id == "user-1"
            assert file_ids == ["file-1"]
            assert instruction == "解析到知识库"
            assert visibility == "private"
            return FakeResponse()

    tools = {
        tool.name: tool
        for tool in build_document_tools(
            user_id="user-1",
            service=type("DocumentService", (), {})(),
            knowledge_ingestion_service=FakeIngestionService(),
        )
    }

    result = await tools["ingest_uploaded_files_to_knowledge"].ainvoke(
        {"file_ids": ["file-1"], "instruction": "解析到知识库"}
    )

    assert result == {
        "message": "已将 1 个文件解析到知识库。",
        "attachments": [{"platform": "knowledge", "document_id": "doc-1"}],
    }


@pytest.mark.anyio
async def test_build_image_generation_tools_generates_images_for_current_user():
    class FakeResult:
        attachments = [{"image_id": "img-1", "image_url": "/images/files/img-1"}]
        message = "图片已生成。"

    class FakeService:
        async def generate(self, *, user_id, prompt, size="", quality="", count=1):
            assert user_id == "user-1"
            assert prompt == "画一张封面图"
            assert size == "1024x1024"
            assert quality == "medium"
            assert count == 1
            return FakeResult()

    tools = build_image_generation_tools(user_id="user-1", service=FakeService())

    assert [tool.name for tool in tools] == ["generate_image"]
    result = await tools[0].ainvoke(
        {
            "prompt": "画一张封面图",
            "size": "1024x1024",
            "quality": "medium",
            "count": 1,
        }
    )
    assert result == {
        "message": "图片已生成。",
        "attachments": [{"image_id": "img-1", "image_url": "/images/files/img-1"}],
    }


def test_build_web_tools_returns_empty_without_searxng_base_url(monkeypatch):
    monkeypatch.setattr("app.agent.tools.web.settings.web_search_provider", "searxng")
    monkeypatch.setattr("app.agent.tools.web.settings.searxng_base_url", "")

    assert [tool.name for tool in build_web_tools()] == ["get_current_weather"]


def test_build_web_tools_returns_searxng_tool_when_configured(monkeypatch):
    monkeypatch.setattr("app.agent.tools.web.settings.web_search_provider", "searxng")
    monkeypatch.setattr("app.agent.tools.web.settings.searxng_base_url", "https://search.local")

    tools = build_web_tools()

    assert [tool.name for tool in tools] == ["get_current_weather", "web_search"]


@pytest.mark.anyio
async def test_search_searxng_returns_normalized_results():
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {
                        "title": "Result A",
                        "url": "https://example.com/a",
                        "content": "Summary A",
                        "engine": "duckduckgo",
                    },
                    {
                        "title": "Result B",
                        "url": "https://example.com/b",
                        "content": "Summary B",
                        "engine": "brave",
                    },
                ]
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url, params, headers):
            assert url == "https://search.local/search"
            assert params == {
                "q": "agent tools",
                "format": "json",
                "language": "auto",
                "safesearch": 1,
            }
            assert headers == {"Accept": "application/json"}
            return FakeResponse()

    results = await web.search_searxng(
        "https://search.local",
        "agent tools",
        max_results=1,
        client_factory=lambda **kwargs: FakeClient(),
    )

    assert results == [
        {
            "title": "Result A",
            "url": "https://example.com/a",
            "snippet": "Summary A",
            "source": "duckduckgo",
        }
    ]


@pytest.mark.anyio
async def test_search_searxng_returns_error_result_when_request_fails():
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url, params, headers):
            raise RuntimeError("connection refused")

    results = await web.search_searxng(
        "https://search.local",
        "agent tools",
        client_factory=lambda **kwargs: FakeClient(),
    )

    assert results == [
        {
            "title": "SearXNG search failed",
            "url": "https://search.local",
            "snippet": "connection refused",
            "source": "searxng",
        }
    ]


@pytest.mark.anyio
async def test_get_open_meteo_weather_returns_structured_current_weather():
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url, params, headers=None):
            self.calls.append((url, params))
            if "geocoding-api" in url:
                return FakeResponse(
                    {
                        "results": [
                            {
                                "name": "长春市",
                                "country": "中国",
                                "admin1": "吉林省",
                                "latitude": 43.88,
                                "longitude": 125.32,
                            }
                        ]
                    }
                )
            return FakeResponse(
                {
                    "current": {
                        "time": "2026-09-03T12:00",
                        "temperature_2m": 20.5,
                        "apparent_temperature": 19.8,
                        "relative_humidity_2m": 62,
                        "precipitation": 0.0,
                        "rain": 0.0,
                        "weather_code": 1,
                        "wind_speed_10m": 8.2,
                    },
                    "current_units": {
                        "temperature_2m": "°C",
                        "apparent_temperature": "°C",
                        "relative_humidity_2m": "%",
                        "precipitation": "mm",
                        "rain": "mm",
                        "wind_speed_10m": "km/h",
                    },
                }
            )

    fake_client = FakeClient()

    result = await get_open_meteo_weather(
        "吉林长春",
        client_factory=lambda **kwargs: fake_client,
    )

    assert result == {
        "location": "中国 吉林省 长春市",
        "time": "2026-09-03T12:00",
        "temperature": "20.5°C",
        "apparent_temperature": "19.8°C",
        "humidity": "62%",
        "precipitation": "0.0mm",
        "rain": "0.0mm",
        "weather": "主要晴朗",
        "wind_speed": "8.2km/h",
        "source": "Open-Meteo",
    }


@pytest.mark.anyio
async def test_get_open_meteo_weather_retries_chinese_city_alias_when_full_location_fails():
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self):
            self.queries = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url, params, headers=None):
            if "geocoding-api" in url:
                self.queries.append(params["name"])
                if params["name"] == "吉林长春":
                    return FakeResponse({})
                return FakeResponse(
                    {
                        "results": [
                            {
                                "name": "长春市",
                                "country": "中国",
                                "admin1": "吉林",
                                "latitude": 43.88,
                                "longitude": 125.32,
                            }
                        ]
                    }
                )
            return FakeResponse(
                {
                    "current": {"weather_code": 3},
                    "current_units": {},
                }
            )

    fake_client = FakeClient()

    result = await get_open_meteo_weather(
        "吉林长春",
        client_factory=lambda **kwargs: fake_client,
    )

    assert fake_client.queries == ["吉林长春", "Changchun"]
    assert result["location"] == "中国 吉林 长春市"
    assert result["weather"] == "阴天"


@pytest.mark.anyio
async def test_get_open_meteo_weather_returns_error_when_location_is_not_found():
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url, params, headers=None):
            return FakeResponse()

    result = await get_open_meteo_weather(
        "不存在的地方",
        client_factory=lambda **kwargs: FakeClient(),
    )

    assert result == {
        "error": "Location not found",
        "location": "不存在的地方",
        "source": "Open-Meteo",
    }


@pytest.mark.anyio
async def test_load_mcp_tools_from_config_returns_empty_without_servers():
    assert await load_mcp_tools_from_config(None) == []
    assert await load_mcp_tools_from_config({}) == []


@pytest.mark.anyio
async def test_load_mcp_tools_from_config_returns_empty_when_adapter_is_missing():
    assert await load_mcp_tools_from_config(
        {"docs": {"transport": "http", "url": "https://docs.langchain.com/mcp"}}
    ) == []


@pytest.mark.anyio
async def test_load_mcp_tools_from_config_returns_empty_when_server_load_fails(monkeypatch):
    adapter_module = ModuleType("langchain_mcp_adapters.client")

    class FailingClient:
        def __init__(self, config):
            self.config = config

        async def get_tools(self):
            raise RuntimeError("server unavailable")

    adapter_module.MultiServerMCPClient = FailingClient
    package_module = ModuleType("langchain_mcp_adapters")

    monkeypatch.setitem(sys.modules, "langchain_mcp_adapters", package_module)
    monkeypatch.setitem(sys.modules, "langchain_mcp_adapters.client", adapter_module)

    assert await load_mcp_tools_from_config({"docs": {"transport": "http"}}) == []


def test_parse_mcp_servers_json_returns_empty_for_blank_or_invalid_values():
    assert parse_mcp_servers_json("") == {}
    assert parse_mcp_servers_json("not json") == {}
    assert parse_mcp_servers_json("[]") == {}


def test_parse_mcp_servers_json_returns_object_config():
    assert parse_mcp_servers_json(
        '{"docs": {"transport": "http", "url": "https://docs.langchain.com/mcp"}}'
    ) == {"docs": {"transport": "http", "url": "https://docs.langchain.com/mcp"}}


@pytest.mark.anyio
async def test_build_runtime_tools_combines_builtin_mcp_and_extra_tools(monkeypatch):
    builtin_tool = object()
    mcp_tool = object()
    extra_tool = object()

    monkeypatch.setattr(
        "app.agent.tools.registry.build_builtin_tools",
        lambda: [builtin_tool],
    )

    async def fake_load_mcp_tools_from_config(config):
        assert config == {"docs": {"transport": "http"}}
        return [mcp_tool]

    monkeypatch.setattr(
        "app.agent.tools.registry.load_mcp_tools_from_config",
        fake_load_mcp_tools_from_config,
    )

    assert await build_runtime_tools(
        mcp_config={"docs": {"transport": "http"}},
        extra_tools=[extra_tool],
    ) == [builtin_tool, extra_tool, mcp_tool]
