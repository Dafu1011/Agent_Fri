from __future__ import annotations

from typing import Any

from .schemas import DocumentConversionError
from .service import DocumentConversionService


DOCUMENT_CONVERSION_KEYWORDS = (
    "转换",
    "转成",
    "转为",
    "转pdf",
    "转 pdf",
    "转word",
    "转 word",
    "pdf",
    "word",
    "docx",
    "扫描",
    "识别",
    "ocr",
)


def is_document_conversion_request(message: str, file_ids: list[str]) -> bool:
    if not file_ids:
        return False
    lowered = message.lower().replace(" ", "")
    return any(keyword.replace(" ", "") in lowered for keyword in DOCUMENT_CONVERSION_KEYWORDS)


async def parse_document_message(
    message: str,
    file_ids: list[str],
    user_id: str,
    service: DocumentConversionService,
) -> dict[str, Any] | None:
    if not is_document_conversion_request(message, file_ids):
        return None
    try:
        result = service.convert(user_id=user_id, file_ids=file_ids, instruction=message)
    except DocumentConversionError as exc:
        return {"reply": f"转换失败：{exc.message}", "attachments": []}
    return {"reply": result.message, "attachments": [result.attachment]}
