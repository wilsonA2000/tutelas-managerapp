"""Extractor robusto de PDFs usando pdfplumber. Sin truncacion."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PageResult:
    page_number: int
    text: str
    has_images: bool = False
    needs_ocr: bool = False


@dataclass
class PDFExtractionResult:
    text: str
    pages: list[PageResult] = field(default_factory=list)
    page_count: int = 0
    method: str = "pdfplumber"
    has_scanned_pages: bool = False
    error: str | None = None


def extract_pdf(file_path: str | Path) -> PDFExtractionResult:
    """Extraer texto COMPLETO de un PDF. Sin truncar."""
    file_path = Path(file_path)
    if not file_path.exists():
        return PDFExtractionResult(text="", error=f"Archivo no existe: {file_path}")

    try:
        import pdfplumber

        all_text = []
        pages = []
        has_scanned = False

        with pdfplumber.open(str(file_path)) as pdf:
            for i, page in enumerate(pdf.pages):
                page_num = i + 1

                # Extraer texto
                text = page.extract_text() or ""

                # Extraer tablas si las hay
                tables = page.extract_tables()
                table_text = ""
                if tables:
                    for table in tables:
                        for row in table:
                            if row:
                                cells = [str(c).strip() if c else "" for c in row]
                                table_text += " | ".join(cells) + "\n"

                combined = text
                if table_text and table_text.strip() not in text:
                    combined += "\n[TABLA]\n" + table_text

                # Detectar paginas escaneadas (sin texto pero con imagenes)
                has_images = bool(page.images)
                needs_ocr = has_images and len(text.strip()) < 50

                if needs_ocr:
                    has_scanned = True

                pages.append(PageResult(
                    page_number=page_num,
                    text=combined,
                    has_images=has_images,
                    needs_ocr=needs_ocr,
                ))

                all_text.append(f"--- PAGINA {page_num} ---\n{combined}")

            return PDFExtractionResult(
                text="\n\n".join(all_text),
                pages=pages,
                page_count=len(pdf.pages),
                method="pdfplumber",
                has_scanned_pages=has_scanned,
            )

    except Exception as e:
        return PDFExtractionResult(text="", error=f"Error extrayendo PDF: {e}")
