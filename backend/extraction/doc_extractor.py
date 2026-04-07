"""Extractor para archivos .doc (formato antiguo de Word)."""

import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DOCExtractionResult:
    text: str
    method: str = ""
    error: str | None = None


def extract_doc(file_path: str | Path) -> DOCExtractionResult:
    """Extraer texto de un archivo .doc usando antiword o libreoffice."""
    file_path = Path(file_path)
    if not file_path.exists():
        return DOCExtractionResult(text="", error=f"Archivo no existe: {file_path}")

    # Metodo 1: antiword
    if shutil.which("antiword"):
        result = _extract_with_antiword(file_path)
        if not result.error and result.text.strip():
            return result

    # Metodo 2: catdoc
    if shutil.which("catdoc"):
        result = _extract_with_catdoc(file_path)
        if not result.error and result.text.strip():
            return result

    # Metodo 3: libreoffice conversion a docx y luego python-docx
    if shutil.which("libreoffice"):
        result = _extract_with_libreoffice(file_path)
        if not result.error and result.text.strip():
            return result

    # Metodo 4: tratar como ZIP (a veces archivos .doc son realmente .docx)
    from backend.extraction.docx_extractor import extract_docx
    docx_result = extract_docx(file_path)
    if not docx_result.error and docx_result.text.strip():
        return DOCExtractionResult(
            text=docx_result.text,
            method="docx_fallback",
        )

    return DOCExtractionResult(
        text="",
        error="No se pudo extraer texto. Instale antiword: sudo apt install antiword",
    )


def _extract_with_antiword(file_path: Path) -> DOCExtractionResult:
    try:
        result = subprocess.run(
            ["antiword", str(file_path)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return DOCExtractionResult(text=result.stdout, method="antiword")
        return DOCExtractionResult(text="", error=result.stderr, method="antiword")
    except Exception as e:
        return DOCExtractionResult(text="", error=str(e), method="antiword")


def _extract_with_catdoc(file_path: Path) -> DOCExtractionResult:
    try:
        result = subprocess.run(
            ["catdoc", str(file_path)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return DOCExtractionResult(text=result.stdout, method="catdoc")
        return DOCExtractionResult(text="", error=result.stderr, method="catdoc")
    except Exception as e:
        return DOCExtractionResult(text="", error=str(e), method="catdoc")


def _extract_with_libreoffice(file_path: Path) -> DOCExtractionResult:
    """Convertir .doc a .docx con libreoffice y luego extraer."""
    import tempfile
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = subprocess.run(
                ["libreoffice", "--headless", "--convert-to", "docx",
                 "--outdir", tmp_dir, str(file_path)],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                return DOCExtractionResult(text="", error=result.stderr, method="libreoffice")

            # Buscar el archivo convertido
            converted = list(Path(tmp_dir).glob("*.docx"))
            if not converted:
                return DOCExtractionResult(text="", error="No se genero archivo DOCX", method="libreoffice")

            from backend.extraction.docx_extractor import extract_docx
            docx_result = extract_docx(converted[0])
            return DOCExtractionResult(
                text=docx_result.text,
                method="libreoffice",
            )
    except Exception as e:
        return DOCExtractionResult(text="", error=str(e), method="libreoffice")
