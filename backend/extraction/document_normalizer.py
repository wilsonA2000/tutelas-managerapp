"""
Capa de normalizacion documental: 3 tiers para PDF, PaddleOCR para escaneados.

Tier 1: pdftext (rapido, sin modelos, mejor que pdfplumber)
Tier 2: Marker (opt-in, ~2GB modelos, mejor layout/tablas)
Tier 3: pdfplumber + Tesseract (legacy fallback)

DOCX siempre usa python-docx (preserva footer con abogado).
Imagenes: PaddleOCR → Tesseract fallback.
"""

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("tutelas.normalizer")

logging.getLogger("ppocr").setLevel(logging.WARNING)
logging.getLogger("paddle").setLevel(logging.WARNING)


@dataclass
class NormalizationResult:
    text: str
    method: str = "legacy"
    pages: int = 0
    has_ocr_pages: bool = False
    error: str | None = None
    markdown: bool = False


# ---------------------------------------------------------------------------
# Lazy singletons
# ---------------------------------------------------------------------------
_pdftext_available: bool | None = None
_marker_converter = None
_paddle_ocr = None


def _check_pdftext() -> bool:
    global _pdftext_available
    if _pdftext_available is not None:
        return _pdftext_available
    try:
        from pdftext.extraction import plain_text_output  # noqa: F401
        _pdftext_available = True
        logger.info("pdftext disponible")
    except ImportError:
        _pdftext_available = False
    return _pdftext_available


def _get_marker_converter():
    global _marker_converter
    if _marker_converter is not None:
        return _marker_converter
    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict

        artifact_dict = create_model_dict(device="cpu")
        _marker_converter = PdfConverter(
            artifact_dict=artifact_dict,
            config={"output_format": "markdown", "languages": ["es", "en"]},
        )
        logger.info("Marker PDF converter inicializado (CPU)")
        return _marker_converter
    except Exception as e:
        logger.warning(f"No se pudo inicializar Marker: {e}")
        return None


def _get_paddle_ocr():
    global _paddle_ocr
    if _paddle_ocr is not None:
        return _paddle_ocr
    try:
        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        from paddleocr import PaddleOCR
        _paddle_ocr = PaddleOCR(use_angle_cls=True, lang="es", use_gpu=False, show_log=False)
        logger.info("PaddleOCR inicializado (CPU, espanol)")
        return _paddle_ocr
    except Exception as e:
        logger.warning(f"No se pudo inicializar PaddleOCR: {e}")
        return None


# ---------------------------------------------------------------------------
# Normalizadores por tipo
# ---------------------------------------------------------------------------

def normalize_pdf(file_path: str | Path) -> NormalizationResult:
    """PDF: cascada tier 1 → 2 → 3."""
    file_path = Path(file_path)
    if not file_path.exists():
        return NormalizationResult(text="", error=f"Archivo no existe: {file_path}")

    # Tier 1: pdftext
    if _check_pdftext():
        result = _extract_with_pdftext(file_path)
        if result.text.strip() and len(result.text.strip()) >= 50:
            if result.has_ocr_pages:
                result = _supplement_with_ocr(result, file_path)
            return result
        # pdftext fallo (escaneado): intentar OCR completo antes de Marker/legacy
        if result.has_ocr_pages:
            ocr_result = _ocr_full_pdf(file_path)
            if ocr_result.text.strip() and len(ocr_result.text.strip()) >= 20:
                return ocr_result

    # Tier 2: Marker (solo si habilitado en config)
    try:
        from backend.core.settings import settings
        if settings.NORMALIZER_USE_MARKER:
            result = _extract_with_marker(file_path)
            if result.text.strip() and len(result.text.strip()) >= 20:
                return result
    except Exception:
        pass

    # Tier 3: legacy
    return _legacy_pdf(file_path)


def normalize_image(file_path: str | Path) -> NormalizationResult:
    """Imagen (screenshot, scan): PaddleOCR → Tesseract."""
    file_path = Path(file_path)
    if not file_path.exists():
        return NormalizationResult(text="", error=f"Archivo no existe: {file_path}")

    try:
        from backend.core.settings import settings
        use_paddle = settings.NORMALIZER_USE_PADDLEOCR
    except Exception:
        use_paddle = True

    if use_paddle:
        ocr = _get_paddle_ocr()
        if ocr:
            try:
                result = ocr.ocr(str(file_path), cls=True)
                lines = _paddle_result_to_lines(result)
                if lines:
                    return NormalizationResult(
                        text="\n".join(lines), method="paddleocr",
                        pages=1, has_ocr_pages=True,
                    )
            except Exception as e:
                logger.warning(f"PaddleOCR fallo para {file_path.name}: {e}")

    # Fallback: Tesseract
    try:
        from backend.extraction.ocr_extractor import extract_image_ocr
        result = extract_image_ocr(file_path)
        return NormalizationResult(text=result.text, method="tesseract", pages=1, has_ocr_pages=True)
    except Exception:
        return NormalizationResult(text="", error="No OCR disponible")


def normalize_docx(file_path: str | Path) -> NormalizationResult:
    """DOCX: usa python-docx (preserva footers con abogado). NUNCA Marker."""
    from backend.extraction.docx_extractor import extract_docx
    result = extract_docx(file_path)
    if result.error:
        return NormalizationResult(text="", error=result.error)
    return NormalizationResult(text=result.text, method=f"docx_{result.method}", pages=1)


def normalize_doc(file_path: str | Path) -> NormalizationResult:
    """DOC legacy: usa extractor existente."""
    from backend.extraction.doc_extractor import extract_doc
    result = extract_doc(file_path)
    if result.error:
        return NormalizationResult(text="", error=result.error)
    return NormalizationResult(text=result.text, method=f"doc_{result.method}", pages=1)


# ---------------------------------------------------------------------------
# Punto de entrada unico
# ---------------------------------------------------------------------------

def normalize_document(file_path: str | Path) -> NormalizationResult:
    """Normaliza cualquier tipo de documento. Fallback a legacy si falla."""
    file_path = Path(file_path)
    ext = file_path.suffix.lower()

    if ext == ".pdf":
        return normalize_pdf(file_path)
    elif ext == ".docx":
        return normalize_docx(file_path)
    elif ext == ".doc":
        return normalize_doc(file_path)
    elif ext in (".png", ".jpg", ".jpeg", ".bmp", ".gif"):
        return normalize_image(file_path)
    elif ext == ".md":
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
            return NormalizationResult(text=text, method="markdown", pages=1, markdown=True)
        except Exception as e:
            return NormalizationResult(text="", error=str(e))
    return NormalizationResult(text="", method="unsupported", error=f"Formato no soportado: {ext}")


# ---------------------------------------------------------------------------
# Funciones internas por tier
# ---------------------------------------------------------------------------

def _extract_with_pdftext(file_path: Path) -> NormalizationResult:
    """Tier 1: pdftext — rapido, sin modelos."""
    try:
        from pdftext.extraction import paginated_plain_text_output
        pages = paginated_plain_text_output(str(file_path))
        if not pages:
            return NormalizationResult(text="", error="pdftext: sin paginas")

        all_parts = []
        scanned_count = 0
        for i, page_text in enumerate(pages):
            if len(page_text.strip()) < 50:
                scanned_count += 1
            all_parts.append(f"--- PAGINA {i + 1} ---\n{page_text}")

        text = "\n\n".join(all_parts)
        has_scanned = scanned_count > 0

        # Si mas de la mitad son escaneadas, necesita OCR completo
        if scanned_count > len(pages) / 2:
            return NormalizationResult(
                text="", error="PDF mayormente escaneado",
                pages=len(pages), has_ocr_pages=True,
            )

        return NormalizationResult(
            text=text, method="pdftext", pages=len(pages), has_ocr_pages=has_scanned,
        )
    except Exception as e:
        return NormalizationResult(text="", error=f"pdftext fallo: {e}")


def _extract_with_marker(file_path: Path) -> NormalizationResult:
    """Tier 2: Marker — mejor calidad con layout. Requiere modelos (~2GB)."""
    converter = _get_marker_converter()
    if not converter:
        return NormalizationResult(text="", error="Marker no disponible")
    try:
        rendered = converter(str(file_path))
        md_text = rendered.markdown if hasattr(rendered, "markdown") else str(rendered)
        if md_text and len(md_text.strip()) >= 20:
            return NormalizationResult(
                text=_clean_markdown(md_text), method="marker",
                pages=getattr(converter, "page_count", 0) or 0,
                markdown=True,
            )
        return NormalizationResult(text="", error="Marker: texto vacio")
    except Exception as e:
        logger.warning(f"Marker fallo para {file_path.name}: {e}")
        return NormalizationResult(text="", error=str(e))


def _legacy_pdf(file_path: Path) -> NormalizationResult:
    """Tier 3: pdfplumber + Tesseract (extractores originales)."""
    from backend.extraction.pdf_extractor import extract_pdf
    from backend.extraction.ocr_extractor import extract_pdf_ocr, is_tesseract_available

    result = extract_pdf(file_path)
    text = result.text
    method = result.method

    if result.has_scanned_pages and is_tesseract_available():
        ocr_result = extract_pdf_ocr(file_path)
        if ocr_result.text.strip():
            text += "\n\n[OCR COMPLEMENTARIO]\n" + ocr_result.text
            method = "pdfplumber+tesseract"

    return NormalizationResult(
        text=text, method=f"legacy_{method}",
        pages=result.page_count, has_ocr_pages=result.has_scanned_pages,
    )


def _ocr_full_pdf(file_path: Path) -> NormalizationResult:
    """OCR completo de un PDF escaneado: PaddleOCR → Tesseract."""
    try:
        from backend.core.settings import settings
        use_paddle = settings.NORMALIZER_USE_PADDLEOCR
    except Exception:
        use_paddle = True

    if use_paddle:
        ocr = _get_paddle_ocr()
        if ocr:
            try:
                result = ocr.ocr(str(file_path), cls=True)
                all_pages = []
                page_count = 0
                if result:
                    for page_idx, page_data in enumerate(result):
                        page_count += 1
                        lines = _paddle_result_to_lines([page_data]) if page_data else []
                        if lines:
                            all_pages.append(f"--- PAGINA {page_idx + 1} (OCR) ---\n" + "\n".join(lines))
                if all_pages:
                    return NormalizationResult(
                        text="\n\n".join(all_pages), method="paddleocr",
                        pages=page_count, has_ocr_pages=True,
                    )
            except Exception as e:
                logger.warning(f"PaddleOCR fallo OCR completo de {file_path.name}: {e}")

    # Fallback: Tesseract
    try:
        from backend.extraction.ocr_extractor import extract_pdf_ocr, is_tesseract_available
        if is_tesseract_available():
            ocr_result = extract_pdf_ocr(file_path)
            if ocr_result.text.strip():
                return NormalizationResult(
                    text=ocr_result.text, method="tesseract",
                    pages=ocr_result.page_count, has_ocr_pages=True,
                )
    except Exception:
        pass

    return NormalizationResult(text="", error="OCR no disponible", has_ocr_pages=True)


def _supplement_with_ocr(result: NormalizationResult, file_path: Path) -> NormalizationResult:
    """Complementar resultado con OCR para paginas escaneadas."""
    try:
        from backend.core.settings import settings
        use_paddle = settings.NORMALIZER_USE_PADDLEOCR
    except Exception:
        use_paddle = True

    if use_paddle:
        ocr = _get_paddle_ocr()
        if ocr:
            try:
                ocr_result = ocr.ocr(str(file_path), cls=True)
                lines = _paddle_result_to_lines(ocr_result)
                if lines:
                    result.text += "\n\n[OCR COMPLEMENTARIO - PaddleOCR]\n" + "\n".join(lines)
                    result.method += "+paddleocr"
                    return result
            except Exception:
                pass

    # Fallback: Tesseract
    try:
        from backend.extraction.ocr_extractor import extract_pdf_ocr, is_tesseract_available
        if is_tesseract_available():
            ocr_result = extract_pdf_ocr(file_path)
            if ocr_result.text.strip():
                result.text += "\n\n[OCR COMPLEMENTARIO - Tesseract]\n" + ocr_result.text
                result.method += "+tesseract"
    except Exception:
        pass

    return result


def _paddle_result_to_lines(result) -> list[str]:
    """Convertir resultado PaddleOCR a lista de lineas de texto."""
    lines = []
    if not result:
        return lines
    for page_data in result:
        if not page_data:
            continue
        for line_data in page_data:
            if line_data and len(line_data) >= 2:
                text = line_data[1][0] if isinstance(line_data[1], (list, tuple)) else str(line_data[1])
                lines.append(text)
    return lines


def _clean_markdown(text: str) -> str:
    """Limpiar artefactos del Markdown generado por Marker."""
    text = re.sub(r"!\[.*?\]\(data:image/[^)]+\)", "[IMAGEN]", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    text = re.sub(r"^\s+$", "", text, flags=re.MULTILINE)
    return text.strip()


# ---------------------------------------------------------------------------
# Status check
# ---------------------------------------------------------------------------

def check_normalizer_status() -> dict:
    """Estado de componentes del normalizer. Para /api/health/normalizer."""
    try:
        from backend.core.settings import settings
        enabled = settings.NORMALIZER_ENABLED
        marker_enabled = settings.NORMALIZER_USE_MARKER
        paddle_enabled = settings.NORMALIZER_USE_PADDLEOCR
    except Exception:
        enabled = marker_enabled = paddle_enabled = False

    status = {
        "normalizer_enabled": enabled,
        "marker_config_enabled": marker_enabled,
        "paddleocr_config_enabled": paddle_enabled,
        "pdftext_available": False,
        "marker_available": False,
        "marker_models_loaded": _marker_converter is not None,
        "paddleocr_available": False,
        "paddleocr_loaded": _paddle_ocr is not None,
        "tesseract_available": False,
    }

    try:
        from pdftext.extraction import plain_text_output  # noqa: F401
        status["pdftext_available"] = True
    except ImportError:
        pass

    try:
        from marker.converters.pdf import PdfConverter  # noqa: F401
        status["marker_available"] = True
    except ImportError:
        pass

    try:
        from paddleocr import PaddleOCR  # noqa: F401
        status["paddleocr_available"] = True
    except ImportError:
        pass

    try:
        from backend.extraction.ocr_extractor import is_tesseract_available
        status["tesseract_available"] = is_tesseract_available()
    except Exception:
        pass

    return status
