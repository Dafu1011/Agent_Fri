from pathlib import Path
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.knowledge import router as knowledge_router
from app.api.memory import router as memory_router
from app.media_downloader.api.media_router import router as media_router
from app.agent.graph import (
    build_chat_graph,
    build_postgres_checkpointer,
    build_postgres_memory_repository,
)
from app.agent.tools.registry import build_runtime_tools
from app.auth import build_auth_repository
from app.config import parse_mcp_servers_json, settings
from app.knowledge import build_knowledge_repository

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    checkpointer_context = None
    checkpointer = None
    auth_repository = None
    knowledge_repository = None
    memory_repository = None
    startup_errors = {}

    try:
        auth_repository = build_auth_repository()
        app.state.auth_repository = auth_repository
        app.state.auth_status = "postgres"
    except Exception as exc:
        logger.exception("Auth repository initialization failed")
        startup_errors["auth"] = str(exc)
        app.state.auth_repository = None
        app.state.auth_status = "disabled"

    try:
        checkpointer_context, checkpointer = await build_postgres_checkpointer()
        app.state.checkpointer_status = "postgres"
    except Exception as exc:
        logger.exception("LangGraph checkpointer initialization failed")
        startup_errors["checkpointer"] = str(exc)
        from langgraph.checkpoint.memory import InMemorySaver

        checkpointer = InMemorySaver()
        app.state.checkpointer_status = "memory"

    try:
        memory_repository = build_postgres_memory_repository()
        app.state.memory_repository = memory_repository
        app.state.memory_status = "postgres"
    except Exception as exc:
        logger.exception("Memory repository initialization failed")
        startup_errors["memory"] = str(exc)
        app.state.memory_repository = None
        app.state.memory_status = "disabled"

    try:
        knowledge_repository = build_knowledge_repository()
        app.state.knowledge_repository = knowledge_repository
        app.state.knowledge_status = "postgres"
    except Exception as exc:
        logger.exception("Knowledge repository initialization failed")
        startup_errors["knowledge"] = str(exc)
        app.state.knowledge_repository = None
        app.state.knowledge_status = "disabled"

    try:
        agent_tools = await build_runtime_tools(
            mcp_config=parse_mcp_servers_json(settings.mcp_servers_json)
        )
    except Exception as exc:
        logger.exception("Agent tools initialization failed")
        startup_errors["tools"] = str(exc)
        agent_tools = []
    app.state.agent_tools = agent_tools
    app.state.startup_errors = startup_errors

    app.state.chat_graph = build_chat_graph(
        checkpointer=checkpointer,
        memory_repository=memory_repository,
        knowledge_repository=knowledge_repository,
        tools=agent_tools,
    )
    app.state.persistence_status = app.state.checkpointer_status
    try:
        yield
    finally:
        if checkpointer_context is not None:
            await checkpointer_context.__aexit__(None, None, None)


app = FastAPI(lifespan=lifespan)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(knowledge_router)
app.include_router(memory_router)
app.include_router(media_router)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/status")
async def status():
    agent_tools = getattr(app.state, "agent_tools", [])
    return {
        "persistence": getattr(app.state, "persistence_status", "unknown"),
        "checkpointer": getattr(app.state, "checkpointer_status", "unknown"),
        "memory": getattr(app.state, "memory_status", "unknown"),
        "knowledge": getattr(app.state, "knowledge_status", "unknown"),
        "tools": [getattr(tool, "name", type(tool).__name__) for tool in agent_tools],
        "searxng_configured": bool(settings.searxng_base_url.strip()),
        "startup_errors": getattr(app.state, "startup_errors", {}),
    }


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello, {name}!"}
