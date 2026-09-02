from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.knowledge import router as knowledge_router
from app.api.memory import router as memory_router
from app.agent.graph import (
    build_chat_graph,
    build_postgres_checkpointer,
    build_postgres_memory_repository,
)
from app.auth import build_auth_repository
from app.knowledge import build_knowledge_repository


@asynccontextmanager
async def lifespan(app: FastAPI):
    checkpointer_context = None
    auth_repository = None
    knowledge_repository = None
    memory_repository = None

    try:
        auth_repository = build_auth_repository()
        app.state.auth_repository = auth_repository
    except Exception:
        app.state.auth_repository = None

    try:
        checkpointer_context, checkpointer = await build_postgres_checkpointer()
    except Exception:
        checkpointer = None

    try:
        memory_repository = build_postgres_memory_repository()
        app.state.memory_repository = memory_repository
    except Exception:
        app.state.memory_repository = None

    try:
        knowledge_repository = build_knowledge_repository()
        app.state.knowledge_repository = knowledge_repository
    except Exception:
        app.state.knowledge_repository = None

    if checkpointer is not None or memory_repository is not None or knowledge_repository is not None:
        app.state.chat_graph = build_chat_graph(
            checkpointer=checkpointer,
            memory_repository=memory_repository,
            knowledge_repository=knowledge_repository,
        )
        app.state.persistence_status = "postgres"
    else:
        app.state.chat_graph = build_chat_graph()
        app.state.persistence_status = "disabled"
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

STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello, {name}!"}
