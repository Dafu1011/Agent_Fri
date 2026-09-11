from app.document_tools.schemas import StoredDocument
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.knowledge import router as knowledge_router
from app.knowledge_ingestion import (
    FileTextExtractor,
    KnowledgeIngestionService,
    is_knowledge_ingestion_request,
)


def test_ingestion_intent_requires_file_ids_and_explicit_keyword():
    assert is_knowledge_ingestion_request("把这个 PDF 解析到知识库", ["file-1"]) is True
    assert is_knowledge_ingestion_request("把附件入库", ["file-1"]) is True
    assert is_knowledge_ingestion_request("总结这个文件", ["file-1"]) is False
    assert is_knowledge_ingestion_request("解析到知识库", []) is False


def test_text_and_markdown_files_are_extracted(tmp_path):
    text_path = tmp_path / "notes.md"
    text_path.write_text("# Title\n\nBody", encoding="utf-8")
    stored = StoredDocument(
        file_id="file-1",
        user_id="user-1",
        filename="notes.md",
        mime_type="text/markdown",
        size_bytes=text_path.stat().st_size,
        path=text_path,
        kind="upload",
    )

    result = FileTextExtractor(service=None).extract("user-1", stored)

    assert result.text == "# Title\n\nBody"
    assert result.title == "notes.md"


def test_ingestion_service_adds_supported_file_to_knowledge(tmp_path):
    file_path = tmp_path / "notes.txt"
    file_path.write_text("Project facts", encoding="utf-8")
    stored = StoredDocument("file-1", "user-1", "notes.txt", "text/plain", 13, file_path, "upload")

    class FakeStorage:
        def get_file(self, user_id, file_id):
            assert user_id == "user-1"
            assert file_id == "file-1"
            return stored

    class FakeRepository:
        def add_document(self, **kwargs):
            assert kwargs["owner_user_id"] == "user-1"
            assert kwargs["title"] == "notes.txt"
            assert kwargs["content"] == "Project facts"
            assert kwargs["source"] == "upload:file-1:notes.txt"
            assert kwargs["visibility"] == "private"
            return type("Doc", (), {"id": "doc-1", "title": "notes.txt"})()

    response = KnowledgeIngestionService(
        storage=FakeStorage(),
        document_service=None,
        knowledge_repository=FakeRepository(),
    ).ingest_files(user_id="user-1", file_ids=["file-1"], instruction="解析到知识库")

    assert response.reply == "已将 1 个文件解析到知识库。"
    assert response.results[0].status == "ingested"
    assert response.results[0].document_id == "doc-1"


def test_ingestion_service_reports_missing_and_unsupported_files(tmp_path):
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"fake")
    image = StoredDocument("file-2", "user-1", "image.png", "image/png", 4, image_path, "upload")

    class FakeStorage:
        def get_file(self, user_id, file_id):
            return image if file_id == "file-2" else None

    class FakeRepository:
        def add_document(self, **kwargs):
            raise AssertionError("unsupported and missing files should not be added")

    response = KnowledgeIngestionService(
        storage=FakeStorage(),
        document_service=None,
        knowledge_repository=FakeRepository(),
    ).ingest_files(user_id="user-1", file_ids=["file-1", "file-2"], instruction="加入知识库")

    assert [item.status for item in response.results] == ["failed", "failed"]
    assert "找不到上传文件" in response.results[0].error
    assert "暂不支持" in response.results[1].error


def test_knowledge_ingest_files_endpoint_ingests_uploaded_file(monkeypatch, tmp_path):
    monkeypatch.setattr("app.api.knowledge.get_current_user_id", lambda request: "user-1")
    file_path = tmp_path / "notes.txt"
    file_path.write_text("Project facts", encoding="utf-8")
    stored = StoredDocument("file-1", "user-1", "notes.txt", "text/plain", 13, file_path, "upload")

    class FakeStorage:
        def get_file(self, user_id, file_id):
            return stored

    class FakeRepository:
        def add_document(self, **kwargs):
            return type("Doc", (), {"id": "doc-1", "title": kwargs["title"]})()

    app = FastAPI()
    app.state.document_storage = FakeStorage()
    app.state.document_conversion_service = None
    app.state.knowledge_repository = FakeRepository()
    app.include_router(knowledge_router)

    response = TestClient(app).post(
        "/knowledge/ingest-files",
        json={"file_ids": ["file-1"], "instruction": "解析到知识库"},
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["document_id"] == "doc-1"
