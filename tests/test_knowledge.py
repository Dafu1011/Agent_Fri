from app.knowledge import KnowledgeRepository


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


def test_knowledge_search_scopes_private_documents_to_user():
    class FakeResult:
        def fetchall(self):
            return [
                ("项目规范：回答要简洁", "项目规范", "doc-1"),
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
            assert params[0] == "user-1"
            return FakeResult()

    repository = KnowledgeRepository(lambda: FakeConnection())

    assert repository.search("user-1", "回答", limit=3) == [
        "项目规范: 项目规范：回答要简洁"
    ]
