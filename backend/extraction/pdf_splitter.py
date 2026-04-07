"""Recortar PDFs grandes para upload multimodal a Gemini."""

import tempfile
from pathlib import Path


def prepare_pdf_for_upload(file_path: str, max_pages: int = 30) -> tuple[str, bool]:
    """Si el PDF tiene >max_pages, crea un PDF temporal con las primeras 10 + ultimas 10.

    Returns:
        (path_to_use, was_trimmed): Path del PDF listo para upload y si fue recortado.
    """
    import fitz

    try:
        doc = fitz.open(file_path)
        total = len(doc)

        if total <= max_pages:
            doc.close()
            return str(file_path), False

        # Crear PDF con primeras 10 + ultimas 10 paginas
        new_doc = fitz.open()
        first_n = min(10, total)
        last_n = min(10, total - first_n)

        # Primeras 10
        new_doc.insert_pdf(doc, from_page=0, to_page=first_n - 1)

        # Pagina separadora indicando que se recorto
        if total > first_n + last_n:
            sep_page = new_doc.new_page(width=612, height=792)
            skipped = total - first_n - last_n
            sep_page.insert_text(
                (72, 400),
                f"[... {skipped} paginas omitidas de {total} totales ...]",
                fontsize=14,
            )

        # Ultimas 10
        if last_n > 0:
            new_doc.insert_pdf(doc, from_page=total - last_n, to_page=total - 1)

        # Guardar en temporal
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        new_doc.save(tmp.name)
        new_doc.close()
        doc.close()
        tmp.close()

        return tmp.name, True

    except Exception:
        return str(file_path), False
