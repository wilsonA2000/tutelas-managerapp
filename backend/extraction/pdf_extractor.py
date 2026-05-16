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


def extract_pdf(
    file_path: str | Path,
    first_pages: int | None = 5,
    last_pages: int | None = 3,
) -> PDFResult:
    """Extrae texto de PDF con pymupdf. Por default lee primeras 5 + últimas 3 páginas.

    Justificación (experimento 2026-05-09): en docs legales (Auto Avoca,
    Sentencia, Escrito Tutela) los campos del cuadro están concentrados en
    las primeras y últimas páginas. Reducir 76% del texto perdió solo 4% de
    cobertura. Speedup LLM ~3-4x.

    Pasar first_pages=None y last_pages=None para leer todo (legacy).
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return PDFResult(text="", error=f"Archivo no existe: {file_path}")

    try:
        import pymupdf
    except ImportError:
        return PDFResult(text="", error="pymupdf no instalado")

    try:
        doc = pymupdf.open(str(file_path))
        n_pages = doc.page_count

        if first_pages is None and last_pages is None:
            indices = list(range(n_pages))
            method = "pymupdf"
        else:
            fp = first_pages or 0
            lp = last_pages or 0
            if n_pages <= fp + lp:
                indices = list(range(n_pages))
                method = "pymupdf"
            else:
                indices = list(range(fp)) + list(range(n_pages - lp, n_pages))
                method = f"pymupdf_first{fp}_last{lp}"

        text_parts = []
        scanned_pages = 0
        for i in indices:
            page_text = doc[i].get_text()
            text_parts.append(page_text)
            if len(page_text.strip()) < 50:
                scanned_pages += 1
        doc.close()
        return PDFResult(
            text="\n".join(text_parts),
            method=method,
            pages=n_pages,
            has_scanned_pages=(scanned_pages > 0),
        )
    except Exception as e:
        logger.warning("pymupdf falló en %s: %s", file_path.name, str(e)[:100])
        return PDFResult(text="", error=str(e)[:200], method="pymupdf_error")
