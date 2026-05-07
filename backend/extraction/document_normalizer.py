"""Normalizador documental minimalista — solo pymupdf.

Sin fallbacks legacy (pdftext, pdfplumber, marker, paddleocr, tesseract).
Si pymupdf no extrae texto (PDF imagen escaneada sin OCR), devuelve vacío.
Esa información se considera "vacío legítimo" — no se invierte tiempo en OCR
incierto que produce ruido.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

# Permitir imágenes muy grandes (escaneados jurídicos)
try:
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
except Exception:
    pass

logger = logging.getLogger("tutelas.normalizer")


@dataclass
class NormalizationResult:
    text: str
    method: str = "pymupdf"
    pages: int = 0
    has_ocr_pages: bool = False
    error: str | None = None
    markdown: bool = False


def _extract_pdf_pymupdf(file_path: Path) -> NormalizationResult:
    """Extrae texto de PDF usando pymupdf (PyMuPDF/fitz). Único motor."""
    try:
        import pymupdf
    except ImportError as e:
        return NormalizationResult(text="", error=f"pymupdf no instalado: {e}")

    try:
        doc = pymupdf.open(str(file_path))
        text_parts = []
        n = doc.page_count
        for i in range(n):
            text_parts.append(doc[i].get_text())
        doc.close()
        text = "\n".join(text_parts)
        return NormalizationResult(text=text, method="pymupdf", pages=n)
    except Exception as e:
        logger.warning("pymupdf falló en %s: %s", file_path.name, str(e)[:100])
        return NormalizationResult(text="", error=str(e)[:200], method="pymupdf_error")


def normalize_pdf(file_path: str | Path) -> NormalizationResult:
    """Extrae texto de PDF. Solo pymupdf (sin fallback)."""
    file_path = Path(file_path)
    if not file_path.exists():
        return NormalizationResult(text="", error=f"Archivo no existe: {file_path}")
    return _extract_pdf_pymupdf(file_path)


def normalize_image(file_path: str | Path) -> NormalizationResult:
    """Imágenes (PNG/JPG): NO se procesan en versión minimalista.

    Si necesitas OCR de imágenes, instala paddleocr+gpu y reactiva la
    funcionalidad. Para producción jurídica el 99% de docs son PDFs.
    """
    return NormalizationResult(
        text="", method="not_supported_minimal",
        error="OCR de imágenes deshabilitado en versión minimalista",
    )


def normalize_docx(file_path: str | Path) -> NormalizationResult:
    """DOCX: usa python-docx (preserva footers con abogado responsable)."""
    from backend.extraction.docx_extractor import extract_docx
    file_path = Path(file_path)
    result = extract_docx(file_path)
    if result.error:
        return NormalizationResult(text="", error=result.error)
    return NormalizationResult(text=result.text, method=f"docx_{result.method}", pages=1)


def normalize_doc(file_path: str | Path) -> NormalizationResult:
    """DOC (formato viejo Word): usa doc_extractor con antiword/olefile."""
    from backend.extraction.doc_extractor import extract_doc
    file_path = Path(file_path)
    result = extract_doc(file_path)
    if result.error:
        return NormalizationResult(text="", error=result.error)
    return NormalizationResult(text=result.text, method=f"doc_{result.method}", pages=1)


def normalize_document(file_path: str | Path) -> NormalizationResult:
    """Dispatcher por extensión. Soporta PDF, DOCX, DOC, MD."""
    file_path = Path(file_path)
    ext = file_path.suffix.lower()

    if ext == ".pdf":
        return normalize_pdf(file_path)
    if ext == ".docx":
        return normalize_docx(file_path)
    if ext == ".doc":
        return normalize_doc(file_path)
    if ext == ".md":
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
            return NormalizationResult(text=text, method="markdown", pages=1, markdown=True)
        except Exception as e:
            return NormalizationResult(text="", error=str(e)[:200])
    if ext in (".png", ".jpg", ".jpeg"):
        return normalize_image(file_path)

    return NormalizationResult(text="", error=f"Formato no soportado: {ext}")
