from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile

from app.config import settings

from .engines.image_pdf import ImagePdfConverter
from .excel import ExcelToolService
from .pdf import PdfToolService
from .schemas import ConversionPlan, ConversionResult, DocumentConversionError, StoredDocument
from .storage import DocumentStorage
from .word import WordToolService


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
OFFICE_SUFFIXES = {
    ".doc",
    ".docx",
    ".odt",
    ".rtf",
    ".ppt",
    ".pptx",
    ".odp",
    ".xls",
    ".xlsx",
    ".ods",
}


def infer_conversion_plan(filenames: list[str], instruction: str = "", target_format: str = "") -> ConversionPlan:
    if not filenames:
        raise DocumentConversionError("请先上传需要转换的文件。")
    suffixes = {Path(filename).suffix.lower() for filename in filenames}
    normalized_target = target_format.strip().lower().lstrip(".")
    lowered_instruction = instruction.lower()
    wants_pdf = normalized_target == "pdf" or "pdf" in lowered_instruction
    wants_word = normalized_target in {"docx", "word"} or "word" in lowered_instruction or "文档" in lowered_instruction
    wants_ocr = any(keyword in lowered_instruction for keyword in ("ocr", "扫描", "识别", "可搜索"))

    if suffixes <= IMAGE_SUFFIXES and wants_pdf:
        return ConversionPlan(operation="images_to_pdf", target_format="pdf", output_suffix=".pdf")
    if suffixes <= IMAGE_SUFFIXES and wants_word:
        return ConversionPlan(operation="image_ocr_to_docx", target_format="docx", output_suffix=".docx")
    if suffixes == {".pdf"} and wants_ocr:
        return ConversionPlan(operation="ocr_pdf", target_format="pdf", output_suffix=".pdf")
    if suffixes == {".pdf"} and wants_word:
        return ConversionPlan(operation="pdf_to_docx", target_format="docx", output_suffix=".docx")
    if len(suffixes) == 1 and next(iter(suffixes)) in OFFICE_SUFFIXES and wants_pdf:
        return ConversionPlan(operation="office_to_pdf", target_format="pdf", output_suffix=".pdf")

    raise DocumentConversionError("暂不支持这个文件类型和转换要求的组合。")


def output_filename(source: StoredDocument, suffix: str) -> str:
    return f"{Path(source.filename).stem}{suffix}"


class DocumentConversionService:
    def __init__(
        self,
        storage: DocumentStorage,
        *,
        image_pdf_converter: ImagePdfConverter | None = None,
    ):
        self.storage = storage
        self.image_pdf_converter = image_pdf_converter or ImagePdfConverter()
        self.word = WordToolService(storage)
        self.excel = ExcelToolService(storage)
        self.pdf = PdfToolService(storage)

    def convert(
        self,
        *,
        user_id: str,
        file_ids: list[str],
        instruction: str = "",
        target_format: str = "",
    ) -> ConversionResult:
        files = self._load_files(user_id, file_ids)
        plan = infer_conversion_plan(
            [file.filename for file in files],
            instruction=instruction,
            target_format=target_format,
        )
        if plan.operation == "images_to_pdf":
            return self._images_to_pdf(user_id, files, plan)
        if plan.operation == "office_to_pdf":
            return self._office_to_pdf(user_id, files[0], plan)
        if plan.operation == "pdf_to_docx":
            return self._pdf_to_docx(user_id, files[0], plan)
        if plan.operation == "ocr_pdf":
            return self._ocr_pdf(user_id, files[0], plan)
        if plan.operation == "image_ocr_to_docx":
            return self._image_ocr_to_docx(user_id, files, plan)
        raise DocumentConversionError("暂不支持这个转换任务。")

    def _load_files(self, user_id: str, file_ids: list[str]) -> list[StoredDocument]:
        unique_file_ids = [file_id for index, file_id in enumerate(file_ids) if file_id and file_id not in file_ids[:index]]
        files = [self.storage.get_file(user_id, file_id) for file_id in unique_file_ids]
        if not files or any(file is None for file in files):
            raise DocumentConversionError("找不到上传文件，请重新上传后再试。", status_code=404)
        return [file for file in files if file is not None]

    def create_word(
        self,
        *,
        user_id: str,
        filename: str = "",
        title: str = "",
        blocks: list[dict] | None = None,
        style: dict | None = None,
    ) -> ConversionResult:
        return self.word.create(user_id=user_id, filename=filename, title=title, blocks=blocks, style=style)

    def read_word(self, *, user_id: str, file_id: str) -> dict:
        return self.word.read(user_id=user_id, file_id=file_id)

    def edit_word_text(
        self,
        *,
        user_id: str,
        file_id: str,
        replacements: list[dict[str, str]],
        filename: str = "",
    ) -> ConversionResult:
        return self.word.edit_text(user_id=user_id, file_id=file_id, replacements=replacements, filename=filename)

    def format_word(
        self,
        *,
        user_id: str,
        file_id: str,
        style: dict,
        filename: str = "",
    ) -> ConversionResult:
        return self.word.format(user_id=user_id, file_id=file_id, style=style, filename=filename)

    def create_excel(
        self,
        *,
        user_id: str,
        filename: str = "",
        sheets: list[dict] | None = None,
    ) -> ConversionResult:
        return self.excel.create(user_id=user_id, filename=filename, sheets=sheets)

    def read_excel(self, *, user_id: str, file_id: str) -> dict:
        return self.excel.read(user_id=user_id, file_id=file_id)

    def calculate_excel(
        self,
        *,
        user_id: str,
        file_id: str,
        operations: list[dict],
        filename: str = "",
    ) -> ConversionResult:
        return self.excel.calculate(user_id=user_id, file_id=file_id, operations=operations, filename=filename)

    def format_excel_table(
        self,
        *,
        user_id: str,
        file_id: str,
        sheet: str,
        range_ref: str,
        filename: str = "",
    ) -> ConversionResult:
        return self.excel.format_table(
            user_id=user_id,
            file_id=file_id,
            sheet=sheet,
            range_ref=range_ref,
            filename=filename,
        )

    def create_pdf(
        self,
        *,
        user_id: str,
        filename: str = "",
        title: str = "",
        blocks: list[dict] | None = None,
        page: dict | None = None,
    ) -> ConversionResult:
        return self.pdf.create(user_id=user_id, filename=filename, title=title, blocks=blocks, page=page)

    def read_pdf(self, *, user_id: str, file_id: str) -> dict:
        return self.pdf.read(user_id=user_id, file_id=file_id)

    def _resolve_executable(self, configured_path: str, *names: str) -> str | None:
        configured = configured_path.strip().strip('"')
        if configured:
            if Path(configured).exists() or shutil.which(configured):
                return configured
            return None
        for name in names:
            executable = shutil.which(name)
            if executable:
                return executable
        return None

    def _images_to_pdf(
        self,
        user_id: str,
        files: list[StoredDocument],
        plan: ConversionPlan,
    ) -> ConversionResult:
        filename = output_filename(files[0], plan.output_suffix) if len(files) == 1 else "images.pdf"
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / filename
            self.image_pdf_converter.convert([file.path for file in files], output_path)
            return self._store_result(
                user_id=user_id,
                filename=filename,
                mime_type="application/pdf",
                content=output_path.read_bytes(),
                operation=plan.operation,
                message="已转换为 PDF。",
            )

    def _office_to_pdf(
        self,
        user_id: str,
        file: StoredDocument,
        plan: ConversionPlan,
    ) -> ConversionResult:
        executable = self._resolve_executable(settings.document_libreoffice_path, "soffice", "libreoffice")
        if not executable:
            raise DocumentConversionError("服务器未安装 LibreOffice，暂时无法把 Office 文档转换为 PDF。", status_code=503)
        filename = output_filename(file, plan.output_suffix)
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            completed = subprocess.run(
                [
                    executable,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(temp_path),
                    str(file.path),
                ],
                capture_output=True,
                text=True,
                timeout=max(1, settings.document_conversion_timeout_seconds),
                check=False,
            )
            output_path = temp_path / filename
            if completed.returncode != 0 or not output_path.exists():
                detail = (completed.stderr or completed.stdout).strip()
                raise DocumentConversionError(f"LibreOffice 转换失败：{detail or completed.returncode}", status_code=500)
            return self._store_result(
                user_id=user_id,
                filename=filename,
                mime_type="application/pdf",
                content=output_path.read_bytes(),
                operation=plan.operation,
                message="已转换为 PDF。",
            )

    def _pdf_to_docx(
        self,
        user_id: str,
        file: StoredDocument,
        plan: ConversionPlan,
    ) -> ConversionResult:
        try:
            from pdf2docx import Converter
        except ImportError as exc:
            raise DocumentConversionError("服务器未安装 pdf2docx，暂时无法把 PDF 转为 Word。", status_code=503) from exc

        filename = output_filename(file, plan.output_suffix)
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / filename
            converter = Converter(str(file.path))
            try:
                converter.convert(str(output_path))
            finally:
                converter.close()
            return self._store_result(
                user_id=user_id,
                filename=filename,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=output_path.read_bytes(),
                operation=plan.operation,
                message="已尽量转换为 Word，复杂版式可能需要人工微调。",
            )

    def _ocr_pdf(
        self,
        user_id: str,
        file: StoredDocument,
        plan: ConversionPlan,
    ) -> ConversionResult:
        executable = self._resolve_executable(settings.document_ocrmypdf_path, "ocrmypdf")
        if not executable:
            raise DocumentConversionError("服务器未安装 OCRmyPDF/Tesseract，暂时无法生成可搜索 PDF。", status_code=503)
        filename = output_filename(file, plan.output_suffix)
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / filename
            completed = subprocess.run(
                [executable, "-l", settings.document_ocr_languages, "--deskew", str(file.path), str(output_path)],
                capture_output=True,
                text=True,
                timeout=max(1, settings.document_ocr_timeout_seconds),
                check=False,
            )
            if completed.returncode != 0 or not output_path.exists():
                detail = (completed.stderr or completed.stdout).strip()
                raise DocumentConversionError(f"OCR 转换失败：{detail or completed.returncode}", status_code=500)
            return self._store_result(
                user_id=user_id,
                filename=filename,
                mime_type="application/pdf",
                content=output_path.read_bytes(),
                operation=plan.operation,
                message="已生成可搜索 PDF。",
            )

    def _image_ocr_to_docx(
        self,
        user_id: str,
        files: list[StoredDocument],
        plan: ConversionPlan,
    ) -> ConversionResult:
        executable = self._resolve_executable(settings.document_tesseract_path, "tesseract")
        if not executable:
            raise DocumentConversionError("服务器未安装 Tesseract，暂时无法把图片识别为 Word。", status_code=503)
        try:
            from docx import Document
        except ImportError as exc:
            raise DocumentConversionError("服务器未安装 python-docx，暂时无法生成 Word。", status_code=503) from exc
        filename = output_filename(files[0], plan.output_suffix) if len(files) == 1 else "ocr-result.docx"
        document = Document()
        for file in files:
            completed = subprocess.run(
                [executable, str(file.path), "stdout", "-l", settings.document_ocr_languages],
                capture_output=True,
                text=True,
                timeout=max(1, settings.document_ocr_timeout_seconds),
                check=False,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()
                raise DocumentConversionError(f"Tesseract 识别失败：{detail or completed.returncode}", status_code=500)
            document.add_paragraph(completed.stdout.strip())
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / filename
            document.save(output_path)
            return self._store_result(
                user_id=user_id,
                filename=filename,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=output_path.read_bytes(),
                operation=plan.operation,
                message="已识别图片内容并生成 Word。",
            )

    def _store_result(
        self,
        *,
        user_id: str,
        filename: str,
        mime_type: str,
        content: bytes,
        operation: str,
        message: str,
    ) -> ConversionResult:
        stored = self.storage.write_file(
            user_id=user_id,
            filename=filename,
            mime_type=mime_type,
            content=content,
            kind="conversion",
        )
        download_url = f"/documents/files/{stored.file_id}/download"
        return ConversionResult(
            file_id=stored.file_id,
            filename=stored.filename,
            mime_type=stored.mime_type,
            size_bytes=stored.size_bytes,
            download_url=download_url,
            preview_url=download_url,
            operation=operation,
            message=message,
        )
