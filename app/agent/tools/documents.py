from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from app.document_tools.service import DocumentConversionService


def build_document_tools(user_id: str, service: DocumentConversionService) -> list[Any]:
    @tool("convert_uploaded_file")
    async def convert_uploaded_file(
        file_ids: list[str],
        target_format: str = "",
        instruction: str = "",
    ) -> dict[str, Any]:
        """Convert files uploaded by the current user, such as image to PDF, Office to PDF, PDF to Word, or OCR output."""
        result = service.convert(
            user_id=user_id,
            file_ids=file_ids,
            instruction=instruction,
            target_format=target_format,
        )
        return {"message": result.message, "attachment": result.attachment}

    return [convert_uploaded_file]
