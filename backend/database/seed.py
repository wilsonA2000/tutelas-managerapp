"""Importar datos del CSV existente y escanear carpetas al SQLite."""

import csv
import os
import re
from pathlib import Path
from datetime import datetime

from sqlalchemy.orm import Session

from backend.config import BASE_DIR, CSV_PATH, CSV_DELIMITER
from backend.database.models import Case, Document, AuditLog
from backend.database.database import SessionLocal, init_db


# Clasificacion de documentos: fuente unica en pipeline.py
from backend.extraction.pipeline import classify_doc_type


def classify_document(filename: str) -> str:
    """Clasificar tipo de documento por su nombre.
    Delegado a classify_doc_type() de pipeline.py (fuente unica de verdad)."""
    return classify_doc_type(filename)


def is_case_folder(name: str) -> bool:
    """Verificar si un nombre de directorio es una carpeta de caso."""
    # Debe empezar con un ano (2020-2029)
    return bool(re.match(r"^20[2][0-9]", name.strip()))


def scan_folder_documents(folder_path: Path) -> list[dict]:
    """Escanear archivos de una carpeta de caso."""
    docs = []
    valid_extensions = {".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg", ".md"}

    if not folder_path.exists():
        return docs

    for f in sorted(folder_path.iterdir()):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext not in valid_extensions:
            continue

        docs.append({
            "filename": f.name,
            "file_path": str(f),
            "doc_type": classify_document(f.name),
            "file_size": f.stat().st_size,
        })

    return docs


def import_csv(db: Session) -> int:
    """Importar registros del CSV existente."""
    if not CSV_PATH.exists():
        print(f"CSV no encontrado: {CSV_PATH}")
        return 0

    imported = 0
    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=CSV_DELIMITER)
        for row in reader:
            # Buscar si ya existe por radicado
            radicado = row.get("RADICADO_23_DIGITOS", "").strip()
            if radicado:
                existing = db.query(Case).filter(
                    Case.radicado_23_digitos == radicado
                ).first()
                if existing:
                    continue

            case = Case(processing_status="COMPLETO")
            for csv_col, attr in Case.CSV_FIELD_MAP.items():
                value = row.get(csv_col, "").strip()
                if value:
                    setattr(case, attr, value)

            db.add(case)
            db.flush()

            # Registro de auditoria
            db.add(AuditLog(
                case_id=case.id,
                action="IMPORT_CSV",
                source="seed.py",
                new_value=f"Importado del CSV con {sum(1 for c, a in Case.CSV_FIELD_MAP.items() if getattr(case, a))} campos",
            ))
            imported += 1

    db.commit()
    print(f"CSV: {imported} casos importados")
    return imported


def scan_folders(db: Session) -> int:
    """Escanear carpetas y crear casos/documentos que no esten en DB."""
    created = 0
    updated_docs = 0

    for entry in sorted(BASE_DIR.iterdir()):
        if not entry.is_dir() or not is_case_folder(entry.name):
            continue

        folder_name = entry.name

        # Buscar caso existente por folder_name
        case = db.query(Case).filter(Case.folder_name == folder_name).first()

        if not case:
            # Intentar match por nombre de accionante en el folder
            # Extraer nombre del folder: "2026-00095 PAOLA ANDREA GARCIA NUNEZ" -> "PAOLA ANDREA GARCIA NUNEZ"
            parts = re.split(r"\d[\s\-]*", folder_name, maxsplit=1)
            accionante_hint = parts[-1].strip() if len(parts) > 1 else ""

            # Buscar por accionante similar (case-insensitive)
            if accionante_hint:
                case = db.query(Case).filter(
                    Case.accionante.ilike(f"%{accionante_hint[:20]}%"),
                    Case.folder_name.is_(None),
                ).first()

            if case:
                case.folder_name = folder_name
                case.folder_path = str(entry)
            else:
                # Crear caso nuevo (pendiente de extraccion)
                case = Case(
                    folder_name=folder_name,
                    folder_path=str(entry),
                    processing_status="PENDIENTE",
                )
                db.add(case)
                db.flush()
                db.add(AuditLog(
                    case_id=case.id,
                    action="CREAR",
                    source="seed.py - scan_folders",
                    new_value=f"Carpeta detectada: {folder_name}",
                ))
                created += 1

        # Escanear documentos de la carpeta
        existing_filenames = {d.filename for d in case.documents} if case.documents else set()
        for doc_info in scan_folder_documents(entry):
            if doc_info["filename"] not in existing_filenames:
                doc = Document(
                    case_id=case.id,
                    filename=doc_info["filename"],
                    file_path=doc_info["file_path"],
                    doc_type=doc_info["doc_type"],
                    file_size=doc_info["file_size"],
                )
                db.add(doc)
                updated_docs += 1

    db.commit()
    print(f"Carpetas: {created} casos nuevos creados, {updated_docs} documentos registrados")
    return created


def run_seed():
    """Ejecutar importacion completa."""
    print("=" * 60)
    print("SEED: Importando datos a la base de datos")
    print("=" * 60)

    init_db()
    db = SessionLocal()

    try:
        # Paso 1: Importar CSV existente
        import_csv(db)

        # Paso 2: Escanear carpetas y vincular/crear casos
        scan_folders(db)

        # Estadisticas finales
        total_cases = db.query(Case).count()
        total_docs = db.query(Document).count()
        complete = db.query(Case).filter(Case.processing_status == "COMPLETO").count()
        pending = db.query(Case).filter(Case.processing_status == "PENDIENTE").count()

        print(f"\n{'=' * 60}")
        print(f"RESULTADO FINAL:")
        print(f"  Total casos: {total_cases}")
        print(f"  Documentos registrados: {total_docs}")
        print(f"  Completos (del CSV): {complete}")
        print(f"  Pendientes de extraccion: {pending}")
        print(f"{'=' * 60}")

    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
