"""Extractor OCR para PDFs escaneados y screenshots usando pytesseract."""

from dataclasses import dataclass
from pathlib import Path
import shutil


@dataclass
class OCRExtractionResult:
    text: str
    page_count: int = 0
    method: str = "ocr"
    error: str | None = None


def is_tesseract_available() -> bool:
    """Verificar si tesseract esta instalado."""
    return shutil.which("tesseract") is not None


def extract_image_ocr(file_path: str | Path) -> OCRExtractionResult:
    """Extraer texto de una imagen (PNG, JPG, etc.) usando OCR."""
    file_path = Path(file_path)
    if not file_path.exists():
        return OCRExtractionResult(text="", error=f"Archivo no existe: {file_path}")

    if not is_tesseract_available():
        return OCRExtractionResult(
            text="",
            error="Tesseract no instalado. Ejecute: sudo apt install tesseract-ocr tesseract-ocr-spa",
        )

    try:
        import pytesseract
        from PIL import Image

        img = Image.open(str(file_path))
        text = pytesseract.image_to_string(img, lang="spa")
        return OCRExtractionResult(text=text, page_count=1)

    except ImportError:
        return OCRExtractionResult(
            text="",
            error="Instale: pip install pytesseract Pillow",
        )
    except Exception as e:
        return OCRExtractionResult(text="", error=str(e))


def extract_pdf_ocr(file_path: str | Path) -> OCRExtractionResult:
    """Extraer texto de un PDF escaneado via OCR."""
    file_path = Path(file_path)
    if not file_path.exists():
        return OCRExtractionResult(text="", error=f"Archivo no existe: {file_path}")

    if not is_tesseract_available():
        return OCRExtractionResult(
            text="",
            error="Tesseract no instalado. Ejecute: sudo apt install tesseract-ocr tesseract-ocr-spa",
        )

    try:
        import pytesseract
        from pdf2image import convert_from_path

        images = convert_from_path(str(file_path), dpi=300)
        all_text = []

        for i, img in enumerate(images):
            page_text = pytesseract.image_to_string(img, lang="spa")
            all_text.append(f"--- PAGINA {i + 1} (OCR) ---\n{page_text}")

        return OCRExtractionResult(
            text="\n\n".join(all_text),
            page_count=len(images),
        )

    except ImportError as e:
        missing = str(e)
        return OCRExtractionResult(
            text="",
            error=f"Dependencia faltante: {missing}. Instale: pip install pytesseract pdf2image Pillow",
        )
    except Exception as e:
        return OCRExtractionResult(text="", error=str(e))
