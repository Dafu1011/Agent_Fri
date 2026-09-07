from fastapi import APIRouter, HTTPException, Request

from app.agent.graph import get_thread_messages, run_chat_graph
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

    document_service = get_document_conversion_service(fastapi_request)
    document_response = await parse_document_message(
        request.message,
        request.file_ids,
        user_id,
        document_service,
    )
    if document_response is not None:
        return ChatResponse(**document_response)

    media_response = await parse_media_message(request.message)
    if media_response is not None:
        return ChatResponse(**media_response)

    image_generation_job_store = get_image_generation_job_store(fastapi_request)
    image_generation_response = await parse_image_generation_message(
        request.message,
        user_id,
        image_generation_job_store,
    )
    if image_generation_response is not None:
        return ChatResponse(**image_generation_response)

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
    try:
        reply = await run_chat_graph(
            request.message,
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
    return ChatResponse(reply=reply)


@router.get("/{thread_id}", response_model=ChatHistoryResponse)
async def chat_history(thread_id: str, fastapi_request: Request) -> ChatHistoryResponse:
    user_id = get_current_user_id(fastapi_request)
    auth_repository = get_auth_repository(fastapi_request)
    if not auth_repository.thread_belongs_to_user(thread_id, user_id):
        raise HTTPException(status_code=404, detail="Thread not found")

    graph = getattr(fastapi_request.app.state, "chat_graph", None)
    messages = await get_thread_messages(graph, thread_id=thread_id)
    return ChatHistoryResponse(
        messages=[
            {"role": message["role"], "text": message["content"]}
            for message in messages
        ]
    )
