import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool

from app.agent.multi_agent.graph import (
    build_multi_agent_graph,
    run_multi_agent_graph,
    run_multi_agent_graph_with_result,
)
from app.agent.multi_agent.learning import InMemoryLearningRepository, PostgresLearningRepository
from app.agent.multi_agent.model_router import InputAttachment, decide_route
from app.agent.multi_agent.router import classify_task_route
from app.agent.tools.catalog import build_tool_catalog


@tool("excel_read")
def fake_excel_read(file_id: str) -> dict:
    """Read an Excel workbook."""
    return {"file_id": file_id}


@tool("word_create")
def fake_word_create(filename: str = "") -> dict:
    """Create a Word document."""
    return {"filename": filename}


@tool("generate_image")
def fake_generate_image(prompt: str) -> dict:
    """Generate an image."""
    return {"prompt": prompt}


def test_classify_task_route_keeps_simple_chat_fast():
    route = classify_task_route("你好，介绍一下你自己", file_ids=[], available_tool_names=[])

    assert route.path == "simple_chat"
    assert route.complexity == "low"


def test_classify_task_route_sends_multi_step_document_task_to_multi_agent():
    route = classify_task_route(
        "读取这个 Excel，计算利润，然后生成 Word 总结",
        file_ids=["file-1"],
        available_tool_names=["excel_read", "excel_calculate", "word_create"],
    )

    assert route.path == "multi_agent"
    assert route.complexity == "high"
    assert "document" in route.domains


@pytest.mark.anyio
async def test_model_router_parses_model_json_decision(monkeypatch):
    catalog = build_tool_catalog([fake_generate_image])

    async def fake_generate_model_message(messages, memories=None, knowledge=None, tools=None):
        return AIMessage(
            content=(
                '{"path":"direct_tool","intent":"image_generation","worker":"image_worker",'
                '"tool_names":["generate_image"],"needs_memory":false,'
                '"needs_knowledge":false,"confidence":0.91,"reason":"需要生成图片"}'
            )
        )

    monkeypatch.setattr(
        "app.agent.multi_agent.model_router.generate_model_message",
        fake_generate_model_message,
    )

    decision = await decide_route("帮我生成一张猫咖海报", attachments=[], tool_catalog=catalog)

    assert decision.path == "direct_tool"
    assert decision.worker == "image_worker"
    assert decision.tool_names == ["generate_image"]
    assert decision.needs_memory is False


@pytest.mark.anyio
async def test_model_router_fallback_keeps_reverse_image_prompt_on_fast_vision_path(monkeypatch):
    async def fail_generate_model_message(*args, **kwargs):
        raise RuntimeError("OPENAI_API_KEY is not configured")

    monkeypatch.setattr(
        "app.agent.multi_agent.model_router.generate_model_message",
        fail_generate_model_message,
    )
    catalog = build_tool_catalog([fake_generate_image])

    decision = await decide_route(
        "反推图片提示词",
        attachments=[InputAttachment(file_id="file-1", filename="sample.png", mime_type="image/png")],
        tool_catalog=catalog,
    )

    assert decision.path == "simple_chat"
    assert decision.intent == "image_prompt_reverse"
    assert decision.worker == "vision_worker"
    assert decision.tool_names == []
    assert decision.needs_memory is False
    assert decision.needs_knowledge is False


@pytest.mark.anyio
async def test_multi_agent_graph_runs_plan_worker_verifier_and_learning():
    catalog = build_tool_catalog([fake_excel_read, fake_word_create])
    learning_repository = InMemoryLearningRepository()

    async def planner(state, tool_catalog):
        return {
            "plan": [
                {
                    "id": "step-1",
                    "description": "读取 Excel 数据",
                    "worker": "document_worker",
                    "tool_names": ["excel_read"],
                    "status": "pending",
                },
                {
                    "id": "step-2",
                    "description": "创建 Word 总结",
                    "worker": "document_worker",
                    "tool_names": ["word_create"],
                    "status": "pending",
                },
            ],
            "selected_tool_names": ["excel_read", "word_create"],
        }

    async def worker(state, selected_tools):
        assert [tool.name for tool in selected_tools] == ["excel_read", "word_create"]
        return {
            "worker_outputs": [
                {"step_id": "step-1", "status": "success", "summary": "已读取 Excel"},
                {"step_id": "step-2", "status": "success", "summary": "已创建 Word"},
            ]
        }

    async def verifier(state):
        return {
            "verification": {
                "passed": True,
                "reason": "所有步骤成功完成",
            }
        }

    graph = build_multi_agent_graph(
        tool_catalog=catalog,
        learning_repository=learning_repository,
        planner=planner,
        worker=worker,
        verifier=verifier,
    )

    reply = await run_multi_agent_graph(
        "读取这个 Excel，计算利润，然后生成 Word 总结",
        thread_id="thread-1",
        user_id="user-1",
        graph=graph,
    )

    assert "所有步骤成功完成" in reply
    assert "已读取 Excel" in reply
    assert len(learning_repository.records) == 1
    assert learning_repository.records[0].kind == "task_pattern"


@pytest.mark.anyio
async def test_multi_agent_default_worker_executes_selected_tool_calls(monkeypatch):
    catalog = build_tool_catalog([fake_excel_read])
    model_calls = []

    async def fake_generate_model_message(messages, memories=None, knowledge=None, tools=None):
        model_calls.append(messages)
        assert [tool.name for tool in tools] == ["excel_read"]
        if len(model_calls) == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "excel_read",
                        "args": {"file_id": "file-1"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            )
        assert isinstance(messages[-1], ToolMessage)
        return AIMessage(content="已读取 Excel 并完成分析。")

    monkeypatch.setattr(
        "app.agent.multi_agent.graph.generate_model_message",
        fake_generate_model_message,
    )

    graph = build_multi_agent_graph(tool_catalog=catalog)

    reply = await run_multi_agent_graph(
        "读取这个 Excel 并分析",
        thread_id="thread-1",
        user_id="user-1",
        graph=graph,
    )

    assert "已读取 Excel 并完成分析。" in reply
    assert len(model_calls) == 2


@pytest.mark.anyio
async def test_multi_agent_result_includes_file_attachment_from_tool_output(monkeypatch):
    @tool("word_create")
    def create_downloadable_word(filename: str = "") -> dict:
        """Create a Word document."""
        return {
            "message": "已创建 Word 文档。",
            "attachment": {
                "platform": "document",
                "media_type": "file",
                "filename": filename or "summary.docx",
                "download_url": "/documents/files/file-1/download",
                "file_id": "file-1",
            },
        }

    catalog = build_tool_catalog([create_downloadable_word])

    async def fake_generate_model_message(messages, memories=None, knowledge=None, tools=None):
        if len(messages) == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "word_create",
                        "args": {"filename": "summary.docx"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content="已生成 Word 总结。")

    monkeypatch.setattr(
        "app.agent.multi_agent.graph.generate_model_message",
        fake_generate_model_message,
    )
    graph = build_multi_agent_graph(tool_catalog=catalog)

    result = await run_multi_agent_graph_with_result(
        "生成 Word 总结",
        thread_id="thread-1",
        user_id="user-1",
        graph=graph,
    )

    assert result.reply == "所有步骤成功完成\n- 已生成 Word 总结。"
    assert result.attachments == [
        {
            "platform": "document",
            "media_type": "file",
            "filename": "summary.docx",
            "download_url": "/documents/files/file-1/download",
            "file_id": "file-1",
        }
    ]


@pytest.mark.anyio
async def test_multi_agent_default_planner_selects_relevant_document_tools():
    catalog = build_tool_catalog([fake_excel_read, fake_word_create, fake_generate_image])
    seen_selected_tools = []

    async def worker(state, selected_tools):
        seen_selected_tools.extend(tool.name for tool in selected_tools)
        return {
            "worker_outputs": [
                {"step_id": "step-1", "status": "success", "summary": "文档任务已处理"}
            ]
        }

    graph = build_multi_agent_graph(tool_catalog=catalog, worker=worker)

    await run_multi_agent_graph(
        "读取 Excel，计算利润，然后生成 Word 总结",
        thread_id="thread-1",
        user_id="user-1",
        graph=graph,
    )

    assert seen_selected_tools == ["excel_read", "word_create"]


def test_postgres_learning_repository_setup_creates_learning_table():
    class FakeConnection:
        def __init__(self):
            self.statements = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            self.statements.append(str(statement))
            return self

    connection = FakeConnection()
    repository = PostgresLearningRepository(lambda: connection)

    repository.setup()

    assert any("CREATE TABLE IF NOT EXISTS agent_learnings" in stmt for stmt in connection.statements)
    assert any("CREATE INDEX IF NOT EXISTS idx_agent_learnings_user_created" in stmt for stmt in connection.statements)


def test_postgres_learning_repository_saves_successful_task_pattern():
    class FakeConnection:
        def __init__(self):
            self.executions = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            self.executions.append((str(statement), params))
            return self

    connection = FakeConnection()
    repository = PostgresLearningRepository(lambda: connection)

    record = repository.save_from_state(
        {
            "messages": [],
            "task": "读取 Excel 然后生成 Word 总结",
            "user_id": "user-1",
            "thread_id": "thread-1",
            "memories": [],
            "knowledge": [],
            "plan": [
                {
                    "id": "step-1",
                    "description": "读取 Excel",
                    "worker": "document_worker",
                    "tool_names": ["excel_read"],
                    "status": "success",
                }
            ],
            "selected_tool_names": ["excel_read"],
            "worker_outputs": [
                {"step_id": "step-1", "status": "success", "summary": "已读取 Excel"}
            ],
            "verification": {"passed": True, "reason": "所有步骤成功完成"},
            "final_reply": "所有步骤成功完成",
        }
    )

    assert record is not None
    insert_statement, params = connection.executions[0]
    assert "INSERT INTO agent_learnings" in insert_statement
    assert params[1] == "user-1"
    assert params[3] == "task_pattern"
