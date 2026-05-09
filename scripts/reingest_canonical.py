"""
Re-ingesta básica desde tutelas-files-clean/ (carpetas canónicas con naming rad23).

Para cada carpeta canónica:
1. Crea Case con folder_name=carpeta, folder_path, radicado_23_digitos derivado del nombre.
2. Itera archivos, crea Document con doc_type clasificado y filepath relativo.
3. NO ejecuta LLM. Solo estructura + metadatos.

Uso:
  .venv/bin/python3 scripts/reingest_canonical.py
"""
from __future__ import annotations
import sys
import re
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session
from backend.database.database import SessionLocal
from backend.database.models import Case, Document
from backend.core.settings import settings

CLEAN_DIR = Path("/home/wilsonarguello/iuris-data/tutelas-files-clean")

# Heurística doc_type (consistente con audit_carpetas_canonical.py)
DOC_TYPE_HINTS = [
    ("PDF_AUTO_ADMISORIO",   ["auto avoca", "auto admisorio", "autoavoca", "autoadmisorio",
                                "admisor", "admite tut", "admitase", "obedezcase",
                                "autoobedezcase", "autoadmite", "auto admite"]),
    ("PDF_FALLO_1RA",         ["fallo1ra", "fallotutela", "sentencia1ra", "fallodetutela",
                                "sentenciatutela", "fallo de tutela", "sentencia de tutela",
                                "fallo tutela"]),
    ("PDF_FALLO_2DA",         ["fallo2da", "sentencia2da", "sentenciasegunda",
                                "fallo2dainstancia", "segundainstancia"]),
    ("PDF_IMPUGNACION",       ["impugnacion", "ampliaimpugnacion", "impugna", "escritoimpugnacion"]),
    ("PDF_INCIDENTE",         ["incidente", "desacato", "autoabreincidente", "aperturaincidente"]),
    ("PDF_AUTO_VINCULA",      ["autovincula", "vinculaydecreta"]),
    ("PDF_AUTO_REQUIERE",     ["autorequiere", "autorequerimiento"]),
    ("PDF_ESCRITO_TUTELA",    ["escritodetutela", "escritotutela", "tutela.pdf", "01accion",
                                "002escritodetutela", "acciondetutela", "accion de tutela"]),
    ("PDF_DERECHO_PETICION",  ["derechopeticion", "derecho de peticion"]),
    ("PDF_PRUEBAS",           ["pruebas"]),
    ("DOCX_RESPUESTA",        ["respuesta forest", "respuestaforest", "respuesta", "contestacion",
                                "carta-contestacion", "rad", "forest"]),
    ("DOCX_IMPUGNACION",      ["impugnacion"]),
    ("EMAIL_MD",              [".md"]),
]

def classify_doc_type(filename: str) -> str:
    """Heurística simple por filename para doc_type."""
    fn = filename.lower()
    suf = Path(filename).suffix.lower()
    if suf == ".md":
        return "EMAIL_MD"
    for dt, hints in DOC_TYPE_HINTS:
        if dt == "EMAIL_MD":
            continue
        # Filtrar por extensión
        if dt.startswith("PDF_") and suf != ".pdf":
            continue
        if dt.startswith("DOCX_") and suf not in (".docx", ".doc"):
            continue
        for h in hints:
            if h in fn:
                return dt
    if suf == ".pdf":
        return "PDF_OTRO"
    if suf in (".docx", ".doc"):
        return "DOCX_OTRO"
    return "OTRO"

def rad23_from_canonical(folder_name: str) -> str | None:
    """Devuelve los 23 dígitos sin guiones desde nombre canónico XXXXX-XX-XX-XXX-XXXX-XXXXX-XX."""
    digits = re.sub(r'\D', '', folder_name)
    if len(digits) == 23:
        return digits
    return None

def main():
    if not CLEAN_DIR.exists():
        print(f"ERROR: {CLEAN_DIR} no existe")
        sys.exit(1)

    folders = sorted([f for f in CLEAN_DIR.iterdir() if f.is_dir() and not f.name.startswith("_")])
    print(f"Re-ingesta de {len(folders)} carpetas canónicas en {CLEAN_DIR}")

    db: Session = SessionLocal()
    cases_created = 0
    docs_created = 0
    errors = []

    try:
        for i, folder in enumerate(folders, 1):
            try:
                rad23 = rad23_from_canonical(folder.name)
                if not rad23:
                    errors.append(f"{folder.name}: rad23 inválido")
                    continue

                # Crear Case
                case = Case(
                    folder_name=folder.name,
                    folder_path=str(folder),
                    radicado_23_digitos=rad23,
                    processing_status="PENDIENTE",
                    tipo_actuacion="TUTELA",
                    estado="ACTIVO",
                    pii_mode="off",
                )
                db.add(case)
                db.flush()  # obtiene case.id
                cases_created += 1

                # Crear Documents
                files = sorted([f for f in folder.iterdir() if f.is_file()])
                for f in files:
                    doc_type = classify_doc_type(f.name)
                    doc = Document(
                        case_id=case.id,
                        filename=f.name,
                        file_path=str(f),
                        doc_type=doc_type,
                        file_size=f.stat().st_size,
                        extraction_date=None,
                    )
                    db.add(doc)
                    docs_created += 1

                if i % 50 == 0:
                    db.commit()
                    print(f"  procesadas {i}/{len(folders)}  cases={cases_created}  docs={docs_created}")

            except Exception as e:
                errors.append(f"{folder.name}: {e}")
                db.rollback()
                continue

        db.commit()
        print(f"\n=== RE-INGESTA COMPLETA ===")
        print(f"  Carpetas procesadas: {len(folders)}")
        print(f"  Cases creados: {cases_created}")
        print(f"  Documents creados: {docs_created}")
        if errors:
            print(f"  Errores: {len(errors)}")
            for e in errors[:10]:
                print(f"    ! {e}")

    finally:
        db.close()

if __name__ == "__main__":
    main()
