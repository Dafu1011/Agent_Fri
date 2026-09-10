from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.document_tools.schemas import DocumentConversionError, StoredDocument


INGESTION_KEYWORDS = (
    "知识库",
    "资料库",
    "入库",
    "加入知识",
    "导入知识",
    "解析到知识",
    "加入资料",
    "导入资料",
)

TEXT_SUFFIXES = {".txt", ".md", ".csv"}
WORD_SUFFIXES = {".docx"}
PDF_SUFFIXES = {".pdf"}
EXCEL_SUFFIXES = {".xlsx"}


@dataclass(frozen=True)
class ExtractedFileText:
    title: str
    text: str
    source: str


@dataclass(frozen=True)
class KnowledgeIngestionItem:
    file_id: str
    filename: str
    status: str
    document_id: str = ""
    title: str = ""
    message: str = ""
    error: str = ""

    @property
    def attachment(self) -> dict[str, Any]:
        return {
            "platform": "knowledge",
            "media_type": "knowledge_document",
            "file_id": self.file_id,
            "document_id": self.document_id,
            "filename": self.filename,
            "title": self.title or self.filename,
            "status": self.status,
            "message": self.message or self.error,
        }


@dataclass(frozen=True)
class KnowledgeIngestionResponse:
    reply: str
    results: list[KnowledgeIngestionItem]

    @property
    def attachments(self) -> list[dict[str, Any]]:
        return [item.attachment for item in self.results]


def is_knowledge_ingestion_request(message: str, file_ids: list[str]) -> bool:
    if not file_ids:
        return False
    normalized = message.lower().replace(" ", "")
    return any(keyword.replace(" ", "") in normalized for keyword in INGESTION_KEYWORDS)


class FileTextExtractor:
    def __init__(self, service: Any):
        self.service = service

    def extract(self, user_id: str, stored: StoredDocument) -> ExtractedFileText:
        suffix = Path(stored.filename).suffix.lower()
        if suffix in TEXT_SUFFIXES or stored.mime_type.startswith("text/"):
            return ExtractedFileText(
                title=stored.filename,
                text=stored.path.read_text(encoding="utf-8", errors="replace"),
                source=f"upload:{stored.file_id}:{stored.filename}",
            )
        if suffix in PDF_SUFFIXES or stored.mime_type == "application/pdf":
            return self._extract_pdf(user_id, stored)
        if suffix in WORD_SUFFIXES:
            return self._extract_word(user_id, stored)
        if suffix in EXCEL_SUFFIXES:
            return self._extract_excel(user_id, stored)
        raise DocumentConversionError(f"暂不支持将 {stored.filename} 解析到知识库。")

    def _extract_pdf(self, user_id: str, stored: StoredDocument) -> ExtractedFileText:
        if self.service is None:
            raise DocumentConversionError("服务器暂时无法读取 PDF 文件。", status_code=503)
        result = self.service.read_pdf(user_id=user_id, file_id=stored.file_id)
        return ExtractedFileText(
            title=str(result.get("filename") or stored.filename),
            text=str(result.get("text") or ""),
            source=f"upload:{stored.file_id}:{stored.filename}",
        )

    def _extract_word(self, user_id: str, stored: StoredDocument) -> ExtractedFileText:
        if self.service is None:
            raise DocumentConversionError("服务器暂时无法读取 Word 文件。", status_code=503)
        result = self.service.read_word(user_id=user_id, file_id=stored.file_id)
        parts = [str(result.get("text") or "")]
        for table in result.get("tables") or []:
            parts.append(_stringify_table(table))
        return ExtractedFileText(
            title=str(result.get("filename") or stored.filename),
            text="\n\n".join(part for part in parts if part.strip()),
            source=f"upload:{stored.file_id}:{stored.filename}",
        )

    def _extract_excel(self, user_id: str, stored: StoredDocument) -> ExtractedFileText:
        if self.service is None:
            raise DocumentConversionError("服务器暂时无法读取 Excel 文件。", status_code=503)
        result = self.service.read_excel(user_id=user_id, file_id=stored.file_id)
        sheets = result.get("sheets") or {}
        parts = []
        for sheet_name, rows in sheets.items():
            parts.append(f"# Sheet: {sheet_name}")
            parts.append(_stringify_table(rows))
        return ExtractedFileText(
            title=str(result.get("filename") or stored.filename),
            text="\n\n".join(part for part in parts if part.strip()),
            source=f"upload:{stored.file_id}:{stored.filename}",
        )


class KnowledgeIngestionService:
    def __init__(
        self,
        *,
        storage: Any,
        document_service: Any,
        knowledge_repository: Any,
        extractor: FileTextExtractor | None = None,
    ):
        self.storage = storage
        self.document_service = document_service
        self.knowledge_repository = knowledge_repository
        self.extractor = extractor or FileTextExtractor(document_service)

    def ingest_files(
        self,
        *,
        user_id: str,
        file_ids: list[str],
        instruction: str = "",
        visibility: str = "private",
    ) -> KnowledgeIngestionResponse:
        del instruction
        results: list[KnowledgeIngestionItem] = []
        for file_id in _unique_values(file_ids):
            results.append(self._ingest_one(user_id=user_id, file_id=file_id, visibility=visibility))
        return KnowledgeIngestionResponse(reply=_format_reply(results), results=results)

    def _ingest_one(self, *, user_id: str, file_id: str, visibility: str) -> KnowledgeIngestionItem:
        stored = self.storage.get_file(user_id, file_id)
        if stored is None:
            return KnowledgeIngestionItem(
                file_id=file_id,
                filename="",
                status="failed",
                error="找不到上传文件，请重新上传后再试。",
            )
        try:
            extracted = self.extractor.extract(user_id, stored)
            if not extracted.text.strip():
                raise DocumentConversionError("文件没有可入库的文本内容。")
            document = self.knowledge_repository.add_document(
                owner_user_id=user_id,
                title=extracted.title,
                content=extracted.text,
                source=extracted.source,
                visibility=visibility,
            )
            return KnowledgeIngestionItem(
                file_id=stored.file_id,
                filename=stored.filename,
                status="ingested",
                document_id=str(document.id),
                title=str(getattr(document, "title", extracted.title)),
                message="已解析到知识库。",
            )
        except DocumentConversionError as exc:
            return KnowledgeIngestionItem(
                file_id=stored.file_id,
                filename=stored.filename,
                status="failed",
                error=exc.message,
            )
        except Exception as exc:
            return KnowledgeIngestionItem(
                file_id=stored.file_id,
                filename=stored.filename,
                status="failed",
                error=str(exc),
            )


def _stringify_table(rows: Any) -> str:
    table_rows = rows if isinstance(rows, list) else []
    lines = []
    for row in table_rows:
        values = row if isinstance(row, list) else [row]
        lines.append("\t".join("" if value is None else str(value) for value in values))
    return "\n".join(lines)


def _unique_values(values: list[str]) -> list[str]:
    unique = []
    for value in values:
        if value and value not in unique:
            unique.append(value)
    return unique


def _format_reply(results: list[KnowledgeIngestionItem]) -> str:
    ingested = [item for item in results if item.status == "ingested"]
    failed = [item for item in results if item.status == "failed"]
    if ingested and not failed:
        return f"已将 {len(ingested)} 个文件解析到知识库。"
    if ingested and failed:
        return f"已将 {len(ingested)} 个文件解析到知识库，{len(failed)} 个文件失败。"
    return "没有文件成功解析到知识库。"
