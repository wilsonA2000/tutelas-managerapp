"""Router de extraccion."""

import threading
_extraction_lock = threading.Lock()

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database.database import get_db, SessionLocal
from backend.database.models import Case
from backend.services.extraction_service import get_review_queue
from backend.extraction.pipeline import process_folder

router = APIRouter(prefix="/api/extraction", tags=["extraction"])

# Estado global compartido con main.py
import backend.main as _main


class BatchRequest(BaseModel):
    case_ids: list[int] | None = None


# Campos que se incluyen en la respuesta de extracción
_RESPONSE_FIELDS = [
    "accionante", "radicado_23_digitos", "radicado_forest", "juzgado", "ciudad",
    "derecho_vulnerado", "fecha_ingreso", "asunto", "pretensiones",
    "abogado_responsable", "oficina_responsable", "estado",
    "sentido_fallo_1st", "fecha_fallo_1st", "impugnacion", "incidente", "observaciones",
]


def _get_token_usage(db: Session, case_id: int) -> dict | None:
    """Obtener último token usage de un caso."""
    import sqlite3
    try:
        conn = sqlite3.connect(str(db.bind.url).replace("sqlite:///", ""))
        c = conn.cursor()
        c.execute(
            "SELECT tokens_input, tokens_output, cost_total, provider, model "
            "FROM token_usage WHERE case_id = ? ORDER BY timestamp DESC LIMIT 1",
            (case_id,),
        )
        tok = c.fetchone()
        conn.close()
        if tok:
            return {"input": tok[0], "output": tok[1], "cost": tok[2], "provider": tok[3], "model": tok[4]}
    except Exception:
        pass
    return None


def _get_fields_data(case) -> dict:
    """Extraer campos poblados de un caso para la respuesta."""
    fields_data = {}
    for col in _RESPONSE_FIELDS:
        val = getattr(case, col, None) or ""
        if val:
            fields_data[col] = val
    return fields_data


def _run_extraction_cases(case_ids: list[int]):
    """Ejecutar extraccion en background para una lista de case IDs."""
    import time
    _main.extraction_in_progress = True
    _main.extraction_progress = {"current": 0, "total": len(case_ids), "case_name": "Iniciando...", "success": 0, "errors": 0}

    try:
        db = SessionLocal()
        for i, cid in enumerate(case_ids):
            if not _main.extraction_in_progress:
                _main.add_monitor_log("Extraccion cancelada por usuario")
                break

            case = db.query(Case).filter(Case.id == cid).first()
            if not case:
                _main.extraction_progress["errors"] += 1
                continue

            _main.extraction_progress["current"] = i + 1
            _main.extraction_progress["case_name"] = case.folder_name or f"ID {cid}"

            try:
                stats = process_folder(db, case)
                if stats.get("ai_error"):
                    _main.extraction_progress["errors"] += 1
                    # Recovery: forzar status REVISION para que sea reintentable
                    case.processing_status = "REVISION"
                    db.commit()
                else:
                    _main.extraction_progress["success"] += 1
            except Exception as e:
                _main.extraction_progress["errors"] += 1
                # Recovery: no dejar en EXTRAYENDO indefinido
                try:
                    case.processing_status = "REVISION"
                    db.commit()
                except Exception:
                    pass
                _main.add_monitor_log(f"Error caso {cid}: {str(e)[:100]}", level="error")

            if i < len(case_ids) - 1:
                time.sleep(2)

        ok = _main.extraction_progress["success"]
        total = _main.extraction_progress["total"]
        _main.extraction_progress["case_name"] = f"Completado: {ok}/{total} exitosos"
        _main.add_monitor_log(f"Extraccion terminada: {ok}/{total} exitosos")

    except Exception as e:
        _main.add_monitor_log(f"Error en extraccion: {e}", level="error")
    finally:
        _main.extraction_in_progress = False
        try:
            db.close()
        except Exception:
            pass


@router.post("/single/{case_id}")
def api_extract_single(case_id: int, db: Session = Depends(get_db)):
    """Extraer un caso individual (síncrono — retorna resultados completos)."""
    from backend.extraction.pipeline import process_folder
    import time

    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Caso no encontrado")

    if _main.extraction_in_progress:
        return {"status": "running", "message": "Ya hay una extraccion en progreso"}

    start = time.time()
    case.processing_status = "PENDIENTE"
    db.commit()

    try:
        stats = process_folder(db, case)
        elapsed = int(time.time() - start)
        db.refresh(case)

        fields_data = _get_fields_data(case)

        return {
            "status": "completed",
            "case_id": case_id,
            "folder_name": case.folder_name,
            "processing_status": case.processing_status,
            "fields_extracted": len(fields_data),
            "fields": fields_data,
            "documents_processed": stats.get("documents_extracted", 0),
            "documents_excluded": stats.get("documents_failed", 0),
            "suspicious_docs": stats.get("suspicious_docs", []),
            "reassigned_docs": stats.get("reassigned_docs", []),
            "cases_created": stats.get("cases_created", []),
            "corrections_injected": stats.get("corrections_injected", 0),
            "elapsed_seconds": elapsed,
            "tokens": _get_token_usage(db, case_id),
        }
    except Exception as e:
        return {
            "status": "error",
            "case_id": case_id,
            "message": str(e),
        }


@router.post("/batch")
def api_extract_batch(req: BatchRequest):
    """Extraer batch de casos en background (protegido contra doble-click)."""
    with _extraction_lock:
        if _main.extraction_in_progress:
            return {"status": "running", "message": "Ya hay una extraccion en progreso"}

    if req.case_ids:
        case_ids = req.case_ids
    else:
        db = SessionLocal()
        try:
            cases = db.query(Case.id).filter(Case.processing_status.in_(["PENDIENTE", "REVISION"])).all()
            case_ids = [c.id for c in cases]
        finally:
            db.close()

    if not case_ids:
        return {"status": "empty", "message": "No hay casos pendientes"}

    thread = threading.Thread(target=_run_extraction_cases, args=(case_ids,), daemon=True)
    thread.start()
    return {"status": "started", "message": f"Extraccion de {len(case_ids)} casos iniciada"}



@router.post("/agent/{case_id}")
def api_agent_extract(case_id: int, classify: bool = False, db: Session = Depends(get_db)):
    """Extracción con Agente IA v3: Context Engine + Multi-criterio + Razonamiento.

    Query params:
        classify: Si true, ejecuta clasificación de documentos antes de extraer
                  (mueve docs que no pertenecen a PENDIENTE DE UBICACION).
    """
    from fastapi import HTTPException
    from backend.agent.orchestrator import smart_extract_case as agent_extract
    from backend.core.settings import settings
    from backend.database.models import AuditLog
    import time

    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Caso no encontrado")

    start = time.time()
    case.processing_status = "EXTRAYENDO"
    db.commit()

    try:
        result = agent_extract(db, case_id, settings.BASE_DIR, classify_docs=classify)
        elapsed = int(time.time() - start)

        # Guardar campos extraídos en el caso
        fields = result.get("fields", {})
        field_map = {k.lower(): k for k in Case.CSV_FIELD_MAP.values()}
        for field_name, value in fields.items():
            attr = field_map.get(field_name.lower(), field_name.lower())
            if hasattr(case, attr) and value:
                setattr(case, attr, value)

        case.processing_status = "COMPLETO"
        db.commit()
        db.refresh(case)

        fields_data = _get_fields_data(case)

        # Registrar en AuditLog
        db.add(AuditLog(
            case_id=case_id,
            action="EXTRACTION_AGENT",
            new_value=f"{len(fields_data)} campos extraidos | {elapsed}s | confianza {result.get('confidence_avg', 0)}%",
        ))
        db.commit()

        return {
            "status": "completed",
            "case_id": case_id,
            "folder_name": case.folder_name,
            "processing_status": case.processing_status,
            "fields_extracted": len(fields_data),
            "fields": fields_data,
            "reasoning": result.get("reasoning", []),
            "warnings": result.get("warnings", []),
            "confidence_avg": result.get("confidence_avg", 0),
            "classification": result.get("classification"),
            "elapsed_seconds": elapsed,
            "tokens": _get_token_usage(db, case_id),
        }
    except Exception as e:
        case.processing_status = "REVISION"
        db.commit()
        return {
            "status": "error",
            "case_id": case_id,
            "message": str(e),
        }


@router.get("/agent/{case_id}/reasoning")
def api_agent_reasoning(case_id: int, db: Session = Depends(get_db)):
    """Obtener cadena de razonamiento de la última extracción de un caso."""
    from backend.agent.reasoning import get_reasoning
    return get_reasoning(db, case_id)


@router.get("/review")
def api_review_queue(db: Session = Depends(get_db)):
    return get_review_queue(db)


@router.get("/mismatched-docs")
def api_mismatched_docs(db: Session = Depends(get_db)):
    """Documentos que no corresponden al caso (detectados por verificacion de dos pasos).
    Solo muestra alertas de documentos que AÚN EXISTEN en la DB."""
    from backend.database.models import AuditLog, Document
    from pathlib import Path

    logs = db.query(AuditLog).filter(AuditLog.action == "DOC_NO_CORRESPONDE").all()
    items = []
    resolved = 0
    for log in logs:
        # Verificar si el documento aún existe en la DB y en disco
        doc = db.query(Document).filter(
            Document.case_id == log.case_id,
            Document.filename == log.old_value,
        ).first()
        if not doc or (doc.file_path and not Path(doc.file_path).exists()):
            # Documento eliminado o ya no existe — resolver automáticamente
            log.action = "DOC_NO_CORRESPONDE_RESUELTO"
            resolved += 1
            continue

        case = db.query(Case).filter(Case.id == log.case_id).first()
        items.append({
            "id": log.id,
            "case_id": log.case_id,
            "case_name": case.folder_name if case else "",
            "filename": log.old_value,
            "radicado_encontrado": log.new_value,
            "timestamp": log.timestamp.isoformat() if log.timestamp else "",
        })

    if resolved > 0:
        db.commit()
    return items


@router.delete("/mismatched-docs/{log_id}")
def api_dismiss_mismatched_doc(log_id: int, db: Session = Depends(get_db)):
    """Descartar/resolver una alerta de documento no correspondiente."""
    from backend.database.models import AuditLog
    log = db.query(AuditLog).filter(AuditLog.id == log_id, AuditLog.action == "DOC_NO_CORRESPONDE").first()
    if not log:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Alerta no encontrada")
    log.action = "DOC_NO_CORRESPONDE_RESUELTO"
    db.commit()
    return {"message": "Alerta resuelta"}


@router.delete("/mismatched-docs")
def api_dismiss_all_mismatched(db: Session = Depends(get_db)):
    """Resolver TODAS las alertas de documentos no correspondientes."""
    from backend.database.models import AuditLog
    count = db.query(AuditLog).filter(AuditLog.action == "DOC_NO_CORRESPONDE").update(
        {"action": "DOC_NO_CORRESPONDE_RESUELTO"}
    )
    db.commit()
    return {"message": f"{count} alertas resueltas"}


@router.post("/verify-all")
def api_verify_all_documents(db: Session = Depends(get_db)):
    """Auditoría retroactiva: verificar pertenencia de TODOS los documentos."""
    from backend.extraction.pipeline import verify_all_documents
    stats = verify_all_documents(db)
    return stats


@router.post("/audit")
def api_full_audit(db: Session = Depends(get_db)):
    """Auditoría molecular completa: disco, DB, documentos, nombres, emails."""
    from pathlib import Path
    from backend.config import BASE_DIR
    from backend.database.models import Document, Email
    from backend.extraction.pipeline import verify_all_documents
    import re, os

    VALID_EXT = {".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg", ".md"}

    # 1. Sync disco ↔ DB
    disk_folders = {}
    for entry in sorted(os.listdir(str(BASE_DIR))):
        full = os.path.join(str(BASE_DIR), entry)
        if os.path.isdir(full) and re.match(r'^20[2-4][0-9]', entry):
            files = [f for f in os.listdir(full) if os.path.isfile(os.path.join(full, f))]
            disk_folders[entry] = {"path": full, "count": len(files)}

    db_names = {c.folder_name for c in db.query(Case.folder_name).filter(
        Case.folder_name.isnot(None), Case.folder_name != "None",
    ).all()}

    only_disk = sorted(set(disk_folders.keys()) - db_names)
    only_db = sorted(db_names - set(disk_folders.keys()))

    # 2. Pendiente revisión
    pendientes = [fn for fn in disk_folders if "PENDIENTE" in fn.upper()]

    # 3. Carpetas vacías
    vacias = [fn for fn, info in disk_folders.items() if info["count"] == 0]

    # 4. Sin accionante
    sin_acc = [{"id": c.id, "folder": c.folder_name} for c in db.query(Case).filter(
        Case.folder_name.isnot(None), Case.folder_name != "None",
    ).all() if not (c.accionante or "").strip() or c.accionante == "None"]

    # 5. Sin radicado 23
    sin_rad = [{"id": c.id, "folder": c.folder_name} for c in db.query(Case).filter(
        Case.folder_name.isnot(None), Case.folder_name != "None",
    ).all() if not (c.radicado_23_digitos or "").strip() or c.radicado_23_digitos == "None"]

    # 6. Emails sin caso
    emails_sin_caso = db.query(Email).filter(Email.case_id.is_(None)).count()

    # 7. Verificar TODOS los documentos
    verify_stats = verify_all_documents(db)

    # 8. Docs fantasma (limpiar)
    fantasma = 0
    for doc in db.query(Document).all():
        if doc.file_path and not Path(doc.file_path).exists():
            db.delete(doc)
            fantasma += 1
    if fantasma > 0:
        db.commit()

    return {
        "disco": len(disk_folders),
        "db": len(db_names),
        "solo_disco": only_disk,
        "solo_db": only_db,
        "pendientes": pendientes,
        "vacias": vacias,
        "sin_accionante": sin_acc,
        "sin_radicado_23": sin_rad,
        "emails_sin_caso": emails_sin_caso,
        "docs_fantasma_limpiados": fantasma,
        "verificacion": verify_stats,
        "total_problemas": len(only_disk) + len(only_db) + len(pendientes) + len(vacias) + len(sin_acc) + len(sin_rad) + emails_sin_caso + verify_stats.get("sospechoso", 0),
    }




@router.get("/duplicate-docs")
def api_duplicate_docs(db: Session = Depends(get_db)):
    """Detectar documentos duplicados entre carpetas (mismo archivo en 2+ casos)."""
    from backend.extraction.pipeline import detect_duplicate_documents
    return detect_duplicate_documents(db)


@router.get("/suspicious-docs")
def api_suspicious_docs(db: Session = Depends(get_db)):
    """Documentos sospechosos o que no pertenecen a su carpeta.
    Auto-resuelve los que ya fueron eliminados del disco."""
    from backend.database.models import Document
    from pathlib import Path
    docs = db.query(Document).filter(
        Document.verificacion.in_(["SOSPECHOSO", "NO_PERTENECE"])
    ).all()
    items = []
    cleaned = 0
    for doc in docs:
        # Si el archivo ya no existe en disco, resolver automáticamente
        if doc.file_path and not Path(doc.file_path).exists():
            doc.verificacion = "OK"
            doc.verificacion_detalle = "Auto-resuelto: archivo eliminado del disco"
            cleaned += 1
            continue
        case = db.query(Case).filter(Case.id == doc.case_id).first()
        items.append({
            "doc_id": doc.id,
            "case_id": doc.case_id,
            "case_name": case.folder_name if case else "",
            "filename": doc.filename,
            "verificacion": doc.verificacion,
            "detalle": doc.verificacion_detalle,
        })
    if cleaned > 0:
        db.commit()
    return items


@router.post("/docs/{doc_id}/mark-ok")
def api_mark_doc_ok(doc_id: int, db: Session = Depends(get_db)):
    """Marcar un documento sospechoso como OK (pertenece al caso)."""
    from backend.database.models import Document
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404)
    doc.verificacion = "OK"
    doc.verificacion_detalle = "Confirmado manualmente"
    db.commit()
    return {"message": "Documento marcado como OK"}


@router.post("/docs/{doc_id}/move/{target_case_id}")
def api_move_doc(doc_id: int, target_case_id: int, db: Session = Depends(get_db)):
    """Mover un documento a otro caso (cambia case_id y mueve archivo en disco)."""
    from backend.database.models import Document
    from pathlib import Path

    doc = db.query(Document).filter(Document.id == doc_id).first()
    target = db.query(Case).filter(Case.id == target_case_id).first()
    if not doc or not target:
        from fastapi import HTTPException
        raise HTTPException(status_code=404)

    # Mover archivo en disco
    if doc.file_path and target.folder_path:
        old_path = Path(doc.file_path)
        new_path = Path(target.folder_path) / doc.filename
        if old_path.exists() and Path(target.folder_path).exists():
            old_path.rename(new_path)
            doc.file_path = str(new_path)

    old_case_id = doc.case_id
    doc.case_id = target_case_id
    doc.verificacion = "OK"
    doc.verificacion_detalle = f"Movido desde caso {old_case_id}"
    db.commit()
    return {"message": f"Documento movido a {target.folder_name}"}
