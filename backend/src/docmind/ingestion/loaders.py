"""Text extraction for PDF, DOCX, Markdown, plain text and HTML sources."""

from __future__ import annotations

import io
import re
from collections.abc import Callable
from pathlib import PurePath

from bs4 import BeautifulSoup

from docmind.domain import ExtractedDocument, Section
from docmind.errors import ExtractionError, UnsupportedDocumentError

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MARKDOWN = "text/markdown"
PLAIN = "text/plain"
HTML = "text/html"

SUPPORTED_MIME_TYPES = (PDF, DOCX, MARKDOWN, PLAIN, HTML)

_EXTENSIONS = {
    ".pdf": PDF,
    ".docx": DOCX,
    ".md": MARKDOWN,
    ".markdown": MARKDOWN,
    ".mdx": MARKDOWN,
    ".txt": PLAIN,
    ".text": PLAIN,
    ".html": HTML,
    ".htm": HTML,
}

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_WS = re.compile(r"[ \t\f\v]+")
_BLANKS = re.compile(r"\n{3,}")


def detect_mime_type(filename: str | None, content_type: str | None, data: bytes) -> str:
    """Best-effort MIME detection: magic bytes first, then extension, then declared type."""
    if data.startswith(b"%PDF-"):
        return PDF
    ext = PurePath(filename or "").suffix.lower()
    if ext in _EXTENSIONS:
        return _EXTENSIONS[ext]
    declared = (content_type or "").split(";")[0].strip().lower()
    if declared in SUPPORTED_MIME_TYPES:
        return declared
    if declared in {"application/xhtml+xml"}:
        return HTML
    if data.startswith(b"PK\x03\x04") and b"word/" in data[:4096]:
        return DOCX
    raise UnsupportedDocumentError(
        f"Unsupported document type ({declared or ext or 'unknown'}). "
        "Supported: PDF, DOCX, Markdown, plain text, HTML."
    )


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    text = "\n".join(_WS.sub(" ", line).strip() for line in text.split("\n"))
    return _BLANKS.sub("\n\n", text).strip()


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1251", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ExtractionError("Could not decode text")  # pragma: no cover - latin-1 never fails


def _title_from(filename: str | None, fallback: str = "Untitled") -> str:
    if not filename:
        return fallback
    stem = PurePath(filename).stem
    return stem.replace("_", " ").replace("-", " ").strip() or fallback


def load_markdown(data: bytes, filename: str | None = None) -> ExtractedDocument:
    text = _decode(data)
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []  # (level, heading) breadcrumbs
    buffer: list[str] = []
    title: str | None = None
    in_code = False

    def flush() -> None:
        body = normalize_text("\n".join(buffer))
        if body:
            path = " › ".join(h for level, h in stack if level > 1 or len(stack) == 1)
            sections.append(Section(text=body, heading=path or None))
        buffer.clear()

    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
        match = None if in_code else _MD_HEADING.match(line)
        if match:
            flush()
            level, heading = len(match.group(1)), match.group(2).strip()
            if level == 1 and title is None:
                title = heading
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading))
            continue
        buffer.append(line)
    flush()
    return ExtractedDocument(
        title=title or _title_from(filename), sections=sections, mime_type=MARKDOWN
    )


def load_plain_text(data: bytes, filename: str | None = None) -> ExtractedDocument:
    body = normalize_text(_decode(data))
    sections = [Section(text=body)] if body else []
    return ExtractedDocument(title=_title_from(filename), sections=sections, mime_type=PLAIN)


def load_pdf(data: bytes, filename: str | None = None) -> ExtractedDocument:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        sections = []
        for page_no, page in enumerate(reader.pages, start=1):
            body = normalize_text(page.extract_text() or "")
            if body:
                sections.append(Section(text=body, page=page_no))
        meta_title = (reader.metadata.title if reader.metadata else None) or None
    except (PdfReadError, ValueError, KeyError) as exc:
        raise ExtractionError(f"Could not read PDF: {exc}") from exc
    return ExtractedDocument(
        title=str(meta_title).strip() if meta_title else _title_from(filename),
        sections=sections,
        mime_type=PDF,
    )


def load_docx(data: bytes, filename: str | None = None) -> ExtractedDocument:
    import docx

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # python-docx raises a zoo of zip/xml errors
        raise ExtractionError(f"Could not read DOCX: {exc}") from exc

    sections: list[Section] = []
    heading: str | None = None
    buffer: list[str] = []
    title = (document.core_properties.title or "").strip() or None

    def flush() -> None:
        body = normalize_text("\n".join(buffer))
        if body:
            sections.append(Section(text=body, heading=heading))
        buffer.clear()

    for paragraph in document.paragraphs:
        style = (paragraph.style.name if paragraph.style is not None else "") or ""
        text = paragraph.text.strip()
        if not text:
            continue
        if style == "Title" and title is None:
            title = text
        elif style.startswith("Heading"):
            flush()
            heading = text
        else:
            buffer.append(text)
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                buffer.append(" | ".join(cells))
    flush()
    return ExtractedDocument(
        title=title or _title_from(filename), sections=sections, mime_type=DOCX
    )


def load_html(data: bytes, filename: str | None = None) -> ExtractedDocument:
    soup = BeautifulSoup(_decode(data), "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None
    root = soup.find("main") or soup.find("article") or soup.body or soup

    sections: list[Section] = []
    heading: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        body = normalize_text("\n".join(buffer))
        if body:
            sections.append(Section(text=body, heading=heading))
        buffer.clear()

    for element in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "pre", "td", "blockquote"]):
        text = element.get_text(" ", strip=True)
        if not text:
            continue
        if element.name in {"h1", "h2", "h3", "h4"}:
            flush()
            heading = text
            if element.name == "h1" and not title:
                title = text
        else:
            buffer.append(text)
    flush()
    if not sections:  # pages without semantic markup
        body = normalize_text(root.get_text("\n"))
        if body:
            sections.append(Section(text=body))
    return ExtractedDocument(
        title=title or _title_from(filename), sections=sections, mime_type=HTML
    )


_LOADERS: dict[str, Callable[[bytes, str | None], ExtractedDocument]] = {
    PDF: load_pdf,
    DOCX: load_docx,
    MARKDOWN: load_markdown,
    PLAIN: load_plain_text,
    HTML: load_html,
}


def extract(data: bytes, *, mime_type: str, filename: str | None = None) -> ExtractedDocument:
    loader = _LOADERS.get(mime_type)
    if loader is None:
        raise UnsupportedDocumentError(f"No loader for {mime_type}")
    document = loader(data, filename)
    if not document.sections:
        raise ExtractionError("No extractable text found (scanned PDF or empty document?)")
    return document
