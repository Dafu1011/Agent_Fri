import base64
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from app.agent.graph import get_thread_messages, run_chat_graph
from app.agent.multi_agent.graph import build_multi_agent_graph, run_multi_agent_graph_with_result
from app.agent.multi_agent.learning import InMemoryLearningRepository
from app.agent.multi_agent.router import classify_task_route
from app.agent.tools.catalog import build_tool_catalog
from app.agent.tools.documents import build_document_tools
from app.agent.tools.images import build_image_generation_tools
from app.api.auth import get_auth_repository, get_current_user_id
from app.document_tools.api.document_router import get_document_conversion_service
from app.document_tools.chat import parse_document_message
from app.image_generation.api.image_router import get_image_generation_job_store, get_image_generation_service
from app.image_generation.chat import parse_image_generation_message
from app.media_downloader.chat import parse_media_message
from app.schemas.chat import ChatHistoryResponse, ChatRequest, ChatResponse


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, fastapi_request: Request) -> ChatResponse:
    user_id = get_current_user_id(fastapi_request)
    auth_repository = get_auth_repository(fastapi_request)
    if not auth_repository.thread_belongs_to_user(request.thread_id, user_id):
        raise HTTPException(status_code=404, detail="Thread not found")

    result = await handle_chat_request(request, fastapi_request, user_id, auth_repository)
    return ChatResponse(**result)


@router.post("/stream")
async def chat_stream(request: ChatRequest, fastapi_request: Request) -> StreamingResponse:
    user_id = get_current_user_id(fastapi_request)
    auth_repository = get_auth_repository(fastapi_request)
    if not auth_repository.thread_belongs_to_user(request.thread_id, user_id):
        raise HTTPException(status_code=404, detail="Thread not found")

    async def stream_events():
        try:
            result = await handle_chat_request(request, fastapi_request, user_id, auth_repository)
            reply = str(result.get("reply", ""))
            for character in reply:
                yield _sse_event("message_delta", {"delta": character})
            attachments = list(result.get("attachments", []))
            if attachments:
                yield _sse_event("attachments", {"attachments": attachments})
            yield _sse_event("done", {"reply": reply, "attachments": attachments})
        except HTTPException as exc:
            yield _sse_event("error", {"detail": exc.detail})
        except Exception as exc:
            yield _sse_event("error", {"detail": str(exc)})

    return StreamingResponse(stream_events(), media_type="text/event-stream")


async def handle_chat_request(
    request: ChatRequest,
    fastapi_request: Request,
    user_id: str,
    auth_repository: Any,
) -> dict[str, Any]:
    document_service = get_document_conversion_service(fastapi_request)
    _save_chat_message(
        auth_repository,
        user_id=user_id,
        thread_id=request.thread_id,
        role="user",
        text=request.message,
        attachments=_uploaded_file_attachments(user_id, request.file_ids, document_service),
    )

    document_response = await parse_document_message(
        request.message,
        request.file_ids,
        user_id,
        document_service,
    )
    if document_response is not None:
        _save_chat_message(
            auth_repository,
            user_id=user_id,
            thread_id=request.thread_id,
            role="assistant",
            text=document_response["reply"],
            attachments=document_response.get("attachments", []),
        )
        return document_response

    media_response = await parse_media_message(request.message)
    if media_response is not None:
        _save_chat_message(
            auth_repository,
            user_id=user_id,
            thread_id=request.thread_id,
            role="assistant",
            text=media_response["reply"],
            attachments=media_response.get("attachments", []),
        )
        return media_response

    image_generation_job_store = get_image_generation_job_store(fastapi_request)
    image_generation_response = await parse_image_generation_message(
        request.message,
        user_id,
        image_generation_job_store,
    )
    if image_generation_response is not None:
        _save_chat_message(
            auth_repository,
            user_id=user_id,
            thread_id=request.thread_id,
            role="assistant",
            text=image_generation_response["reply"],
            attachments=image_generation_response.get("attachments", []),
        )
        return image_generation_response

    graph = getattr(fastapi_request.app.state, "chat_graph", None)
    memory_repository = getattr(fastapi_request.app.state, "memory_repository", None)
    knowledge_repository = getattr(fastapi_request.app.state, "knowledge_repository", None)
    base_tools = getattr(fastapi_request.app.state, "agent_tools", None) or []
    image_generation_service = get_image_generation_service(fastapi_request)
    tools = [
        *base_tools,
        *build_document_tools(user_id, document_service),
        *build_image_generation_tools(user_id, image_generation_service),
    ]
    route = classify_task_route(
        request.message,
        file_ids=request.file_ids,
        available_tool_names=[getattr(tool, "name", type(tool).__name__) for tool in tools],
    )
    try:
        if route.path == "multi_agent":
            memories = (
                memory_repository.search_memories(
                    user_id=user_id,
                    query=request.message,
                    limit=5,
                )
                if memory_repository is not None
                else []
            )
            knowledge = (
                knowledge_repository.search(
                    user_id=user_id,
                    query=request.message,
                    limit=5,
                )
                if knowledge_repository is not None
                else []
            )
            learning_repository = getattr(
                fastapi_request.app.state,
                "learning_repository",
                None,
            )
            if learning_repository is None:
                learning_repository = InMemoryLearningRepository()
                fastapi_request.app.state.learning_repository = learning_repository
            multi_agent_graph = build_multi_agent_graph(
                tool_catalog=build_tool_catalog(tools),
                learning_repository=learning_repository,
            )
            result = await run_multi_agent_graph_with_result(
                request.message,
                thread_id=request.thread_id,
                user_id=user_id,
                graph=multi_agent_graph,
                memories=memories,
                knowledge=knowledge,
            )
            response = {"reply": result.reply, "attachments": result.attachments}
            _save_chat_message(
                auth_repository,
                user_id=user_id,
                thread_id=request.thread_id,
                role="assistant",
                text=result.reply,
                attachments=result.attachments,
            )
            return response
        reply = await run_chat_graph(
            _chat_graph_user_message(request.message, user_id, request.file_ids, document_service),
            thread_id=request.thread_id,
            user_id=user_id,
            graph=graph,
            memory_repository=memory_repository,
            knowledge_repository=knowledge_repository,
            tools=tools,
        )
    except RuntimeError as exc:
        if "OPENAI_API_KEY is not configured" in str(exc):
            raise HTTPException(
                status_code=503,
                detail="模型服务未配置：请设置 OPENAI_API_KEY 后重启服务。",
            ) from exc
        raise
    _save_chat_message(
        auth_repository,
        user_id=user_id,
        thread_id=request.thread_id,
        role="assistant",
        text=reply,
        attachments=[],
    )
    return {"reply": reply, "attachments": []}


@router.get("/{thread_id}", response_model=ChatHistoryResponse)
async def chat_history(thread_id: str, fastapi_request: Request) -> ChatHistoryResponse:
    user_id = get_current_user_id(fastapi_request)
    auth_repository = get_auth_repository(fastapi_request)
    if not auth_repository.thread_belongs_to_user(thread_id, user_id):
        raise HTTPException(status_code=404, detail="Thread not found")

    if hasattr(auth_repository, "list_thread_messages"):
        stored_messages = auth_repository.list_thread_messages(user_id, thread_id)
        if stored_messages:
            return ChatHistoryResponse(
                messages=[
                    {
                        "role": message.role,
                        "text": message.text,
                        "attachments": message.attachments,
                    }
                    for message in stored_messages
                ]
            )

    graph = getattr(fastapi_request.app.state, "chat_graph", None)
    messages = await get_thread_messages(graph, thread_id=thread_id)
    return ChatHistoryResponse(
        messages=[
            {"role": message["role"], "text": message["content"]}
            for message in messages
        ]
    )


def _save_chat_message(
    auth_repository: Any,
    *,
    user_id: str,
    thread_id: str,
    role: str,
    text: str,
    attachments: list[dict[str, Any]],
) -> None:
    if hasattr(auth_repository, "save_thread_message"):
        auth_repository.save_thread_message(
            user_id=user_id,
            thread_id=thread_id,
            role=role,
            text=text,
            attachments=attachments,
        )


def _uploaded_file_attachments(
    user_id: str,
    file_ids: list[str],
    document_service: Any,
) -> list[dict[str, Any]]:
    storage = getattr(document_service, "storage", None)
    if storage is None:
        return []
    attachments: list[dict[str, Any]] = []
    for file_id in file_ids:
        stored = storage.get_file(user_id, file_id)
        if stored is None:
            continue
        download_url = f"/documents/files/{stored.file_id}/download"
        attachments.append(
            {
                "platform": "document",
                "media_type": "file",
                "title": stored.filename,
                "file_id": stored.file_id,
                "filename": stored.filename,
                "mime_type": stored.mime_type,
                "download_url": download_url,
                "preview_url": download_url,
                "size_bytes": stored.size_bytes,
                "status": "uploaded",
                "message": "已上传，等待处理。",
            }
        )
    return attachments


def _chat_graph_user_message(
    message: str,
    user_id: str,
    file_ids: list[str],
    document_service: Any,
) -> str | HumanMessage:
    image_parts = _uploaded_image_message_parts(user_id, file_ids, document_service)
    if not image_parts:
        return message
    return HumanMessage(
        content=[
            {"type": "text", "text": message},
            *image_parts,
        ]
    )


def _uploaded_image_message_parts(
    user_id: str,
    file_ids: list[str],
    document_service: Any,
) -> list[dict[str, Any]]:
    storage = getattr(document_service, "storage", None)
    if storage is None:
        return []
    parts: list[dict[str, Any]] = []
    for file_id in file_ids:
        stored = storage.get_file(user_id, file_id)
        if stored is None or not str(stored.mime_type).startswith("image/"):
            continue
        try:
            content = stored.path.read_bytes()
        except OSError:
            continue
        image_url = f"data:{stored.mime_type};base64,{base64.b64encode(content).decode('ascii')}"
        parts.append({"type": "image_url", "image_url": {"url": image_url}})
    return parts


def _sse_event(event: str, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n"
