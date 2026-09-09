from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    name: str
    tool: Any
    description: str = ""
    domain: str = "general"
    capability: str = "general"
    risk_level: str = "low"
    owner_worker: str = "general_worker"
    requires_confirmation: bool = False


KNOWN_TOOL_METADATA: dict[str, dict[str, Any]] = {
    "web_search": {
        "domain": "research",
        "capability": "search_web",
        "owner_worker": "research_worker",
        "risk_level": "low",
    },
    "get_current_weather": {
        "domain": "research",
        "capability": "get_weather",
        "owner_worker": "research_worker",
        "risk_level": "low",
    },
    "parse_social_media_link": {
        "domain": "media",
        "capability": "parse_public_link",
        "owner_worker": "media_worker",
        "risk_level": "low",
    },
    "generate_image": {
        "domain": "image",
        "capability": "generate_asset",
        "owner_worker": "image_worker",
        "risk_level": "medium",
    },
    "convert_uploaded_file": {
        "domain": "document",
        "capability": "convert_file",
        "owner_worker": "document_worker",
        "risk_level": "medium",
    },
    "word_create": {
        "domain": "document",
        "capability": "create_docx",
        "owner_worker": "document_worker",
        "risk_level": "medium",
    },
    "word_read": {
        "domain": "document",
        "capability": "read_docx",
        "owner_worker": "document_worker",
        "risk_level": "low",
    },
    "word_format": {
        "domain": "document",
        "capability": "format_docx",
        "owner_worker": "document_worker",
        "risk_level": "medium",
    },
    "word_edit_text": {
        "domain": "document",
        "capability": "edit_docx",
        "owner_worker": "document_worker",
        "risk_level": "medium",
    },
    "excel_create": {
        "domain": "spreadsheet",
        "capability": "create_xlsx",
        "owner_worker": "document_worker",
        "risk_level": "medium",
    },
    "excel_read": {
        "domain": "spreadsheet",
        "capability": "read_xlsx",
        "owner_worker": "document_worker",
        "risk_level": "low",
    },
    "excel_calculate": {
        "domain": "spreadsheet",
        "capability": "calculate_xlsx",
        "owner_worker": "document_worker",
        "risk_level": "medium",
    },
    "excel_format_table": {
        "domain": "spreadsheet",
        "capability": "format_xlsx_table",
        "owner_worker": "document_worker",
        "risk_level": "medium",
    },
    "pdf_create": {
        "domain": "document",
        "capability": "create_pdf",
        "owner_worker": "document_worker",
        "risk_level": "medium",
    },
    "pdf_read": {
        "domain": "document",
        "capability": "read_pdf",
        "owner_worker": "document_worker",
        "risk_level": "low",
    },
}


class ToolCatalog:
    def __init__(self, specs: list[ToolSpec]):
        self.specs = specs

    @classmethod
    def from_tools(cls, tools: list[Any]) -> "ToolCatalog":
        return build_tool_catalog(tools)

    def get(self, name: str) -> ToolSpec | None:
        return next((spec for spec in self.specs if spec.name == name), None)

    def names(self) -> list[str]:
        return [spec.name for spec in self.specs]

    def select_names(self, names: list[str]) -> list[Any]:
        name_set = set(names)
        return [spec.tool for spec in self.specs if spec.name in name_set]

    def select_domains(self, domains: list[str]) -> list[Any]:
        domain_set = set(domains)
        return [spec.tool for spec in self.specs if spec.domain in domain_set]

    def describe_for_planner(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "domain": spec.domain,
                "capability": spec.capability,
                "risk_level": spec.risk_level,
                "owner_worker": spec.owner_worker,
                "requires_confirmation": spec.requires_confirmation,
            }
            for spec in self.specs
        ]


def build_tool_catalog(tools: list[Any]) -> ToolCatalog:
    return ToolCatalog([_build_tool_spec(tool) for tool in tools])


def _build_tool_spec(tool: Any) -> ToolSpec:
    name = str(getattr(tool, "name", type(tool).__name__))
    metadata = KNOWN_TOOL_METADATA.get(name, {})
    description = str(getattr(tool, "description", "") or "")
    return ToolSpec(
        name=name,
        tool=tool,
        description=description,
        domain=str(metadata.get("domain", "general")),
        capability=str(metadata.get("capability", "general")),
        risk_level=str(metadata.get("risk_level", "low")),
        owner_worker=str(metadata.get("owner_worker", "general_worker")),
        requires_confirmation=bool(metadata.get("requires_confirmation", False)),
    )
