from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from app.document_tools.common import MIME_TYPES, ensure_suffix, store_document_result, stringify_table
from app.document_tools.schemas import ConversionResult, DocumentConversionError
from app.document_tools.storage import DocumentStorage


class PdfToolService:
    def __init__(self, storage: DocumentStorage):
        self.storage = storage

    def create(
        self,
        *,
        user_id: str,
        filename: str = "",
        title: str = "",
        blocks: list[dict[str, Any]] | None = None,
        page: dict[str, Any] | None = None,
    ) -> ConversionResult:
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4, A3, letter, landscape
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        except ImportError as exc:
            raise DocumentConversionError("服务器未安装 reportlab，暂时无法生成 PDF。", status_code=503) from exc

        page = page or {}
        page_sizes = {"A4": A4, "A3": A3, "LETTER": letter}
        pagesize = page_sizes.get(str(page.get("size") or "A4").upper(), A4)
        if str(page.get("orientation") or "").lower() == "landscape":
            pagesize = landscape(pagesize)

        buffer = BytesIO()
        document = SimpleDocTemplate(buffer, pagesize=pagesize)
        styles = getSampleStyleSheet()
        cjk_font = _register_cjk_font()
        if cjk_font:
            for style_name in ("Normal", "BodyText", "Title", "Heading1", "Heading2"):
                styles[style_name].fontName = cjk_font
        story = []
        if title:
            story.append(Paragraph(title, styles["Title"]))
            story.append(Spacer(1, 12))
        for block in blocks or []:
            block_type = str(block.get("type") or "paragraph")
            if block_type == "heading":
                level = int(block.get("level") or 1)
                story.append(Paragraph(str(block.get("text") or ""), styles["Heading1" if level <= 1 else "Heading2"]))
                story.append(Spacer(1, 8))
            elif block_type == "table":
                headers = block.get("headers") or []
                rows = block.get("rows") or []
                data = stringify_table(([headers] if headers else []) + rows)
                if data:
                    table = Table(data, repeatRows=1 if headers else 0)
                    table.setStyle(
                        TableStyle(
                            [
                                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ]
                        )
                    )
                    story.append(table)
                    story.append(Spacer(1, 10))
            else:
                text = str(block.get("text") or "").replace("\n", "<br/>")
                story.append(Paragraph(text, styles["BodyText"]))
                story.append(Spacer(1, 8))
        document.build(story or [Paragraph("", styles["BodyText"])])
        return store_document_result(
            self.storage,
            user_id=user_id,
            filename=ensure_suffix(filename, ".pdf", "document"),
            mime_type=MIME_TYPES["pdf"],
            content=buffer.getvalue(),
            operation="pdf_create",
            message="已创建 PDF 文档。",
        )

    def read(self, *, user_id: str, file_id: str) -> dict[str, Any]:
        stored = self.storage.get_file(user_id, file_id)
        if stored is None:
            raise DocumentConversionError("找不到 PDF 文件，请重新上传或生成后再试。", status_code=404)
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise DocumentConversionError("服务器未安装 pypdf，暂时无法读取 PDF。", status_code=503) from exc

        reader = PdfReader(str(stored.path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return {
            "file_id": stored.file_id,
            "filename": stored.filename,
            "text": "\n\n".join(pages),
            "pages": len(reader.pages),
        }


def _register_cjk_font() -> str | None:
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        return None

    for font_path in _candidate_cjk_fonts():
        if not font_path.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont("DocumentCJK", str(font_path)))
            return "DocumentCJK"
        except Exception:
            continue
    return None


def _candidate_cjk_fonts() -> list[Path]:
    return [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simsun.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
    ]
