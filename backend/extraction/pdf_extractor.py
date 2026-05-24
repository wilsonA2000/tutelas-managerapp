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
    ocr_pages: int = 0


# OCR engine (PaddleOCR) lazy + singleton por proceso. Solo se carga si alguna
# página resulta escaneada Y ocr_scanned=True. No afecta el path normal (capa de
# texto) que sigue siendo el rápido.
_OCR_ENGINE = None


def _get_ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from paddleocr import PaddleOCR
        try:
            _OCR_ENGINE = PaddleOCR(lang="es", use_angle_cls=False, show_log=False)
        except TypeError:  # PaddleOCR 3.x cambió la firma
            _OCR_ENGINE = PaddleOCR(lang="es")
    return _OCR_ENGINE


def _ocr_page_text(page, dpi: int = 200) -> str:
    """OCR de una página pymupdf ya abierta. Rasteriza a `dpi` y corre PaddleOCR."""
    import numpy as np
    pix = page.get_pixmap(dpi=dpi)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        img = img[:, :, :3]
    elif pix.n == 1:
        img = np.repeat(img, 3, axis=2)
    eng = _get_ocr_engine()
    try:
        res = eng.ocr(img)
    except Exception:
        res = eng.predict(img)
    out = []
    for blk in (res or []):
        if not blk:
            continue
        if isinstance(blk, dict) and "rec_texts" in blk:
            out.extend(blk["rec_texts"]); continue
        rec = getattr(blk, "rec_texts", None)
        if rec:
            out.extend(rec); continue
        try:
            for ln in blk:
                if ln and len(ln) >= 2 and ln[1]:
                    out.append(ln[1][0])
        except TypeError:
            pass
    return " ".join(t for t in out if t)


def extract_pdf(
    file_path: str | Path,
    first_pages: int | None = 5,
    last_pages: int | None = 3,
    ocr_scanned: bool = False,
    ocr_dpi: int = 200,
) -> PDFResult:
    """Extrae texto de PDF con pymupdf. Por default lee primeras 5 + últimas 3 páginas.

    Justificación (experimento 2026-05-09): en docs legales (Auto Avoca,
    Sentencia, Escrito Tutela) los campos del cuadro están concentrados en
    las primeras y últimas páginas. Reducir 76% del texto perdió solo 4% de
    cobertura. Speedup LLM ~3-4x.

    Pasar first_pages=None y last_pages=None para leer todo (legacy).

    ocr_scanned=True: si una página NO tiene capa de texto (escaneada, <50 chars),
    se rasteriza y se pasa por OCR (PaddleOCR es). Default False → path rápido intacto.
    Para los 422 docs imagen-pura del backfill: usar first/last=None + ocr_scanned=True
    (documento completo, ya que pueden tener info valiosa fuera del head+tail).
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
        ocr_pages = 0
        for i in indices:
            page = doc[i]
            page_text = page.get_text()
            if len(page_text.strip()) < 50:
                scanned_pages += 1
                if ocr_scanned:
                    ocr_text = _ocr_page_text(page, dpi=ocr_dpi)
                    if len(ocr_text.strip()) > len(page_text.strip()):
                        page_text = ocr_text
                        ocr_pages += 1
            text_parts.append(page_text)
        doc.close()
        if ocr_pages:
            method = f"{method}+ocr{ocr_pages}"
        return PDFResult(
            text="\n".join(text_parts),
            method=method,
            pages=n_pages,
            has_scanned_pages=(scanned_pages > 0),
            ocr_pages=ocr_pages,
        )
    except Exception as e:
        logger.warning("pymupdf falló en %s: %s", file_path.name, str(e)[:100])
        return PDFResult(text="", error=str(e)[:200], method="pymupdf_error")
