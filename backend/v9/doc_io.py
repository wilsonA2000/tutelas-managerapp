"""Etapa 1 — Lectura de documentos. Sin IA, sin clasificación.

Toma una lista de paths a PDF/DOCX/DOC/IMG y devuelve el texto crudo
con metadata de método. Reusa `pdf_extractor.extract_pdf` y
`docx_extractor.extract_docx` que ya funcionan.

Salida: lista de `DocText` con `path`, `text`, `method`, `pages`, `error`.
La clasificación de tipo de documento NO ocurre aquí — eso es trabajo de
`regex_pass`, que mira keywords en el texto.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

logger = logging.getLogger("tutelas.v9.doc_io")


@dataclass
class DocText:
    path: str
    filename: str
    text: str
    method: str               # pymupdf / python-docx / antiword / error
    pages: int = 0
    has_scanned_pages: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.text.strip())


def read_one(path: str | Path) -> DocText:
    """Lee 1 archivo. Despacha por extensión."""
    p = Path(path)
    if not p.exists():
        return DocText(str(p), p.name, "", "missing", error=f"No existe: {p}")

    ext = p.suffix.lower()
    try:
        if ext == ".pdf":
            from backend.extraction.pdf_extractor import extract_pdf
            # OCR de páginas escaneadas (sin capa de texto). Flag V9_OCR_SCANNED
            # (default on): cierra el hueco de los PDFs imagen-pura que quedaban sin
            # texto en la ingesta. extract_pdf solo OCR-ea las páginas escaneadas, así
            # que los PDFs con texto no pagan costo.
            _ocr = os.getenv("V9_OCR_SCANNED", "true").lower() != "false"
            r = extract_pdf(p, ocr_scanned=_ocr)
            return DocText(
                path=str(p), filename=p.name,
                text=r.text or "", method=r.method,
                pages=r.pages, has_scanned_pages=r.has_scanned_pages,
                error=r.error,
            )
        if ext == ".docx":
            from backend.extraction.docx_extractor import extract_docx
            r = extract_docx(p)
            # extract_docx devuelve un dict-like o tuple según versión; normalizamos
            if isinstance(r, tuple):
                text, method = r[0], (r[1] if len(r) > 1 else "python-docx")
                return DocText(str(p), p.name, text or "", method)
            text = getattr(r, "text", "") or (r.get("text", "") if isinstance(r, dict) else "")
            method = getattr(r, "method", "python-docx") or "python-docx"
            err = getattr(r, "error", None)
            return DocText(str(p), p.name, text, method, error=err)
        if ext == ".doc":
            from backend.extraction.doc_extractor import extract_doc
            r = extract_doc(p)
            if isinstance(r, tuple):
                return DocText(str(p), p.name, r[0] or "", r[1] if len(r) > 1 else "antiword")
            return DocText(str(p), p.name, getattr(r, "text", "") or "", "antiword")
        if ext == ".md" or ext == ".txt":
            return DocText(str(p), p.name, p.read_text(encoding="utf-8", errors="ignore"), "text")
        # Imágenes: por ahora, sin OCR. Se delega a una etapa futura si hace falta.
        if ext in {".jpg", ".jpeg", ".png", ".tiff", ".tif"}:
            return DocText(str(p), p.name, "", "image_no_ocr",
                           error="Imagen sin OCR — fuera de scope v9 inicial")
        return DocText(str(p), p.name, "", "unsupported", error=f"Extensión no soportada: {ext}")
    except Exception as e:
        logger.warning("read_one falló en %s: %s", p.name, str(e)[:120])
        return DocText(str(p), p.name, "", "error", error=str(e)[:200])


def read_all(paths: Iterable[str | Path]) -> list[DocText]:
    """Lee N archivos. No paraleliza — pymupdf + python-docx son rápidos
    y la complejidad de un ProcessPool en WSL/DrvFs no compensa para
    casos típicos (4-20 docs/caso)."""
    return [read_one(p) for p in paths]
