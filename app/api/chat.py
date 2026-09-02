from fastapi import APIRouter, Request

from app.agent.graph import get_thread_messages, run_chat_graph
from app.schemas.chat import ChatHistoryResponse, ChatRequest, ChatResponse


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, fastapi_request: Request) -> ChatResponse:
    graph = getattr(fastapi_request.app.state, "chat_graph", None)
    memory_repository = getattr(fastapi_request.app.state, "memory_repository", None)
    reply = await run_chat_graph(
        request.message,
        thread_id=request.thread_id,
        user_id=request.user_id,
        graph=graph,
        memory_repository=memory_repository,
    )
    return ChatResponse(reply=reply)


@router.get("/{thread_id}", response_model=ChatHistoryResponse)
async def chat_history(thread_id: str, fastapi_request: Request) -> ChatHistoryResponse:
    graph = getattr(fastapi_request.app.state, "chat_graph", None)
    messages = await get_thread_messages(graph, thread_id=thread_id)
    return ChatHistoryResponse(
        messages=[
            {"role": message["role"], "text": message["content"]}
            for message in messages
        ]
    )
