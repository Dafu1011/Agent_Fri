import sys
from types import ModuleType

from app.knowledge import KnowledgeRepository, reciprocal_rank_fusion


def test_knowledge_repository_setup_creates_pgvector_tables():
    class FakeConnection:
        def __init__(self):
            self.statements = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            self.statements.append(str(statement))

    connection = FakeConnection()
    repository = KnowledgeRepository(lambda: connection)

    repository.setup()

    assert any("CREATE EXTENSION IF NOT EXISTS vector" in stmt for stmt in connection.statements)
    assert any("CREATE TABLE IF NOT EXISTS knowledge_documents" in stmt for stmt in connection.statements)
    assert any("CREATE TABLE IF NOT EXISTS knowledge_chunks" in stmt for stmt in connection.statements)
    assert any("search_tsv TSVECTOR" in stmt for stmt in connection.statements)
    assert any("SET search_tsv = to_tsvector('simple', content)" in stmt for stmt in connection.statements)
    assert any("USING GIN (search_tsv)" in stmt for stmt in connection.statements)
    assert any("USING hnsw (embedding vector_cosine_ops)" in stmt for stmt in connection.statements)


def test_knowledge_search_scopes_private_documents_to_user():
    class FakeResult:
        def fetchall(self):
            return [
                ("chunk-1", "项目规范：回答要简洁", "项目规范", "doc-1", 0.8),
            ]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            sql = str(statement)
            assert "owner_user_id = %s" in sql
            assert "visibility = 'public'" in sql
            assert "user-1" in params
            return FakeResult()

    repository = KnowledgeRepository(lambda: FakeConnection())

    assert repository.search("user-1", "回答", limit=3) == [
        "项目规范: 项目规范：回答要简洁"
    ]


def test_reciprocal_rank_fusion_prefers_results_found_by_both_retrievers():
    fused = reciprocal_rank_fusion(
        keyword_ids=["chunk-a", "chunk-b"],
        vector_ids=["chunk-b", "chunk-c"],
    )

    assert fused[0][0] == "chunk-b"
    assert {chunk_id for chunk_id, score in fused} == {"chunk-a", "chunk-b", "chunk-c"}


def test_hybrid_search_combines_keyword_and_vector_results_with_user_scope():
    class FakeResult:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class FakeConnection:
        def __init__(self):
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            self.calls.append((str(statement), params))
            if len(self.calls) == 1:
                return FakeResult(
                    [
                        ("chunk-a", "关键词命中文本", "关键词文档", "doc-a", 0.9),
                        ("chunk-b", "共同命中文本", "共同文档", "doc-b", 0.8),
                    ]
                )
            return FakeResult(
                [
                    ("chunk-b", "共同命中文本", "共同文档", "doc-b", 0.05),
                    ("chunk-c", "向量命中文本", "向量文档", "doc-c", 0.07),
                ]
            )

    connection = FakeConnection()
    repository = KnowledgeRepository(lambda: connection)

    results = repository.hybrid_search(
        user_id="user-1",
        query="部署 PostgreSQL",
        query_embedding=[0.1, 0.2, 0.3],
        limit=3,
    )

    keyword_sql, keyword_params = connection.calls[0]
    vector_sql, vector_params = connection.calls[1]
    assert "d.owner_user_id = %s OR d.visibility = 'public'" in keyword_sql
    assert "d.owner_user_id = %s OR d.visibility = 'public'" in vector_sql
    assert "user-1" in keyword_params
    assert vector_params[0] == "[0.1,0.2,0.3]"
    assert vector_params[1] == "user-1"
    assert [result.chunk_id for result in results] == ["chunk-b", "chunk-a", "chunk-c"]
    assert results[0].sources == ["keyword", "vector"]


def test_add_document_chunks_content_and_stores_search_vector_and_embedding():
    class FakeResult:
        def __init__(self, row=None):
            self.row = row

        def fetchone(self):
            return self.row

    class FakeConnection:
        def __init__(self):
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            self.calls.append((str(statement), params))
            if "RETURNING id, owner_user_id" in str(statement):
                return FakeResult(("doc-1", "user-1", "Doc", "manual", "private", "now"))
            return FakeResult()

    class FakeEmbeddingProvider:
        def embed_documents(self, texts):
            return [[0.1, 0.2, 0.3] for _ in texts]

    connection = FakeConnection()
    repository = KnowledgeRepository(
        lambda: connection,
        embedding_provider=FakeEmbeddingProvider(),
        chunk_size=12,
        chunk_overlap=0,
    )

    repository.add_document(
        owner_user_id="user-1",
        title="Doc",
        content="第一段内容足够长。第二段内容也会被切块。",
        source="manual",
    )

    chunk_inserts = [call for call in connection.calls if "INSERT INTO knowledge_chunks" in call[0]]
    assert len(chunk_inserts) >= 2
    assert "search_tsv" in chunk_inserts[0][0]
    assert "to_tsvector" in chunk_inserts[0][0]
    assert chunk_inserts[0][1][3] == "[0.1,0.2,0.3]"


def test_openai_embedding_provider_prefers_embedding_specific_credentials(monkeypatch):
    calls = []
    fake_module = ModuleType("langchain_openai")

    class FakeOpenAIEmbeddings:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def embed_query(self, text):
            return [0.1, 0.2, 0.3]

    fake_module.OpenAIEmbeddings = FakeOpenAIEmbeddings
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)
    monkeypatch.setattr("app.knowledge.settings.openai_api_key", "chat-key")
    monkeypatch.setattr("app.knowledge.settings.openai_base_url", "https://chat.example/v1")
    monkeypatch.setattr("app.knowledge.settings.openai_embedding_api_key", "embedding-key")
    monkeypatch.setattr(
        "app.knowledge.settings.openai_embedding_base_url",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setattr("app.knowledge.settings.openai_embedding_model", "qwen3.7-text-embedding")

    from app.knowledge import OpenAIEmbeddingProvider

    assert OpenAIEmbeddingProvider().embed_query("hello") == [0.1, 0.2, 0.3]
    assert calls == [
        {
            "model": "qwen3.7-text-embedding",
            "api_key": "embedding-key",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "check_embedding_ctx_length": False,
            "dimensions": 1536,
        }
    ]


def test_openai_embedding_provider_does_not_reuse_chat_key_for_embedding_endpoint(monkeypatch):
    calls = []
    fake_module = ModuleType("langchain_openai")

    class FakeOpenAIEmbeddings:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def embed_query(self, text):
            return [0.1, 0.2, 0.3]

    fake_module.OpenAIEmbeddings = FakeOpenAIEmbeddings
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)
    monkeypatch.setattr("app.knowledge.settings.openai_api_key", "chat-key")
    monkeypatch.setattr("app.knowledge.settings.openai_base_url", "https://chat.example/v1")
    monkeypatch.setattr("app.knowledge.settings.openai_embedding_api_key", "")
    monkeypatch.setattr(
        "app.knowledge.settings.openai_embedding_base_url",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    from app.knowledge import OpenAIEmbeddingProvider

    assert OpenAIEmbeddingProvider().embed_query("hello") == [0.1, 0.2, 0.3]
    assert calls[0]["api_key"] == ""


def test_openai_embedding_provider_can_override_dimensions(monkeypatch):
    calls = []
    fake_module = ModuleType("langchain_openai")

    class FakeOpenAIEmbeddings:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def embed_query(self, text):
            return [0.1, 0.2, 0.3]

    fake_module.OpenAIEmbeddings = FakeOpenAIEmbeddings
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)
    monkeypatch.setattr("app.knowledge.settings.openai_embedding_api_key", "embedding-key")
    monkeypatch.setattr("app.knowledge.settings.openai_embedding_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setattr("app.knowledge.settings.openai_embedding_dimensions", 1024)

    from app.knowledge import OpenAIEmbeddingProvider

    assert OpenAIEmbeddingProvider().embed_query("hello") == [0.1, 0.2, 0.3]
    assert calls[0]["dimensions"] == 1024
