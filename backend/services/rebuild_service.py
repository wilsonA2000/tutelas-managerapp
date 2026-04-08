"""Servicio de reconstruccion de DB desde carpetas fisicas.

Genera una DB nueva en data/sandbox/ escaneando las carpetas originales.
NO consume IA — solo extraccion de texto local (pdftext/PaddleOCR).
NO mueve ni modifica archivos del directorio original.
"""

import re
import csv
import logging
import sqlite3
from pathlib import Path
from datetime import datetime

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.core.settings import settings
from backend.database.models import Base, Case, Document, Email, AuditLog
from backend.database.seed import is_case_folder, scan_folder_documents, classify_document
from backend.extraction.pipeline import extract_document_text

logger = logging.getLogger("rebuild")

SANDBOX_DIR = settings.app_dir / "data" / "sandbox"
SANDBOX_DB_PATH = SANDBOX_DIR / "tutelas_sandbox.db"


def _create_sandbox_engine():
    """Crear engine SQLAlchemy para la DB sandbox."""
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{SANDBOX_DB_PATH}"
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 15})

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def rebuild_from_folders(
    extract_text: bool = True,
    import_csv_data: bool = True,
    progress_callback=None,
) -> dict:
    """Reconstruir DB completa en sandbox desde carpetas fisicas.

    Args:
        extract_text: Si True, extrae texto de cada documento (pdftext/PaddleOCR, 0 IA)
        import_csv_data: Si True, importa campos del CSV existente
        progress_callback: Funcion(step, current, total, detail) para reportar progreso

    Returns:
        dict con estadisticas del rebuild
    """
    stats = {
        "cases_created": 0,
        "documents_registered": 0,
        "documents_with_text": 0,
        "csv_imported": 0,
        "emails_linked": 0,
        "errors": [],
        "started_at": datetime.now().isoformat(),
    }

    def report(step, current=0, total=0, detail=""):
        if progress_callback:
            progress_callback(step, current, total, detail)
        logger.info(f"Rebuild [{current}/{total}]: {step} - {detail}")

    # Eliminar DB sandbox anterior si existe
    if SANDBOX_DB_PATH.exists():
        SANDBOX_DB_PATH.unlink()
        # Limpiar WAL/SHM residuales
        for suffix in ("-wal", "-shm"):
            residual = Path(str(SANDBOX_DB_PATH) + suffix)
            if residual.exists():
                residual.unlink()

    # Crear engine y tablas
    engine = _create_sandbox_engine()
    # Importar todos los modelos para crear tablas
    import backend.auth.models  # noqa
    import backend.knowledge.models  # noqa
    import backend.agent.reasoning  # noqa
    import backend.agent.memory  # noqa
    import backend.alerts.models  # noqa
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        base_dir = Path(settings.BASE_DIR)
        report("Escaneando carpetas...", 0, 5)

        # ============================================================
        # Paso 1: Escanear carpetas fisicas y crear casos
        # ============================================================
        report("Paso 1/5: Registrando casos desde carpetas", 1, 5)
        folders = sorted([
            d for d in base_dir.iterdir()
            if d.is_dir() and is_case_folder(d.name)
        ])

        for i, folder in enumerate(folders):
            case = Case(
                folder_name=folder.name,
                folder_path=str(folder),
                processing_status="PENDIENTE",
            )
            db.add(case)
            db.flush()

            # Registrar documentos
            for doc_info in scan_folder_documents(folder):
                doc = Document(
                    case_id=case.id,
                    filename=doc_info["filename"],
                    file_path=doc_info["file_path"],
                    doc_type=doc_info["doc_type"],
                    file_size=doc_info.get("file_size", 0),
                )
                db.add(doc)
                stats["documents_registered"] += 1

            stats["cases_created"] += 1

            if i % 20 == 0:
                report("Paso 1/5: Registrando casos", 1, 5,
                       f"{i+1}/{len(folders)} carpetas")
                db.commit()

        db.commit()
        report("Paso 1/5 completado", 1, 5,
               f"{stats['cases_created']} casos, {stats['documents_registered']} docs")

        # ============================================================
        # Paso 2: Importar datos del CSV si existe
        # ============================================================
        if import_csv_data:
            report("Paso 2/5: Importando CSV", 2, 5)
            csv_path = settings.csv_path
            if csv_path.exists():
                try:
                    with open(csv_path, "r", encoding="utf-8-sig") as f:
                        reader = csv.DictReader(f, delimiter=settings.CSV_DELIMITER)
                        for row in reader:
                            radicado = row.get("RADICADO_23_DIGITOS", "").strip()
                            accionante_csv = row.get("ACCIONANTE", "").strip()

                            # Buscar caso por radicado o por nombre en folder
                            matched_case = None
                            if radicado:
                                matched_case = db.query(Case).filter(
                                    Case.radicado_23_digitos == radicado
                                ).first()

                            if not matched_case and accionante_csv:
                                # Buscar por accionante en folder_name
                                all_cases = db.query(Case).all()
                                for c in all_cases:
                                    if c.folder_name and accionante_csv[:15].upper() in c.folder_name.upper():
                                        matched_case = c
                                        break

                            if matched_case:
                                for csv_col, attr in Case.CSV_FIELD_MAP.items():
                                    val = row.get(csv_col, "").strip()
                                    if val and not getattr(matched_case, attr):
                                        setattr(matched_case, attr, val)
                                stats["csv_imported"] += 1
                            else:
                                # Caso del CSV sin carpeta — crear registro sin folder
                                case = Case(processing_status="COMPLETO")
                                for csv_col, attr in Case.CSV_FIELD_MAP.items():
                                    val = row.get(csv_col, "").strip()
                                    if val:
                                        setattr(case, attr, val)
                                db.add(case)
                                stats["csv_imported"] += 1

                    db.commit()
                except Exception as e:
                    stats["errors"].append(f"CSV: {e}")
                    logger.error(f"Error importando CSV: {e}")

            report("Paso 2/5 completado", 2, 5, f"{stats['csv_imported']} registros del CSV")

        # ============================================================
        # Paso 3: Extraer texto de documentos (local, 0 IA)
        # ============================================================
        if extract_text:
            report("Paso 3/5: Extrayendo texto de documentos", 3, 5)
            all_docs = db.query(Document).filter(
                Document.extracted_text.is_(None)
            ).all()

            for i, doc in enumerate(all_docs):
                if i % 50 == 0:
                    report("Paso 3/5: Extrayendo texto", 3, 5,
                           f"{i}/{len(all_docs)} docs")
                    db.commit()

                if not doc.file_path or not Path(doc.file_path).exists():
                    continue

                try:
                    text, method = extract_document_text(doc)
                    if text and len(text.strip()) >= 10:
                        doc.extracted_text = text
                        doc.extraction_method = method
                        doc.extraction_date = datetime.utcnow()
                        stats["documents_with_text"] += 1
                except Exception as e:
                    stats["errors"].append(f"Doc {doc.filename}: {str(e)[:80]}")

            db.commit()
            report("Paso 3/5 completado", 3, 5,
                   f"{stats['documents_with_text']}/{len(all_docs)} docs con texto")

        # ============================================================
        # Paso 4: Vincular emails de la DB principal (si existe)
        # ============================================================
        report("Paso 4/5: Vinculando emails", 4, 5)
        main_db_path = settings.db_path
        if main_db_path.exists():
            try:
                conn = sqlite3.connect(str(main_db_path))
                cursor = conn.execute(
                    "SELECT message_id, subject, sender, date_received, body_preview, "
                    "status, attachments FROM emails"
                )
                rows = cursor.fetchall()
                conn.close()

                for row in rows:
                    msg_id, subject, sender, date_recv, body, status, attachments = row

                    email = Email(
                        message_id=msg_id,
                        subject=subject,
                        sender=sender,
                        date_received=datetime.fromisoformat(date_recv) if date_recv else None,
                        body_preview=body,
                        status=status or "PENDIENTE",
                    )

                    # Intentar vincular por radicado en subject
                    if subject:
                        linked = _match_email_to_case(db, subject, body or "")
                        if linked:
                            email.case_id = linked.id
                            email.status = "ASIGNADO"
                            stats["emails_linked"] += 1

                    db.add(email)

                db.commit()
                report("Paso 4/5 completado", 4, 5,
                       f"{len(rows)} emails importados, {stats['emails_linked']} vinculados")

            except Exception as e:
                stats["errors"].append(f"Emails: {e}")
                logger.error(f"Error importando emails: {e}")

        # ============================================================
        # Paso 5: Generar reporte de comparacion
        # ============================================================
        report("Paso 5/5: Generando reporte", 5, 5)
        comparison = generate_comparison_report(db)
        stats["comparison"] = comparison

        stats["completed_at"] = datetime.now().isoformat()
        stats["sandbox_db"] = str(SANDBOX_DB_PATH)
        stats["sandbox_size_mb"] = round(SANDBOX_DB_PATH.stat().st_size / (1024 * 1024), 2)

        # Guardar reporte como JSON en sandbox
        import json
        report_path = SANDBOX_DIR / "rebuild_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2, ensure_ascii=False, default=str)

        report("Rebuild completado", 5, 5, f"{stats['cases_created']} casos")
        return stats

    except Exception as e:
        logger.error(f"Error en rebuild: {e}")
        stats["errors"].append(f"Fatal: {e}")
        stats["completed_at"] = datetime.now().isoformat()
        return stats

    finally:
        db.close()


def _match_email_to_case(db, subject: str, body: str):
    """Intentar vincular email a un caso por radicado en subject/body."""
    # Buscar radicado corto (2026-NNNNN) o largo (23 digitos)
    text = f"{subject} {body}"

    # Radicado corto: 2026-00095
    m = re.search(r"20[2][0-9][-\s]?(\d{3,5})", text)
    if m:
        year_match = re.search(r"(20[2][0-9])", text[:m.end()])
        if year_match:
            full = f"{year_match.group(1)}-{m.group(1).zfill(5)}"
            case = db.query(Case).filter(Case.folder_name.contains(full[:9])).first()
            if case:
                return case

    # FOREST number
    forest = re.search(r"EXT\d{2}[-\s]?\d{1,6}", text)
    if forest:
        case = db.query(Case).filter(
            Case.radicado_forest.contains(forest.group(0)[:8])
        ).first()
        if case:
            return case

    return None


def generate_comparison_report(sandbox_db=None) -> dict:
    """Comparar sandbox DB vs DB principal.

    Returns dict con diferencias encontradas.
    """
    main_db_path = settings.db_path
    if not main_db_path.exists():
        return {"error": "DB principal no encontrada"}
    if not SANDBOX_DB_PATH.exists():
        return {"error": "Sandbox DB no encontrada. Ejecute rebuild primero."}

    main_conn = sqlite3.connect(str(main_db_path))
    sand_conn = sqlite3.connect(str(SANDBOX_DB_PATH))

    try:
        # Casos
        main_cases = main_conn.execute("SELECT folder_name FROM cases WHERE folder_name IS NOT NULL").fetchall()
        sand_cases = sand_conn.execute("SELECT folder_name FROM cases WHERE folder_name IS NOT NULL").fetchall()
        main_set = {r[0] for r in main_cases}
        sand_set = {r[0] for r in sand_cases}

        # Documentos
        main_docs = main_conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        sand_docs = sand_conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]

        # Docs con texto
        main_text = main_conn.execute("SELECT COUNT(*) FROM documents WHERE extracted_text IS NOT NULL AND LENGTH(extracted_text) > 10").fetchone()[0]
        sand_text = sand_conn.execute("SELECT COUNT(*) FROM documents WHERE extracted_text IS NOT NULL AND LENGTH(extracted_text) > 10").fetchone()[0]

        # Emails
        main_emails = main_conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
        sand_emails = sand_conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]

        return {
            "main_cases": len(main_set),
            "sandbox_cases": len(sand_set),
            "only_in_main": sorted(main_set - sand_set),
            "only_in_sandbox": sorted(sand_set - main_set),
            "main_documents": main_docs,
            "sandbox_documents": sand_docs,
            "main_docs_with_text": main_text,
            "sandbox_docs_with_text": sand_text,
            "main_emails": main_emails,
            "sandbox_emails": sand_emails,
        }

    finally:
        main_conn.close()
        sand_conn.close()
