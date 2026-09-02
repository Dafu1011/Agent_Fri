from fastapi import APIRouter, HTTPException, Request

from app.agent.graph import get_thread_messages, run_chat_graph
from app.api.auth import get_auth_repository, get_current_user_id
from app.schemas.chat import ChatHistoryResponse, ChatRequest, ChatResponse


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, fastapi_request: Request) -> ChatResponse:
    user_id = get_current_user_id(fastapi_request)
    auth_repository = get_auth_repository(fastapi_request)
    if not auth_repository.thread_belongs_to_user(request.thread_id, user_id):
        raise HTTPException(status_code=404, detail="Thread not found")

    graph = getattr(fastapi_request.app.state, "chat_graph", None)
    memory_repository = getattr(fastapi_request.app.state, "memory_repository", None)
    knowledge_repository = getattr(fastapi_request.app.state, "knowledge_repository", None)
    reply = await run_chat_graph(
        request.message,
        thread_id=request.thread_id,
        user_id=user_id,
        graph=graph,
        memory_repository=memory_repository,
        knowledge_repository=knowledge_repository,
    )
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
