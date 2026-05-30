"""Router de extraccion."""

import threading
from backend.core.time import utcnow
_extraction_lock = threading.Lock()

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database.database import get_db, SessionLocal
from backend.database.models import Case
from backend.services.extraction_service import get_review_queue
from backend.core.settings import settings

router = APIRouter(prefix="/api/extraction", tags=["extraction"])

# Estado global compartido con main.py
import backend.main as _main


class BatchRequest(BaseModel):
    case_ids: list[int] | None = None
    classify_docs: bool = False
    force: bool = False
    use_llm: bool = False  # selector de motor: False=determinista, True=Qwen local (default batch: determinista)


def _guard_folder_consistency(db: Session, case_id: int, force: bool) -> None:
    """Rechaza la extracción si la carpeta tiene documentos sin depurar. Primero depurar,
    luego extraer (extraer una carpeta sucia contamina los campos). `force=True` la omite."""
    if force:
        return
    from fastapi import HTTPException
    from backend.v9.folder_consistency import check_folder_consistency
    cons = check_folder_consistency(db, case_id)
    if not cons["clean"]:
        raise HTTPException(status_code=409, detail={
            "error": "carpeta_inconsistente",
            "message": (
                f"La carpeta tiene {cons['n_issues']} documento(s) sin depurar "
                "(no pertenecen / sospechosos / conflación de radicado). Resuélvelos antes "
                "de extraer para no contaminar los campos. Reintenta con force=true si estás seguro."
            ),
            "n_issues": cons["n_issues"],
            "issues": cons["issues"],
        })


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
MAX_WORKERS = settings.EXTRACTION_MAX_WORKERS


def _extraction_worker_init():
    """Precarga singletons + log PID (assert paralelismo real) por worker process.

    v6.1.1: skipea Presidio analyzer si LOCAL_ONLY=true (ahorra ~300 MB RAM por worker).
    """
    import os, logging
    logging.getLogger("tutelas.extraction.worker").info(
        "Worker process started: pid=%s ppid=%s", os.getpid(), os.getppid()
    )
    try:
        from backend.cognition.ner_spacy import _get_nlp
        _get_nlp()
    except Exception:
        pass


def _process_one_case_router(args: tuple) -> tuple:
    """Worker top-level (picklable) para ProcessPool. args=(cid, _classify_docs).

    (Modernización Fase 7.3) Corre el pipeline v9 (`extract_case`) por caso. `persist.py`
    solo rellena campos vacíos → el batch no puede pisar el cuadro v9, solo añadir. El
    flag `_classify_docs` ya no aplica (v9 clasifica los docs vía `doc_librarian` en la
    ingesta). Retorna (ok, folder_name, error_reason, cid). Reintenta 3× ante
    OperationalError transitorios de SQLite.
    """
    import time as _time
    from sqlalchemy.exc import OperationalError as _OpErr
    # tupla de 3 (cid, classify_docs, use_llm); tolera la de 2 antigua por compatibilidad
    cid, _classify_docs, *_rest = args
    _use_llm = _rest[0] if _rest else False
    from backend.database.database import SessionLocal as _SessionLocal
    from backend.database.models import Case as _Case
    from backend.v9.pipeline import extract_case as _extract_case

    last_err = None
    for attempt in range(3):
        if attempt > 0:
            _time.sleep(0.5 * (2 ** attempt))  # 0.5s, 1s, 2s
        db = _SessionLocal()
        folder_name = f"ID {cid}"
        try:
            case = db.query(_Case).filter(_Case.id == cid).first()
            if not case:
                return False, folder_name, "case no encontrado", cid

            folder_name = (case.folder_name or folder_name)[:60]
            _extract_case(db, cid, dry_run=False, use_llm=_use_llm)
            try:
                case.processing_status = "COMPLETO"
                db.commit()
            except Exception:
                db.rollback()
            return True, folder_name, None, cid
        except _OpErr as e:
            # OperationalError: lock o disk I/O. Reintentar.
            last_err = e
            try:
                db.rollback()
            except Exception:
                pass
            continue
        except Exception as e:
            try:
                db.rollback()
                case = db.query(_Case).filter(_Case.id == cid).first()
                if case:
                    case.processing_status = "REVISION"
                    db.commit()
            except Exception:
                pass
            return False, folder_name, str(e)[:120], cid
        finally:
            db.close()

    # Agotó retries por OperationalError. Marcar REVISION en sesión nueva.
    try:
        db2 = _SessionLocal()
        case = db2.query(_Case).filter(_Case.id == cid).first()
        if case:
            case.processing_status = "REVISION"
            db2.commit()
        db2.close()
    except Exception:
        pass
    return False, folder_name, f"OperationalError x3: {str(last_err)[:90]}", cid


def _run_extraction_cases(case_ids: list[int], classify_docs: bool = False, use_llm: bool = False):
    """Ejecutar extraccion en background con ProcessPool real (sin GIL)."""
    import time
    from concurrent.futures import ProcessPoolExecutor, as_completed
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

    try:
        # Ciclo de vida del motor IA. Con use_llm (flujo del operador) la app
        # ENCIENDE el server on-demand (begin_extraction) y lo apaga sola tras
        # quedar idle (ver llm_mutex). Sin use_llm (scripts deterministas) se
        # mantiene la pausa para liberar RAM. El finally llama end_extraction.
        if use_llm:
            try:
                from backend.services.llm_mutex import begin_extraction
                _update_progress(step="Encendiendo motor de IA...", phase="Setup")
                begin_extraction()
            except Exception as e:
                logger.warning("llm_mutex begin_extraction falló: %s", e)
        else:
            try:
                from backend.services.llm_mutex import pause_llm_for_extraction
                paused = pause_llm_for_extraction()
                if paused:
                    _update_progress(step="LLM pausado para liberar RAM...", phase="Setup")
            except Exception as e:
                logger.warning("llm_mutex pause falló: %s", e)

        _update_progress(step="Creando backup automatico...", phase="Backup")
        auto_backup("pre_extraction")

        _update_progress(
            step=f"Extrayendo {len(case_ids)} casos (ProcessPool={MAX_WORKERS})...",
            phase="Extraccion",
        )

        with ProcessPoolExecutor(max_workers=MAX_WORKERS, initializer=_extraction_worker_init) as executor:
            futures = {}
            for cid in case_ids:
                if not _main.extraction_in_progress:
                    break
                future = executor.submit(_process_one_case_router, (cid, classify_docs, use_llm))
                futures[future] = cid

            for future in as_completed(futures):
                if not _main.extraction_in_progress:
                    _main.add_monitor_log("Extraccion cancelada por usuario")
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

                cid = futures[future]
                try:
                    result = future.result()
                    if isinstance(result, tuple) and len(result) >= 3:
                        ok, folder_name, reason = result[0], result[1], result[2]
                    else:
                        ok, folder_name, reason = bool(result), f"ID {cid}", None
                    with _progress_lock:
                        _main.extraction_progress["current"] += 1
                        _main.extraction_progress["case_name"] = folder_name
                        _main.extraction_progress["step"] = f"Procesado: {folder_name}"
                        if ok:
                            _main.extraction_progress["success"] += 1
                        else:
                            _main.extraction_progress["errors"] += 1
                            _main.extraction_progress["failed_cases"].append({
                                "id": cid, "folder": folder_name, "reason": reason or "desconocido",
                            })
                            _main.add_monitor_log(f"Error caso {cid}: {(reason or 'desconocido')[:100]}", level="error")
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
        if use_llm:
            try:
                from backend.services.llm_mutex import end_extraction
                end_extraction()
            except Exception as e:
                logger.warning("llm_mutex end_extraction falló: %s", e)
        _main.extraction_in_progress = False
        _elapsed_stop.set()


@router.get("/llm-status")
def api_llm_status():
    """Estado del motor de IA para el semáforo de la UI (solo lectura).

    server: "off" · "starting" (encendiendo/cargando) · "ready".
    extracting: hay una extracción en curso (individual, lote o avanzado).
    """
    try:
        from backend.services.llm_mutex import lifecycle_state
        st = lifecycle_state()
    except Exception as e:
        logger.warning("lifecycle_state falló: %s", e)
        st = {"server": "off", "extracting": False}
    st["extracting"] = bool(st.get("extracting")) or bool(_main.extraction_in_progress)
    return st


@router.get("/folder-consistency/{case_id}")
def api_folder_consistency(case_id: int, db: Session = Depends(get_db)):
    """Pre-chequeo de consistencia de carpeta para la UI: lista documentos sin depurar
    (no pertenecen / sospechosos / conflación cross-juzgado). El frontend lo llama ANTES
    de ofrecer "Extraer" — si no está limpia, bloquea y manda a depurar primero."""
    from backend.v9.folder_consistency import check_folder_consistency
    return check_folder_consistency(db, case_id)


@router.post("/single/{case_id}")
def api_extract_single(case_id: int, force: bool = False, use_llm: bool = True, db: Session = Depends(get_db)):
    """Extraer un caso individual con el pipeline v9 (síncrono).

    (Modernización Fase 7.3) Usa `backend.v9.pipeline.extract_case` en vez del motor v8.
    `persist.py` solo RELLENA campos vacíos — nunca sobrescribe valores ya extraídos ni
    los editados a mano —, así que pulsar "Extraer" es seguro: puede añadir datos, jamás
    pisar el cuadro v9. El motor v8 (`unified_cognitive` / `cognition/*`) ya no se usa aquí.

    Gate de consistencia: si la carpeta tiene documentos sin depurar (NO_PERTENECE /
    SOSPECHOSO / PENDIENTE_OCR / conflación cross-juzgado) se rechaza con HTTP 409 —
    extraer una carpeta sucia contamina los campos. Pasar `force=true` para omitir.
    """
    import time
    from backend.v9.pipeline import extract_case

    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Caso no encontrado")

    _guard_folder_consistency(db, case_id, force)

    if _main.extraction_in_progress:
        return {"status": "running", "message": "Ya hay una extraccion en progreso"}

    start = time.time()
    _llm_lifecycle = False
    try:
        if use_llm:
            from backend.services.llm_mutex import begin_extraction
            begin_extraction()
            _llm_lifecycle = True
        result = extract_case(db, case_id, dry_run=False, use_llm=use_llm)
        # Marca el caso como procesado (semántica de la UI; v9 no gestiona processing_status).
        try:
            case.processing_status = "COMPLETO"
            db.commit()
        except Exception:
            db.rollback()
        db.refresh(case)
        fields_data = _get_fields_data(case)

        return {
            "status": "completed",
            "case_id": case_id,
            "folder_name": case.folder_name,
            "processing_status": case.processing_status,
            "fields_extracted": len(fields_data),
            "fields": fields_data,
            "completitud_v9": result.fields.completitud(),
            "documents_processed": result.docs_processed,
            "documents_excluded": result.docs_failed,
            "llm_calls": result.llm_calls,
            "warnings": result.warnings,
            "elapsed_seconds": int(time.time() - start),
            "tokens": _get_token_usage(db, case_id),
            "method": "v9.pipeline",
        }
    except Exception as e:
        db.rollback()
        return {
            "status": "error",
            "case_id": case_id,
            "message": str(e),
        }
    finally:
        if _llm_lifecycle:
            from backend.services.llm_mutex import end_extraction
            end_extraction()


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

    # Gate de consistencia: no extraer carpetas sin depurar (contamina los campos).
    skipped: list[int] = []
    if not req.force:
        from backend.v9.folder_consistency import check_folder_consistency
        db = SessionLocal()
        try:
            clean_ids = []
            for cid in case_ids:
                if check_folder_consistency(db, cid)["clean"]:
                    clean_ids.append(cid)
                else:
                    skipped.append(cid)
            case_ids = clean_ids
        finally:
            db.close()

    if not case_ids:
        return {"status": "empty", "message": f"Ninguna carpeta está depurada ({len(skipped)} con inconsistencias). Resuélvelas o usa force.", "skipped": skipped}

    thread = threading.Thread(target=_run_extraction_cases, args=(case_ids, req.classify_docs, req.use_llm), daemon=True)
    thread.start()
    classify_msg = " + clasificacion de documentos" if req.classify_docs else ""
    skip_msg = f" — {len(skipped)} omitidas por inconsistencias (depurar primero)" if skipped else ""
    return {"status": "started", "message": f"Extraccion de {len(case_ids)} casos iniciada ({MAX_WORKERS} en paralelo{classify_msg}){skip_msg}", "skipped": skipped}



@router.post("/agent/{case_id}")
def api_agent_extract(case_id: int, classify: bool = False, force: bool = False, db: Session = Depends(get_db)):
    """(Modernización Fase 7.3) Alias de "Extraer un caso" sobre el pipeline v9.

    El antiguo "Agente IA v3" (multi-modelo, multi-paso) ya no se usa — generaba ruido.
    Este endpoint ahora corre `backend.v9.pipeline.extract_case`, igual que `/single/{id}`;
    `persist.py` solo rellena campos vacíos (no pisa el cuadro). El query param `classify`
    se ignora (v9 clasifica los docs en la ingesta vía `doc_librarian`).
    """
    from fastapi import HTTPException
    from backend.database.models import AuditLog
    from backend.v9.pipeline import extract_case
    import time

    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Caso no encontrado")

    _guard_folder_consistency(db, case_id, force)

    start = time.time()
    _llm_lifecycle = False
    try:
        from backend.services.llm_mutex import begin_extraction
        begin_extraction()
        _llm_lifecycle = True
        result = extract_case(db, case_id, dry_run=False, use_llm=True)
        elapsed = int(time.time() - start)
        try:
            case.processing_status = "COMPLETO"
            db.commit()
        except Exception:
            db.rollback()
        db.refresh(case)
        fields_data = _get_fields_data(case)

        try:
            db.add(AuditLog(
                case_id=case_id, action="EXTRACTION_V9",
                new_value=f"{len(fields_data)} campos | {elapsed}s | completitud {result.fields.completitud()}%",
            ))
            db.commit()
        except Exception:
            db.rollback()

        return {
            "status": "completed",
            "case_id": case_id,
            "folder_name": case.folder_name,
            "processing_status": case.processing_status,
            "fields_extracted": len(fields_data),
            "fields": fields_data,
            "completitud_v9": result.fields.completitud(),
            "documents_processed": result.docs_processed,
            "warnings": result.warnings,
            "elapsed_seconds": elapsed,
            "tokens": _get_token_usage(db, case_id),
            "method": "v9.pipeline",
        }
    except Exception as e:
        db.rollback()
        return {
            "status": "error",
            "case_id": case_id,
            "message": str(e),
        }
    finally:
        if _llm_lifecycle:
            from backend.services.llm_mutex import end_extraction
            end_extraction()


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
    from backend.extraction.doc_ops import verify_all_documents
    stats = verify_all_documents(db)
    return stats


@router.post("/audit")
def api_full_audit(db: Session = Depends(get_db)):
    """Auditoría molecular completa: disco, DB, documentos, nombres, emails."""
    from pathlib import Path
    from backend.config import BASE_DIR
    from backend.database.models import Document, Email
    from backend.extraction.doc_ops import verify_all_documents
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
    from backend.extraction.doc_ops import classify_doc_type

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
    from backend.extraction.doc_ops import detect_duplicate_documents
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

    now = utcnow()
    since_dt = _parse_iso(since, now - timedelta(hours=24))
    until_dt = _parse_iso(until, now)

    return compute_period_metrics(
        db=db,
        since=since_dt,
        until=until_dt,
        provider=provider,
        version_tag=version_tag,
    )
