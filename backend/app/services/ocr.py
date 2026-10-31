"""OCR for scanned PDF pages, using the Tesseract engine.

Needs the `tesseract` binary (apt-get install tesseract-ocr; the backend Docker image includes it)
plus the Python packages pypdfium2, pytesseract and Pillow. When any of these is missing,
`ocr_available()` is False and documents keep their `needs_ocr` data-quality issue.

OCR text can contain recognition errors, so chunks made from it are marked `extraction="ocr"` and
the document gets an `ocr_text_needs_review` issue: never import numbers from OCR text without a
human check against the original page.
"""
import io
import logging
import shutil

from app.config import get_settings

log = logging.getLogger(__name__)


def _tesseract_cmd() -> str | None:
    s = get_settings()
    return s.tesseract_cmd or shutil.which("tesseract")


def ocr_available() -> bool:
    if not get_settings().ocr_enabled or not _tesseract_cmd():
        return False
    try:
        import pypdfium2  # noqa: F401
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return True


def ocr_pdf_pages(content: bytes, pages: list[int]) -> dict[int, str]:
    """OCR the given 1-based page numbers of a PDF. Returns {page: text}."""
    import pypdfium2 as pdfium
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = _tesseract_cmd()
    langs = get_settings().ocr_languages
    pdf = pdfium.PdfDocument(io.BytesIO(content))
    out: dict[int, str] = {}
    try:
        for n in pages:
            image = pdf[n - 1].render(scale=300 / 72).to_pil()  # 300 dpi
            out[n] = pytesseract.image_to_string(image, lang=langs)
    finally:
        pdf.close()
    return out
