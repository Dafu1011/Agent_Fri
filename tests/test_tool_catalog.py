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


def test_build_tool_catalog_infers_metadata_for_known_tools():
    catalog = build_tool_catalog([fake_word_read, fake_generate_image])

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
        }
    ]
