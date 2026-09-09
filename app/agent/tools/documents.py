from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from app.document_tools.service import DocumentConversionService


def build_document_tools(user_id: str, service: DocumentConversionService) -> list[Any]:
    def result_payload(result: Any) -> dict[str, Any]:
        return {"message": result.message, "attachment": result.attachment}

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
        return result_payload(result)

    @tool("word_create")
    async def word_create(
        filename: str = "",
        title: str = "",
        blocks: list[dict[str, Any]] | None = None,
        style: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a Word .docx file with headings, paragraphs, tables, and basic formatting."""
        return result_payload(
            service.create_word(
                user_id=user_id,
                filename=filename,
                title=title,
                blocks=blocks,
                style=style,
            )
        )

    @tool("word_read")
    async def word_read(file_id: str) -> dict[str, Any]:
        """Read text and tables from a Word .docx file owned by the current user."""
        return service.read_word(user_id=user_id, file_id=file_id)

    @tool("word_format")
    async def word_format(
        file_id: str,
        style: dict[str, Any],
        filename: str = "",
    ) -> dict[str, Any]:
        """Apply basic Word formatting such as font, size, alignment, and line spacing."""
        return result_payload(service.format_word(user_id=user_id, file_id=file_id, style=style, filename=filename))

    @tool("word_edit_text")
    async def word_edit_text(
        file_id: str,
        replacements: list[dict[str, str]],
        filename: str = "",
    ) -> dict[str, Any]:
        """Replace text in Word paragraphs and table cells, then save a new .docx file."""
        return result_payload(
            service.edit_word_text(
                user_id=user_id,
                file_id=file_id,
                replacements=replacements,
                filename=filename,
            )
        )

    @tool("excel_create")
    async def excel_create(
        filename: str = "",
        sheets: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create an Excel .xlsx workbook with one or more sheets and rows."""
        return result_payload(service.create_excel(user_id=user_id, filename=filename, sheets=sheets))

    @tool("excel_read")
    async def excel_read(file_id: str) -> dict[str, Any]:
        """Read workbook sheets and cell values from an Excel file owned by the current user."""
        return service.read_excel(user_id=user_id, file_id=file_id)

    @tool("excel_calculate")
    async def excel_calculate(
        file_id: str,
        operations: list[dict[str, Any]],
        filename: str = "",
    ) -> dict[str, Any]:
        """Apply Excel calculations such as formulas and summary operations, then save a new workbook."""
        return result_payload(
            service.calculate_excel(
                user_id=user_id,
                file_id=file_id,
                operations=operations,
                filename=filename,
            )
        )

    @tool("excel_format_table")
    async def excel_format_table(
        file_id: str,
        sheet: str,
        range_ref: str,
        filename: str = "",
    ) -> dict[str, Any]:
        """Format a cell range as an Excel table with header styling and row stripes."""
        return result_payload(
            service.format_excel_table(
                user_id=user_id,
                file_id=file_id,
                sheet=sheet,
                range_ref=range_ref,
                filename=filename,
            )
        )

    @tool("pdf_create")
    async def pdf_create(
        filename: str = "",
        title: str = "",
        blocks: list[dict[str, Any]] | None = None,
        page: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a PDF file with headings, paragraphs, tables, and basic page settings."""
        return result_payload(
            service.create_pdf(
                user_id=user_id,
                filename=filename,
                title=title,
                blocks=blocks,
                page=page,
            )
        )

    @tool("pdf_read")
    async def pdf_read(file_id: str) -> dict[str, Any]:
        """Extract text from a PDF file owned by the current user."""
        return service.read_pdf(user_id=user_id, file_id=file_id)

    return [
        convert_uploaded_file,
        word_create,
        word_read,
        word_format,
        word_edit_text,
        excel_create,
        excel_read,
        excel_calculate,
        excel_format_table,
        pdf_create,
        pdf_read,
    ]
