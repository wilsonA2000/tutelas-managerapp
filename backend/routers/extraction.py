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
from backend.core.settings import settings

router = APIRouter(prefix="/api/extraction", tags=["extraction"])

# Estado global compartido con main.py
import backend.main as _main


class BatchRequest(BaseModel):
    case_ids: list[int] | None = None
    classify_docs: bool = False


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


_progress_lock = threading.Lock()
MAX_WORKERS = 3


def _run_extraction_cases(case_ids: list[int], classify_docs: bool = False):
    """Ejecutar extraccion en background con paralelizacion (3 workers)."""
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from backend.services.backup_service import auto_backup

    _start = time.time()
    _main.extraction_in_progress = True
    _main.extraction_progress = {
        "current": 0, "total": len(case_ids), "case_name": "Iniciando...",
        "success": 0, "errors": 0, "progress_pct": 0, "elapsed_seconds": 0,
        "step": "Preparando extraccion...", "phase": "",
        "failed_cases": [],
    }

    def _update_progress(**kwargs):
        with _progress_lock:
            _main.extraction_progress.update(kwargs)
            total = _main.extraction_progress["total"]
            current = _main.extraction_progress["current"]
            _main.extraction_progress["progress_pct"] = round((current / total) * 100) if total > 0 else 0
            _main.extraction_progress["elapsed_seconds"] = round(time.time() - _start)

    # Thread para actualizar elapsed_seconds cada segundo
    _elapsed_stop = threading.Event()
    def _update_elapsed():
        while not _elapsed_stop.is_set():
            with _progress_lock:
                _main.extraction_progress["elapsed_seconds"] = round(time.time() - _start)
                done = _main.extraction_progress["current"]
                if done > 0:
                    avg = (time.time() - _start) / done
                    remaining = (len(case_ids) - done) * avg / MAX_WORKERS
                    _main.extraction_progress["eta_seconds"] = round(remaining)
            _elapsed_stop.wait(1)
    elapsed_thread = threading.Thread(target=_update_elapsed, daemon=True)
    elapsed_thread.start()

    # Lock para operaciones de archivo (rename, move) — evita race conditions
    _file_ops_lock = threading.Lock()

    def _process_one_case(cid: int) -> tuple[bool, str, str | None]:
        """Procesar un caso en su propio thread. Retorna (ok, folder_name, error_reason)."""
        db = SessionLocal()
        folder_name = f"ID {cid}"
        try:
            case = db.query(Case).filter(Case.id == cid).first()
            if not case:
                return False, folder_name, "case no encontrado"

            folder_name = (case.folder_name or folder_name)[:60]
            with _progress_lock:
                _main.extraction_progress["step"] = f"Procesando: {folder_name}..."
                _main.extraction_progress["phase"] = "Clasificando..." if classify_docs else "Extrayendo..."

            if classify_docs:
                try:
                    with _file_ops_lock:
                        from backend.agent.orchestrator import classify_and_clean_folder
                        classify_and_clean_folder(db, case, settings.BASE_DIR)
                except Exception as e:
                    _main.add_monitor_log(f"Clasificacion caso {cid}: {str(e)[:80]}", level="warning")

            with _progress_lock:
                _main.extraction_progress["phase"] = "Extrayendo..."

            if settings.UNIFIED_EXTRACTOR_ENABLED:
                from backend.extraction.unified import unified_extract
                stats = unified_extract(db, case, settings.BASE_DIR)
            else:
                stats = process_folder(db, case)

            if stats.get("renamed"):
                with _file_ops_lock:
                    db.refresh(case)

            if stats.get("ai_error") and case.processing_status != "COMPLETO":
                case.processing_status = "REVISION"
                db.commit()
                return False, folder_name, str(stats.get("ai_error"))[:120]

            return True, folder_name, None
        except Exception as e:
            try:
                db.rollback()
                case = db.query(Case).filter(Case.id == cid).first()
                if case:
                    case.processing_status = "REVISION"
                    db.commit()
            except Exception:
                pass
            _main.add_monitor_log(f"Error caso {cid}: {str(e)[:100]}", level="error")
            return False, folder_name, str(e)[:120]
        finally:
            db.close()

    try:
        _update_progress(step="Creando backup automatico...", phase="Backup")
        auto_backup("pre_extraction")

        _update_progress(
            step=f"Extrayendo {len(case_ids)} casos ({MAX_WORKERS} en paralelo)...",
            phase="Extraccion",
        )

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for cid in case_ids:
                if not _main.extraction_in_progress:
                    break
                future = executor.submit(_process_one_case, cid)
                futures[future] = cid

            for future in as_completed(futures):
                if not _main.extraction_in_progress:
                    _main.add_monitor_log("Extraccion cancelada por usuario")
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

                cid = futures[future]
                try:
                    result = future.result()
                    if isinstance(result, tuple) and len(result) == 3:
                        ok, folder_name, reason = result
                    else:
                        ok, folder_name, reason = bool(result), f"ID {cid}", None
                    with _progress_lock:
                        _main.extraction_progress["current"] += 1
                        if ok:
                            _main.extraction_progress["success"] += 1
                        else:
                            _main.extraction_progress["errors"] += 1
                            _main.extraction_progress["failed_cases"].append({
                                "id": cid, "folder": folder_name, "reason": reason or "desconocido",
                            })
                except Exception as e:
                    with _progress_lock:
                        _main.extraction_progress["current"] += 1
                        _main.extraction_progress["errors"] += 1
                        _main.extraction_progress["failed_cases"].append({
                            "id": cid, "folder": f"ID {cid}", "reason": str(e)[:120],
                        })

                _update_progress()

        ok = _main.extraction_progress["success"]
        total = _main.extraction_progress["total"]
        _update_progress(
            case_name=f"Completado: {ok}/{total} exitosos",
            step=f"Completado: {ok}/{total} exitosos, {_main.extraction_progress['errors']} errores",
            progress_pct=100, phase="Completado",
        )
        _main.add_monitor_log(f"Extraccion terminada: {ok}/{total} exitosos ({MAX_WORKERS} workers)")

    except Exception as e:
        _main.add_monitor_log(f"Error en extraccion: {e}", level="error")
    finally:
        _main.extraction_in_progress = False
        _elapsed_stop.set()


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
        if settings.UNIFIED_EXTRACTOR_ENABLED:
            from backend.extraction.unified import unified_extract
            stats = unified_extract(db, case, settings.BASE_DIR)
        else:
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
            "method": stats.get("method", "pipeline"),
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

    thread = threading.Thread(target=_run_extraction_cases, args=(case_ids, req.classify_docs), daemon=True)
    thread.start()
    classify_msg = " + clasificacion de documentos" if req.classify_docs else ""
    return {"status": "started", "message": f"Extraccion de {len(case_ids)} casos iniciada ({MAX_WORKERS} en paralelo{classify_msg})"}



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
    """Documentos que no corresponden al caso. Optimizado v4.0: 1 JOIN query."""
    from backend.database.models import AuditLog, Document

    # UNA query con JOIN — en vez de N+1
    results = db.query(AuditLog, Document, Case).outerjoin(
        Document, (Document.case_id == AuditLog.case_id) & (Document.filename == AuditLog.old_value),
    ).join(
        Case, Case.id == AuditLog.case_id,
    ).filter(
        AuditLog.action == "DOC_NO_CORRESPONDE",
    ).all()

    items = []
    resolved = 0
    for log, doc, case in results:
        if not doc:
            log.action = "DOC_NO_CORRESPONDE_RESUELTO"
            resolved += 1
            continue
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

    # 4. Sin accionante — query directa con filtro SQL (no cargar todos)
    sin_acc = [{"id": c.id, "folder": c.folder_name} for c in db.query(Case.id, Case.folder_name).filter(
        Case.folder_name.isnot(None), Case.folder_name != "None",
        or_(Case.accionante.is_(None), Case.accionante == "", Case.accionante == "None"),
    ).all()]

    # 5. Sin radicado 23 — query directa con filtro SQL
    sin_rad = [{"id": c.id, "folder": c.folder_name} for c in db.query(Case.id, Case.folder_name).filter(
        Case.folder_name.isnot(None), Case.folder_name != "None",
        or_(Case.radicado_23_digitos.is_(None), Case.radicado_23_digitos == "", Case.radicado_23_digitos == "None"),
    ).all()]

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




@router.get("/benchmark")
def api_benchmark(limit: int = 20, db: Session = Depends(get_db)):
    """Benchmark: comparar regex IR vs datos actuales en DB para N casos COMPLETO.

    No modifica datos — solo analiza y compara.
    Retorna cobertura campo por campo + resumen.
    """
    import re
    import time
    from backend.extraction.ir_builder import build_case_ir
    from backend.agent.extractors.registry import _EXTRACTORS
    from backend.agent.extractors.base import ExtractionResult
    from backend.agent.forest_extractor import extract_forest_from_sources
    from backend.database.models import Email, AuditLog, TokenUsage
    from backend.extraction.pipeline import classify_doc_type

    # Tomar N casos COMPLETO con mas campos
    cases = db.query(Case).filter(
        Case.processing_status == "COMPLETO",
        Case.folder_path.isnot(None),
    ).order_by(Case.updated_at.desc()).limit(limit).all()

    FIELDS = [
        "radicado_23_digitos", "radicado_forest", "accionante", "accionados",
        "juzgado", "ciudad", "fecha_ingreso", "derecho_vulnerado",
        "sentido_fallo_1st", "fecha_fallo_1st", "impugnacion", "asunto",
        "pretensiones", "observaciones", "abogado_responsable",
    ]

    results = []
    field_stats = {f: {"db_filled": 0, "regex_filled": 0, "match": 0, "mismatch": 0, "regex_only": 0, "db_only": 0} for f in FIELDS}
    total_time = 0

    for case in cases:
        start = time.time()
        case_result = {"id": case.id, "folder": case.folder_name, "fields": {}}

        # Construir IR
        try:
            case_ir = build_case_ir(db, case)
        except Exception as e:
            case_result["error"] = f"IR failed: {str(e)[:80]}"
            results.append(case_result)
            continue

        # Preparar doc_dicts
        doc_dicts = []
        for doc_ir in case_ir.documents:
            doc_dicts.append({
                "filename": doc_ir.filename, "doc_type": doc_ir.doc_type,
                "text": doc_ir.full_text, "full_text": doc_ir.full_text,
                "content": doc_ir.full_text, "priority": doc_ir.priority,
                "zones": [{"zone_type": z.zone_type, "text": z.text, "metadata": z.metadata,
                           "page": z.page, "confidence": z.confidence} for z in doc_ir.zones],
            })

        # Ejecutar extractores regex
        case_emails = db.query(Email).filter(Email.case_id == case.id).all()
        regex_results = {}

        for field_name, extractor in _EXTRACTORS.items():
            try:
                result = extractor.extract_regex(doc_dicts, case_emails)
                if result:
                    is_valid, _ = extractor.validate(result.value)
                    if is_valid:
                        regex_results[field_name] = result.value
            except Exception:
                pass

        # FOREST
        forest = extract_forest_from_sources(doc_dicts, case_emails)
        if forest:
            regex_results["radicado_forest"] = forest.value

        elapsed = round(time.time() - start, 2)
        total_time += elapsed
        case_result["elapsed_s"] = elapsed
        case_result["ir_docs"] = len(case_ir.documents)
        case_result["ir_zones"] = sum(len(d.zones) for d in case_ir.documents)

        # Comparar campo por campo
        for f in FIELDS:
            attr = Case.CSV_FIELD_MAP.get(f, f)
            db_val = (getattr(case, attr, None) or "").strip()
            regex_val = (regex_results.get(f, "") or "").strip()

            status = "empty"
            if db_val and regex_val:
                # Normalizar para comparacion: quitar guiones, puntos, espacios
                db_norm = re.sub(r'[\s\-\.\,]', '', db_val.upper())
                regex_norm = re.sub(r'[\s\-\.\,]', '', regex_val.upper())
                if db_norm == regex_norm:
                    status = "match"
                    field_stats[f]["match"] += 1
                else:
                    status = "mismatch"
                    field_stats[f]["mismatch"] += 1
                field_stats[f]["db_filled"] += 1
                field_stats[f]["regex_filled"] += 1
            elif db_val:
                status = "db_only"
                field_stats[f]["db_only"] += 1
                field_stats[f]["db_filled"] += 1
            elif regex_val:
                status = "regex_only"
                field_stats[f]["regex_only"] += 1
                field_stats[f]["regex_filled"] += 1

            case_result["fields"][f] = {
                "status": status,
                "db": db_val[:80] if db_val else "",
                "regex": regex_val[:80] if regex_val else "",
            }

        results.append(case_result)

    # Token usage comparison: pipeline vs unified
    token_stats = {"pipeline": {"count": 0, "tokens": 0}, "unified": {"count": 0, "tokens": 0}}
    for tu in db.query(TokenUsage).order_by(TokenUsage.timestamp.desc()).limit(500).all():
        key = "unified" if "unified" in (tu.model or "").lower() or "compact" in (tu.model or "").lower() else "pipeline"
        token_stats[key]["count"] += 1
        token_stats[key]["tokens"] += (tu.tokens_input or 0) + (tu.tokens_output or 0)

    return {
        "total_cases": len(cases),
        "total_time_s": round(total_time, 1),
        "avg_time_per_case_s": round(total_time / len(cases), 2) if cases else 0,
        "field_coverage": field_stats,
        "token_comparison": token_stats,
        "cases": results,
    }


@router.get("/duplicate-docs")
def api_duplicate_docs(db: Session = Depends(get_db)):
    """Detectar documentos duplicados entre carpetas (mismo archivo en 2+ casos)."""
    from backend.extraction.pipeline import detect_duplicate_documents
    return detect_duplicate_documents(db)


@router.get("/suspicious-docs")
def api_suspicious_docs(db: Session = Depends(get_db)):
    """Documentos sospechosos o que no pertenecen. Optimizado v4.0: 1 JOIN query."""
    from backend.database.models import Document

    # UNA query con JOIN — en vez de N+1
    results = db.query(Document, Case).join(
        Case, Case.id == Document.case_id,
    ).filter(
        Document.verificacion.in_(["SOSPECHOSO", "NO_PERTENECE"]),
    ).all()

    items = []
    for doc, case in results:
        items.append({
            "doc_id": doc.id,
            "case_id": doc.case_id,
            "case_name": case.folder_name if case else "",
            "filename": doc.filename,
            "verificacion": doc.verificacion,
            "detalle": doc.verificacion_detalle,
        })
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
    """Mover un documento a otro caso.

    v4.8 Provenance: si el doc tiene email_id (vino por Gmail), se mueven
    TAMBIEN todos sus hermanos del mismo paquete email. Regla "hermanos
    viajan juntos" es absoluta — es imposible por diseño separar el cuerpo
    de un correo de sus adjuntos.

    Para docs legacy (sin email_id), solo se mueve el doc individual.
    """
    from backend.database.models import Document
    from backend.services.sibling_mover import move_document_or_package

    doc = db.query(Document).filter(Document.id == doc_id).first()
    target = db.query(Case).filter(Case.id == target_case_id).first()
    if not doc or not target:
        from fastapi import HTTPException
        raise HTTPException(status_code=404)

    result = move_document_or_package(db, doc_id, target_case_id, reason="manual_ui_move")
    if result.get("errors"):
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="; ".join(result["errors"]))

    db.commit()

    if result["package_mode"]:
        n = len(result["moved_ids"])
        return {
            "message": f"Paquete movido a {target.folder_name}: {n} documentos hermanos (email_id={result['email_id']})",
            "package_mode": True,
            "moved_ids": result["moved_ids"],
        }
    else:
        return {
            "message": f"Documento movido a {target.folder_name}",
            "package_mode": False,
            "moved_ids": result["moved_ids"],
        }


@router.get("/docs/{doc_id}/suggest-target")
def api_suggest_target(doc_id: int, db: Session = Depends(get_db)):
    """Sugerir caso destino para un documento NO_PERTENECE.

    Busca por radicado 23d, radicado corto y accionante en el texto del documento.
    """
    import re
    from backend.database.models import Document

    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404)

    text = (doc.extracted_text or "")[:10000].upper()
    detalle = doc.verificacion_detalle or ""
    source_case = db.query(Case).filter(Case.id == doc.case_id).first()
    suggestions = []

    # 1. Buscar radicado 23d en el texto
    rad23_matches = re.findall(r'(68[\d]{17,21})', re.sub(r'[\s\-\.]', '', text))
    source_rad23 = re.sub(r'[\s\-\.]', '', (source_case.radicado_23_digitos or '') if source_case else '')

    all_cases = db.query(Case).filter(Case.id != doc.case_id).all()

    for rad23 in rad23_matches:
        if len(rad23) >= 20 and rad23 != source_rad23:
            for c in all_cases:
                c_rad = re.sub(r'[\s\-\.]', '', c.radicado_23_digitos or '')
                if c_rad and len(c_rad) >= 15 and c_rad[-12:] == rad23[-12:]:
                    suggestions.append({
                        "case_id": c.id,
                        "folder_name": c.folder_name,
                        "confidence": "ALTA",
                        "reason": f"Radicado 23d coincide: {rad23}",
                    })

    # 2. Buscar por radicado corto en detalle de verificacion
    m = re.search(r'Radicado\s+(20\d{2})[-\s]?0*(\d{2,5})', detalle)
    if m and not suggestions:
        target_seq = m.group(2).zfill(5)
        pattern = f"{m.group(1)}-{target_seq}"
        for c in all_cases:
            if c.folder_name and pattern in c.folder_name:
                suggestions.append({
                    "case_id": c.id,
                    "folder_name": c.folder_name,
                    "confidence": "MEDIA",
                    "reason": f"Radicado corto coincide: {pattern}",
                })

    # 3. Buscar por accionante mencionado en filename
    if not suggestions:
        fname_upper = doc.filename.upper()
        for c in all_cases:
            if c.accionante and len(c.accionante) > 5:
                # Buscar primer apellido del accionante en el filename
                first_word = c.accionante.split()[0].upper() if c.accionante else ""
                if first_word and len(first_word) >= 4 and first_word in fname_upper:
                    suggestions.append({
                        "case_id": c.id,
                        "folder_name": c.folder_name,
                        "confidence": "BAJA",
                        "reason": f"Nombre '{first_word}' aparece en filename",
                    })

    return {
        "doc_id": doc_id,
        "filename": doc.filename,
        "current_case": source_case.folder_name if source_case else None,
        "suggestions": suggestions[:5],
    }


# ============================================================
# v4.7 — Benchmark comparativo (metricas agregadas)
# ============================================================

@router.get("/metrics/comparison")
def api_metrics_comparison(
    since: str | None = None,
    until: str | None = None,
    provider: str | None = None,
    version_tag: str = "v4.7",
    db: Session = Depends(get_db),
):
    """Benchmark de metricas agregadas sobre TokenUsage + Case.

    Query params:
    - since: ISO timestamp (ej: '2026-04-09T11:00:00'). Default: ultimas 24h
    - until: ISO timestamp. Default: ahora
    - provider: filtrar por provider ('deepseek', 'anthropic', etc)
    - version_tag: etiqueta del reporte (default 'v4.7')

    Retorna JSON con: cost, latency, coverage, errors, providers_used,
    problematic_cases, projection_1000_cases.

    Reusa backend.reports.benchmark.compute_period_metrics (logica pura).
    """
    from datetime import datetime, timedelta
    from backend.reports.benchmark import compute_period_metrics

    def _parse_iso(s: str | None, default: datetime) -> datetime:
        if not s:
            return default
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
        except (ValueError, AttributeError):
            return default

    now = datetime.utcnow()
    since_dt = _parse_iso(since, now - timedelta(hours=24))
    until_dt = _parse_iso(until, now)

    return compute_period_metrics(
        db=db,
        since=since_dt,
        until=until_dt,
        provider=provider,
        version_tag=version_tag,
    )
