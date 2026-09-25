from __future__ import annotations

import itertools

import pytest

from docmind.domain import ExtractedDocument, Section
from docmind.errors import ExtractionError, UnsupportedDocumentError
from docmind.ingestion.chunking import chunk_document, split_text
from docmind.ingestion.loaders import (
    DOCX,
    HTML,
    MARKDOWN,
    PDF,
    PLAIN,
    detect_mime_type,
    extract,
    normalize_text,
)
from tests.helpers import make_docx, make_pdf

LOREM = " ".join(
    f"Sentence number {i} talks about vacation days, laptops and onboarding." for i in range(60)
)


class TestSplitText:
    def test_short_text_is_single_chunk(self) -> None:
        assert [(s.start, s.end) for s in split_text("hello world", 100, 10)] == [(0, 11)]

    @pytest.mark.parametrize(("size", "overlap"), [(120, 0), (200, 40), (500, 120)])
    def test_chunks_respect_size_and_cover_text(self, size: int, overlap: int) -> None:
        spans = split_text(LOREM, size, overlap)
        assert all(s.end - s.start <= size for s in spans)
        assert spans[0].start == 0
        assert spans[-1].end == len(LOREM.rstrip())
        # coverage: every gap between consecutive chunks is whitespace only
        for prev, nxt in itertools.pairwise(spans):
            assert nxt.start > prev.start, "must make progress"
            assert LOREM[prev.end : nxt.start].strip() == "" or nxt.start < prev.end

    def test_overlap_repeats_context(self) -> None:
        spans = split_text(LOREM, 200, 80)
        overlaps = [prev.end - nxt.start for prev, nxt in itertools.pairwise(spans)]
        assert any(o > 0 for o in overlaps)
        assert all(o <= 80 for o in overlaps)

    def test_prefers_paragraph_boundaries(self) -> None:
        text = ("A" * 50 + ".\n\n") + ("B" * 50 + ".\n\n") + ("C" * 50 + ".")
        chunks = [text[s.start : s.end] for s in split_text(text, 110, 0)]
        assert chunks[0].endswith(".")
        assert "C" not in chunks[0]

    def test_hard_split_for_unbreakable_text(self) -> None:
        spans = split_text("x" * 250, 100, 0)
        assert [s.end - s.start for s in spans] == [100, 100, 50]

    @pytest.mark.parametrize(("size", "overlap"), [(0, 0), (100, 100), (100, -1)])
    def test_invalid_arguments(self, size: int, overlap: int) -> None:
        with pytest.raises(ValueError, match="chunk_"):
            split_text("text", size, overlap)


def test_chunk_document_keeps_offsets_and_metadata() -> None:
    doc = ExtractedDocument(
        title="T",
        sections=[Section(text=LOREM, heading="Time off", page=3)],
        mime_type=PLAIN,
    )
    chunks = chunk_document(doc, "doc_1", chunk_size=300, chunk_overlap=50)
    assert len(chunks) > 3
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert len({c.id for c in chunks}) == len(chunks)
    for chunk in chunks:
        assert LOREM[chunk.start : chunk.end] == chunk.text
        assert chunk.heading == "Time off"
        assert chunk.page == 3


class TestLoaders:
    def test_markdown_sections_and_breadcrumbs(self, handbook_md: bytes) -> None:
        doc = extract(handbook_md, mime_type=MARKDOWN, filename="handbook.md")
        assert doc.title == "Lumenfold Labs Employee Handbook"
        headings = [s.heading for s in doc.sections]
        assert "Time off › Paid vacation" in headings
        vacation = next(s for s in doc.sections if s.heading == "Time off › Paid vacation")
        assert "25 working days" in vacation.text

    def test_markdown_ignores_hashes_in_code_blocks(self) -> None:
        md = b"# Title\n\n## Setup\n\n```bash\n# not a heading\npip install x\n```\n"
        doc = extract(md, mime_type=MARKDOWN)
        assert [s.heading for s in doc.sections] == ["Setup"]
        assert "# not a heading" in doc.sections[0].text

    def test_pdf_pages(self) -> None:
        data = make_pdf(["Vacation is 25 days per year.", "Laptops are replaced every 3 years."])
        doc = extract(data, mime_type=PDF, filename="policy.pdf")
        assert [s.page for s in doc.sections] == [1, 2]
        assert "25 days" in doc.sections[0].text
        assert doc.title == "policy"

    def test_pdf_title_from_metadata(self) -> None:
        doc = extract(make_pdf(["Hello"], title="Travel Policy"), mime_type=PDF)
        assert doc.title == "Travel Policy"

    def test_corrupt_pdf_raises_extraction_error(self) -> None:
        with pytest.raises(ExtractionError):
            extract(b"%PDF-1.4 garbage", mime_type=PDF)

    def test_docx_headings_paragraphs_tables(self) -> None:
        data = make_docx(
            "Remote Work Policy",
            {"Eligibility": ["Everyone may work remotely."], "Budget": ["Ask People Ops."]},
        )
        doc = extract(data, mime_type=DOCX, filename="remote.docx")
        assert doc.title == "Remote Work Policy"
        assert [s.heading for s in doc.sections][:2] == ["Eligibility", "Budget"]
        assert "600 EUR" in doc.sections[-1].text

    def test_html_strips_chrome_and_scripts(self) -> None:
        html = (
            b"<html><head><title>Guide</title><style>p{}</style></head><body>"
            b"<nav>Menu</nav><main><h2>Install</h2><p>Run the installer.</p>"
            b"<script>evil()</script></main><footer>(c)</footer></body></html>"
        )
        doc = extract(html, mime_type=HTML)
        assert doc.title == "Guide"
        assert doc.sections[0].heading == "Install"
        text = " ".join(s.text for s in doc.sections)
        assert "evil" not in text and "Menu" not in text

    def test_plain_text_cp1251_fallback(self) -> None:
        doc = extract("Привет, мир".encode("cp1251"), mime_type=PLAIN, filename="note.txt")
        assert doc.sections[0].text == "Привет, мир"

    def test_empty_document_rejected(self) -> None:
        with pytest.raises(ExtractionError):
            extract(b"   \n\n ", mime_type=PLAIN)


@pytest.mark.parametrize(
    ("filename", "content_type", "data", "expected"),
    [
        ("a.pdf", None, b"%PDF-1.7 ...", PDF),
        ("renamed.bin", None, b"%PDF-1.7 ...", PDF),
        ("notes.md", "application/octet-stream", b"# hi", MARKDOWN),
        ("page", "text/html; charset=utf-8", b"<html>", HTML),
        (None, "text/plain", b"hi", PLAIN),
        ("x.docx", None, b"PK\x03\x04", DOCX),
    ],
)
def test_detect_mime_type(
    filename: str | None, content_type: str | None, data: bytes, expected: str
) -> None:
    assert detect_mime_type(filename, content_type, data) == expected


def test_detect_mime_type_rejects_unknown() -> None:
    with pytest.raises(UnsupportedDocumentError):
        detect_mime_type("image.png", "image/png", b"\x89PNG")


def test_normalize_text() -> None:
    assert normalize_text("a  b\r\n\r\n\r\n\r\nc  ") == "a b\n\nc"
