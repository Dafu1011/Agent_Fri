"""聊天智能体图模块。

该模块定义了基于LangGraph的聊天机器人架构，包括：
- 图的构建和编译
- 节点定义（加载记忆、聊天、保存记忆）
- 状态管理和线程配置
- PostgreSQL检查点和存储的初始化
"""

from functools import lru_cache
from typing import Any

from langgraph.graph import END, StateGraph

from app.agent.chat import generate_reply
from app.agent.memory import PostgresMemoryRepository
from app.agent.state import ChatState
from app.config import settings


def ensure_async_postgres_event_loop_policy() -> None:
    """Use a Windows-compatible event loop for async psycopg connections."""
    import asyncio
    import sys

    if sys.platform == "win32" and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


ensure_async_postgres_event_loop_policy()


async def chatbot_node(state: ChatState) -> dict[str, Any]:
    """聊天机器人节点。
    
    根据当前的对话状态生成AI回复。
    
    Args:
        state: 包含消息历史和可选记忆的聊天状态
        
    Returns:
        包含助手回复和消息的字典
    """
    reply = await generate_reply(state["messages"], memories=state.get("memories", []))
    return {
        "messages": [{"role": "assistant", "content": reply}],
        "reply": reply,
    }


def build_chat_graph(
    checkpointer: Any | None = None,
    memory_repository: Any | None = None,
):
    """构建聊天图。
    
    创建一个LangGraph状态图，包含三个节点的工作流：
    加载记忆 -> 聊天回复 -> 保存记忆
    
    Args:
        checkpointer: 可选的检查点管理器，用于持久化状态
        memory_repository: 可选的记忆库，用于搜索和保存记忆
        
    Returns:
        编译后的LangGraph图对象
    """
    graph = StateGraph(ChatState)

    async def load_memories_node(state: ChatState) -> dict[str, Any]:
        """加载记忆节点。
        
        根据用户最新消息搜索相关的记忆信息。
        如果没有配置记忆库，返回空记忆列表。
        """
        if memory_repository is None:
            return {"memories": []}
        latest_user_message = state["messages"][-1]["content"]
        memories = memory_repository.search_memories(
            user_id=state["user_id"],
            query=latest_user_message,
            limit=5,
        )
        return {"memories": memories}

    async def save_memories_node(state: ChatState) -> dict[str, Any]:
        """保存记忆节点。
        
        从用户最新的消息中提取并保存重要信息到记忆库。
        如果没有配置记忆库，此操作被跳过。
        """
        if memory_repository is None:
            return {}
        # 找到最后一条用户消息
        latest_user_message = next(
            message["content"]
            for message in reversed(state["messages"])
            if message["role"] == "user"
        )
        # 保存消息内容到记忆库
        memory_repository.save_from_message(
            user_id=state["user_id"],
            thread_id=state["thread_id"],
            message=latest_user_message,
        )
        return {}

    # 添加三个节点到图中
    graph.add_node("load_memories", load_memories_node)
    graph.add_node("chatbot", chatbot_node)
    graph.add_node("save_memories", save_memories_node)
    
    # 设置图的入口点
    graph.set_entry_point("load_memories")
    
    # 连接节点的边，形成工作流
    graph.add_edge("load_memories", "chatbot")
    graph.add_edge("chatbot", "save_memories")
    graph.add_edge("save_memories", END)

    # 编译图，可选地添加检查点用于状态持久化
    return graph.compile(checkpointer=checkpointer)


@lru_cache(maxsize=1)
def get_chat_graph():
    """获取缓存的聊天图实例。
    
    使用LRU缓存避免重复创建图对象。
    
    Returns:
        缓存的LangGraph图对象
    """
    return build_chat_graph()


def create_initial_state(message: str, user_id: str, thread_id: str) -> ChatState:
    """创建初始聊天状态。
    
    为新的聊天消息构建初始状态对象。
    
    Args:
        message: 用户的初始消息内容
        user_id: 用户唯一标识符
        thread_id: 对话线程的唯一标识符
        
    Returns:
        初始化的ChatState字典
    """
    return {
        "messages": [{"role": "user", "content": message}],
        "reply": "",
        "user_id": user_id,
        "thread_id": thread_id,
        "memories": [],
    }


def create_thread_config(thread_id: str) -> dict[str, dict[str, str]]:
    """创建线程配置。
    
    为LangGraph生成配置对象，用于线程级别的状态管理。
    
    Args:
        thread_id: 对话线程的唯一标识符
        
    Returns:
        包含线程配置的字典
    """
    return {"configurable": {"thread_id": thread_id}}


async def run_chat_graph(
    message: str,
    thread_id: str,
    user_id: str,
    graph: Any | None = None,
    memory_repository: Any | None = None,
) -> str:
    """执行聊天图的完整工作流。
    
    运行聊天图，处理用户消息并返回AI回复。
    如果未提供图，将使用默认配置创建新图。
    
    Args:
        message: 用户的输入消息
        thread_id: 对话线程的唯一标识符
        user_id: 用户唯一标识符
        graph: 可选的预编译图对象。如果为None，将创建新图
        memory_repository: 可选的记忆库对象
        
    Returns:
        AI生成的回复文本
    """
    # 使用提供的图，或创建新图
    graph = graph or build_chat_graph(memory_repository=memory_repository)
    # 异步调用图并等待结果
    result = await graph.ainvoke(
        create_initial_state(message=message, user_id=user_id, thread_id=thread_id),
        config=create_thread_config(thread_id),
    )
    return result["reply"]


async def get_thread_messages(graph: Any | None, thread_id: str) -> list[dict[str, str]]:
    """Read checkpointed chat messages for a LangGraph thread."""
    if graph is None:
        return []

    state = await graph.aget_state(create_thread_config(thread_id))
    values = getattr(state, "values", {}) or {}
    messages = values.get("messages", [])
    return [
        {"role": message["role"], "content": message["content"]}
        for message in messages
        if message.get("role") in {"user", "assistant"} and "content" in message
    ]


async def build_postgres_checkpointer():
    """创建PostgreSQL检查点管理器。
    
    初始化PostgreSQL检查点系统，用于持久化LangGraph的状态。
    这允许在中断后恢复对话状态。
    
    Returns:
        元组 (上下文管理器, 检查点对象)
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    ensure_async_postgres_event_loop_policy()
    # FastAPI calls graph.ainvoke(), so the checkpointer must be async too.
    checkpointer_context = AsyncPostgresSaver.from_conn_string(settings.database_url)
    checkpointer = await checkpointer_context.__aenter__()
    # 初始化检查点数据库表结构
    await checkpointer.setup()
    return checkpointer_context, checkpointer


def build_postgres_memory_repository() -> PostgresMemoryRepository:
    """创建基于PostgreSQL存储的记忆库。
    
    使用应用自有的 agent_memories 表保存结构化长期记忆。
        
    Returns:
        初始化的PostgresMemoryRepository实例
    """
    repository = PostgresMemoryRepository.from_conn_string(settings.database_url)
    repository.setup()
    return repository
