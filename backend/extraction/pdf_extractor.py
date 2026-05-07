"""Extractor de PDFs minimalista — solo pymupdf.

Reemplaza la versión legacy con pdfplumber. Mantiene la misma firma
para compatibilidad con código que la consume.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("tutelas.pdf_extractor")


@dataclass
class PDFResult:
    text: str
    method: str = "pymupdf"
    pages: int = 0
    has_scanned_pages: bool = False
    error: str | None = None


def extract_pdf(file_path: str | Path) -> PDFResult:
    """Extrae texto de PDF con pymupdf. Sin fallback OCR."""
    file_path = Path(file_path)
    if not file_path.exists():
        return PDFResult(text="", error=f"Archivo no existe: {file_path}")

    try:
        import pymupdf
    except ImportError:
        return PDFResult(text="", error="pymupdf no instalado")

    try:
        doc = pymupdf.open(str(file_path))
        text_parts = []
        n_pages = doc.page_count
        scanned_pages = 0
        for i in range(n_pages):
            page_text = doc[i].get_text()
            text_parts.append(page_text)
            # Heurística: página con muy poco texto y muchas imágenes = escaneada
            if len(page_text.strip()) < 50:
                scanned_pages += 1
        doc.close()
        return PDFResult(
            text="\n".join(text_parts),
            method="pymupdf",
            pages=n_pages,
            has_scanned_pages=(scanned_pages > 0),
        )
    except Exception as e:
        logger.warning("pymupdf falló en %s: %s", file_path.name, str(e)[:100])
        return PDFResult(text="", error=str(e)[:200], method="pymupdf_error")
