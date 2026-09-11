from langchain_core.tools import tool

from app.agent.tools.catalog import ToolCatalog, build_tool_catalog


@tool("word_read")
def fake_word_read(file_id: str) -> dict:
    """Read a Word document."""
    return {"file_id": file_id}


@tool("generate_image")
def fake_generate_image(prompt: str) -> dict:
    """Generate an image."""
    return {"prompt": prompt}


@tool("ingest_uploaded_files_to_knowledge")
def fake_ingest_uploaded_files_to_knowledge(file_ids: list[str]) -> dict:
    """Ingest uploaded files."""
    return {"file_ids": file_ids}


def test_build_tool_catalog_infers_metadata_for_known_tools():
    catalog = build_tool_catalog([fake_word_read, fake_generate_image, fake_ingest_uploaded_files_to_knowledge])

    word_spec = catalog.get("word_read")
    assert word_spec is not None
    assert word_spec.domain == "document"
    assert word_spec.capability == "read_docx"
    assert word_spec.owner_worker == "document_worker"
    assert word_spec.risk_level == "low"

    image_spec = catalog.get("generate_image")
    assert image_spec is not None
    assert image_spec.domain == "image"
    assert image_spec.capability == "generate_asset"
    assert image_spec.owner_worker == "image_worker"
    assert image_spec.risk_level == "medium"

    ingestion_spec = catalog.get("ingest_uploaded_files_to_knowledge")
    assert ingestion_spec is not None
    assert ingestion_spec.domain == "document"
    assert ingestion_spec.capability == "ingest_to_knowledge"
    assert ingestion_spec.owner_worker == "document_worker"
    assert ingestion_spec.risk_level == "medium"


def test_tool_catalog_selects_tools_by_domain_and_name():
    catalog = build_tool_catalog([fake_word_read, fake_generate_image])

    assert catalog.select_domains(["document"]) == [fake_word_read]
    assert catalog.select_names(["generate_image"]) == [fake_generate_image]
    assert catalog.names() == ["word_read", "generate_image"]


def test_tool_catalog_describes_tools_for_planning():
    catalog = ToolCatalog.from_tools([fake_word_read])

    assert catalog.describe_for_planner() == [
        {
            "name": "word_read",
            "description": "Read a Word document.",
            "domain": "document",
            "capability": "read_docx",
            "risk_level": "low",
            "owner_worker": "document_worker",
            "requires_confirmation": False,
            "input_types": ["file"],
            "output_types": ["text"],
            "estimated_latency_ms": 1000,
        }
    ]


def test_build_tool_catalog_includes_latency_and_io_metadata_for_router():
    catalog = build_tool_catalog([fake_word_read, fake_generate_image])

    image_spec = catalog.get("generate_image")
    assert image_spec is not None
    assert image_spec.input_types == ["text"]
    assert image_spec.output_types == ["image"]
    assert image_spec.estimated_latency_ms == 15000

    assert catalog.describe_for_planner()[1]["input_types"] == ["text"]
