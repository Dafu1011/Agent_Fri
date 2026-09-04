from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_docker_compose_defines_local_searxng_service():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "searxng:" in compose
    assert "image: docker.io/searxng/searxng:latest" in compose
    assert '"8080:8080"' in compose
    assert "./searxng/settings.yml:/etc/searxng/settings.yml:ro" in compose


def test_searxng_settings_enable_json_api_for_agent_search():
    settings = (ROOT / "searxng" / "settings.yml").read_text(encoding="utf-8")

    assert "formats:" in settings
    assert "- html" in settings
    assert "- json" in settings
    assert "limiter: false" in settings
    assert "public_instance: false" in settings
    assert "name: bing" in settings
    assert "name: brave" in settings


def test_env_example_points_agent_to_local_searxng():
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "WEB_SEARCH_PROVIDER=searxng" in env_example
    assert "SEARXNG_BASE_URL=http://localhost:8080" in env_example


def test_env_example_points_agent_to_docker_postgres_host_port():
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert '"55432:5432"' in compose
    assert "DATABASE_URL=postgresql://agent:agent@localhost:55432/agent_memory" in env_example
