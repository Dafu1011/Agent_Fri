from typing import Any, Sequence

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.agent.state import ChatMessage
from app.config import settings


def _to_langchain_message(message: ChatMessage | BaseMessage) -> BaseMessage:
    if isinstance(message, BaseMessage):
        return message
    if message["role"] == "user":
        return HumanMessage(content=message["content"])
    return AIMessage(content=message["content"])


def _tool_call_ids(message: AIMessage) -> set[str]:
    return {
        str(tool_call["id"])
        for tool_call in (message.tool_calls or [])
        if tool_call.get("id")
    }


def _sanitize_tool_call_history(messages: list[BaseMessage]) -> list[BaseMessage]:
    sanitized: list[BaseMessage] = []
    index = 0
    while index < len(messages):
        message = messages[index]

        if isinstance(message, ToolMessage):
            index += 1
            continue

        if not isinstance(message, AIMessage) or not message.tool_calls:
            sanitized.append(message)
            index += 1
            continue

        expected_tool_call_ids = _tool_call_ids(message)
        tool_messages: list[ToolMessage] = []
        scan_index = index + 1
        while scan_index < len(messages) and isinstance(messages[scan_index], ToolMessage):
            tool_messages.append(messages[scan_index])
            scan_index += 1

        returned_tool_call_ids = {
            str(tool_message.tool_call_id)
            for tool_message in tool_messages
            if tool_message.tool_call_id
        }
        if expected_tool_call_ids and expected_tool_call_ids <= returned_tool_call_ids:
            sanitized.append(message)
            sanitized.extend(tool_messages)

        index = scan_index

    return sanitized


def build_model_messages(
    messages: Sequence[ChatMessage | BaseMessage],
    memories: list[str] | None = None,
    knowledge: list[str] | None = None,
) -> list[BaseMessage]:
    system_prompt = (
        "You are a Chinese-language AI assistant. "
        "Answer the user's request directly in Chinese. "
        "If the user asks about a concept, explain it directly. "
        "Use available tools for real-time information, especially weather, "
        "news, search, prices, schedules, and facts that may have changed. "
        "Do not claim that no user request was provided."
    )
    if memories:
        memory_lines = "\n".join(f"- {memory}" for memory in memories)
        system_prompt = (
            f"{system_prompt}\n\n"
            "Known long-term memories about this user:\n"
            f"{memory_lines}\n"
            "Use these memories when they are relevant, but do not mention them "
            "unless they help answer the user."
        )
    if knowledge:
        knowledge_lines = "\n".join(f"- {item}" for item in knowledge)
        system_prompt = (
            f"{system_prompt}\n\n"
            "Relevant knowledge base context:\n"
            f"{knowledge_lines}\n"
            "Use this retrieved context when it is relevant. If it conflicts with "
            "the user's private memories, do not merge the two sources silently."
        )
    history = [_to_langchain_message(message) for message in messages]
    return [SystemMessage(content=system_prompt)] + _sanitize_tool_call_history(history)



async def generate_reply(
    messages: Sequence[ChatMessage | BaseMessage],
    memories: list[str] | None = None,
    knowledge: list[str] | None = None,
) -> str:
    response = await generate_model_message(
        messages,
        memories=memories,
        knowledge=knowledge,
    )
    return str(response.content)


async def generate_model_message(
    messages: Sequence[ChatMessage | BaseMessage],
    memories: list[str] | None = None,
    knowledge: list[str] | None = None,
    tools: list[Any] | None = None,
) -> AIMessage:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=0,
    )
    if tools:
        llm = llm.bind_tools(tools)
    response = await llm.ainvoke(
        build_model_messages(messages, memories=memories, knowledge=knowledge)
    )
    return response
