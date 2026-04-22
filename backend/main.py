"""FastAPI - Plataforma de Gestion Juridica de Tutelas."""

import sys
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Asegurar que el directorio padre este en el path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database.database import init_db, get_db, SessionLocal
from backend.database.seed import run_seed
from backend.routers import cases, documents, extraction, dashboard, reports, emails, seguimiento
from backend.email.gmail_monitor import check_inbox, get_gmail_total, sync_inbox
from backend.extraction.pipeline import process_folder
from backend.database.models import Case, Email

# Logging estructurado
from backend.core.logging import setup_logging, get_logger
setup_logging(log_dir=str(Path(__file__).resolve().parent.parent / "logs"))
logger = get_logger("main")

# ============================================================
# Estado global del monitor de Gmail y extraccion
# ============================================================
gmail_monitor_enabled = False  # Desactivado por defecto — activar desde Dashboard
GMAIL_CHECK_INTERVAL = 20 * 60  # 20 minutos en segundos
last_gmail_check = None
gmail_monitor_log: list[dict] = []  # Ultimas 50 entradas del log

extraction_in_progress = False
extraction_progress = {"current": 0, "total": 0, "case_name": "", "results": [], "progress_pct": 0}


import threading
_monitor_log_lock = threading.Lock()


def add_monitor_log(message: str, level: str = "info", details: dict | None = None):
    """Agregar entrada al log del monitor (thread-safe)."""
    global gmail_monitor_log
    entry = {
        "timestamp": datetime.now().isoformat(),
        "message": message,
        "level": level,
        "details": details or {},
    }
    with _monitor_log_lock:
        gmail_monitor_log.append(entry)
        if len(gmail_monitor_log) > 50:
            gmail_monitor_log = gmail_monitor_log[-50:]
    if level == "error":
        logger.error(message)
    else:
        logger.info(message)


async def gmail_background_check():
    """Tarea en background: revisa Gmail cada 20 minutos.
    Espera 60 segundos antes del primer chequeo para que la app arranque."""
    global last_gmail_check, gmail_monitor_enabled

    add_monitor_log("Monitor de Gmail iniciado (cada 20 minutos). Primer chequeo en 60 segundos.")

    # Esperar 60 segundos antes del primer chequeo
    await asyncio.sleep(60)

    while True:
        if gmail_monitor_enabled and not gmail_check_in_progress:
            try:
                add_monitor_log("Revisando bandeja de Gmail...")
                db = SessionLocal()
                try:
                    results = check_inbox(db)
                    new_emails = [r for r in results if "error" not in r]
                    errors = [r for r in results if "error" in r]

                    last_gmail_check = datetime.now().isoformat()

                    if errors:
                        add_monitor_log(
                            f"Errores al revisar Gmail: {errors[0].get('error', '')}",
                            level="error",
                            details={"errors": errors},
                        )
                    elif new_emails:
                        add_monitor_log(
                            f"Encontrados {len(new_emails)} emails nuevos",
                            details={"emails": new_emails},
                        )

                        # Extraccion con contexto completo: re-analizar toda la carpeta
                        # para que la IA tenga contexto de TODOS los documentos + emails
                        cases_processed = set()
                        total_fields = 0
                        for email_info in new_emails:
                            if not email_info.get("matched_case"):
                                continue
                            case = db.query(Case).filter(
                                Case.folder_name == email_info["matched_case"]
                            ).first()
                            if not case or case.id in cases_processed:
                                continue

                            cases_processed.add(case.id)
                            try:
                                stats = process_folder(db, case)
                                fields = stats.get("ai_fields_extracted", 0)
                                total_fields += fields
                                add_monitor_log(
                                    f"Caso '{case.folder_name}': {fields} campos extraidos ({stats.get('documents_extracted', 0)} docs + emails analizados)",
                                )
                            except Exception as e:
                                add_monitor_log(
                                    f"Error procesando {case.folder_name}: {e}",
                                    level="error",
                                )

                        add_monitor_log(
                            f"Procesados {len(new_emails)} emails -> {len(cases_processed)} casos analizados, {total_fields} campos actualizados",
                        )
                    else:
                        add_monitor_log("No hay emails nuevos")

                finally:
                    db.close()

            except Exception as e:
                add_monitor_log(f"Error en monitor de Gmail: {e}", level="error")

        await asyncio.sleep(GMAIL_CHECK_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializar DB y lanzar monitor de Gmail al arrancar."""
    init_db()

    # Verificar si la DB esta vacia y hacer seed
    db = SessionLocal()
    if db.query(Case).count() == 0:
        db.close()
        run_seed()
    else:
        db.close()

    # Monitor de Gmail desactivado — todo es manual
    add_monitor_log("Aplicacion iniciada - Gmail en modo manual")

    # Scheduler de backup diario (6:00 AM)
    import threading
    from backend.services.backup_service import create_backup

    def _daily_backup_scheduler():
        """Thread daemon que ejecuta backup diario a las 6 AM."""
        import time as _time
        while True:
            now = datetime.now()
            # Calcular segundos hasta las 6:00 AM del dia siguiente
            target = now.replace(hour=6, minute=0, second=0, microsecond=0)
            if now >= target:
                target = target.replace(day=target.day + 1)
            wait_seconds = (target - now).total_seconds()
            _time.sleep(wait_seconds)
            try:
                result = create_backup(reason="scheduled")
                add_monitor_log(f"Backup diario: {result.get('filename', result.get('error', '?'))}")
            except Exception as e:
                add_monitor_log(f"Error en backup diario: {e}", level="error")

    backup_thread = threading.Thread(target=_daily_backup_scheduler, daemon=True, name="daily-backup")
    backup_thread.start()
    add_monitor_log("Scheduler de backup diario activado (6:00 AM)")

    # v5.1 Sprint 1: scheduler de WAL checkpoint cada 5 min.
    # Evita que el archivo .db-wal crezca indefinidamente y garantiza
    # que scripts CLI (que leen el .db principal) vean los datos mas recientes.
    def _wal_checkpoint_scheduler():
        import time as _time
        from backend.database.database import wal_checkpoint
        while True:
            _time.sleep(300)  # 5 minutos
            try:
                r = wal_checkpoint("PASSIVE")
                if r.get("log_pages", 0) > 500:
                    add_monitor_log(f"WAL checkpoint: {r['checkpointed']}/{r['log_pages']} pages")
            except Exception as e:
                add_monitor_log(f"Error WAL checkpoint: {e}", level="warning")

    wal_thread = threading.Thread(target=_wal_checkpoint_scheduler, daemon=True, name="wal-checkpoint")
    wal_thread.start()
    add_monitor_log("Scheduler de WAL checkpoint activado (cada 5 min)")

    # v5.3.3: Active learning nocturno (3:00 AM)
    try:
        from backend.services.active_learning_scheduler import run_scheduler_thread as _al_thread
        al_thread = threading.Thread(target=_al_thread, daemon=True, name="active-learning")
        al_thread.start()
        add_monitor_log("Active learning scheduler activado (cron 3:00 AM)")
    except Exception as e:
        add_monitor_log(f"Active learning no activado: {e}", level="warning")

    # v5.4.2: precargar Presidio analyzer en background.
    # Evita el KeyError('spacy') del primer caso en batch — la caché lru_cache
    # no se construye hasta la primera llamada, y bajo carga concurrente el
    # modelo spaCy no termina de cargar antes de que llegue la primera redacción.
    def _warmup_presidio():
        try:
            from backend.privacy.detectors import _get_analyzer
            _get_analyzer()
            add_monitor_log("Presidio analyzer precargado")
        except Exception as e:
            add_monitor_log(f"Presidio warmup fallo: {e}", level="warning")

    warmup_thread = threading.Thread(target=_warmup_presidio, daemon=True, name="presidio-warmup")
    warmup_thread.start()

    # v5.4.4: construir CaseLookupCache al startup (KB en memoria del monitor Gmail)
    def _build_case_cache():
        try:
            from backend.email.case_lookup_cache import get_cache
            _db = SessionLocal()
            try:
                stats = get_cache().build(_db)
                add_monitor_log(f"CaseLookupCache built: {stats['cases_indexed']} casos indexados")
            finally:
                _db.close()
        except Exception as e:
            add_monitor_log(f"CaseLookupCache build fallo: {e}", level="warning")

    cache_thread = threading.Thread(target=_build_case_cache, daemon=True, name="case-cache-build")
    cache_thread.start()

    yield

    # Cleanup
    add_monitor_log("Aplicacion detenida")


app = FastAPI(
    title="Tutelas Manager",
    description="Plataforma de Gestion Juridica de Tutelas - Gobernacion de Santander",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS para el frontend React (localhost:5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware
from backend.core.middleware import RequestIDMiddleware, global_exception_handler
app.add_middleware(RequestIDMiddleware)
app.add_exception_handler(Exception, global_exception_handler)

# Routers
from backend.auth.router import router as auth_router
app.include_router(auth_router)
app.include_router(cases.router)
app.include_router(documents.router)
app.include_router(extraction.router)
app.include_router(dashboard.router)
app.include_router(reports.router)
app.include_router(emails.router)
app.include_router(seguimiento.router)
from backend.routers.knowledge import router as knowledge_router
app.include_router(knowledge_router)
from backend.alerts.router import router as alerts_router
app.include_router(alerts_router)
from backend.routers.intelligence import router as intelligence_router
app.include_router(intelligence_router)
from backend.routers.agent import router as agent_router
app.include_router(agent_router)
from backend.routers.cleanup import router as cleanup_router
app.include_router(cleanup_router)


# ============================================================
# Endpoints de salud y monitor
# ============================================================

@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "Tutelas Manager v1.0"}


@app.get("/api/health/normalizer")
def normalizer_status():
    """Estado de los componentes del normalizador de documentos."""
    try:
        from backend.extraction.document_normalizer import check_normalizer_status
        return check_normalizer_status()
    except ImportError:
        return {"normalizer_enabled": False, "error": "document_normalizer no disponible"}


# Estado global de revision de Gmail manual
gmail_check_in_progress = False
gmail_check_result = {}


def _run_gmail_check_background():
    """Ejecutar revision de Gmail en background (thread)."""
    global gmail_check_in_progress, gmail_check_result, last_gmail_check
    import time as _time
    from backend.services.backup_service import auto_backup

    _start = _time.time()

    def _update_pct():
        """Recalcular progress_pct y elapsed_seconds."""
        total = gmail_check_result.get("total", 0)
        current = gmail_check_result.get("current", 0)
        gmail_check_result["progress_pct"] = round((current / total) * 100) if total > 0 else 0
        gmail_check_result["elapsed_seconds"] = round(_time.time() - _start)

    try:
        # Backup automatico antes de revision Gmail
        auto_backup("pre_gmail")

        db = SessionLocal()
        add_monitor_log("Revision manual de Gmail iniciada...")

        # Paso 1: Conectar a Gmail y descargar emails
        gmail_check_result = {
            "step": "Paso 1/3: Conectando a Gmail...",
            "current": 0, "total": 3,
            "emails_found": 0, "cases_processed": 0, "total_fields": 0,
            "progress_pct": 0, "elapsed_seconds": 0,
        }

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(check_inbox, db)
            try:
                results = future.result(timeout=600)
            except concurrent.futures.TimeoutError:
                gmail_check_result["step"] = "Error: Gmail no responde (timeout 10min). Intente mas tarde."
                gmail_check_result["error"] = "timeout"
                _update_pct()
                add_monitor_log("Gmail timeout: no responde en 10min", level="error")
                return

        gmail_check_result["current"] = 1
        _update_pct()
        last_gmail_check = datetime.now().isoformat()

        new_emails = [r for r in results if "error" not in r]
        errors = [r for r in results if "error" in r]
        gmail_check_result["emails_found"] = len(new_emails)
        gmail_check_result["step"] = f"Paso 1/3: {len(new_emails)} emails descargados"

        if errors:
            err_msg = errors[0].get("error", "desconocido")
            add_monitor_log(f"Gmail: {len(errors)} error(es) parciales: {err_msg}", level="warning")
            # No retornar — continuar con los emails exitosos si los hay

        if not new_emails:
            gmail_check_result["current"] = 3
            gmail_check_result["total"] = 3
            gmail_check_result["step"] = "Completado: No hay emails nuevos"
            _update_pct()
            add_monitor_log("No hay emails nuevos")
            return

        # Paso 2: Clasificar emails y asociar a casos
        gmail_check_result["step"] = f"Paso 2/3: Clasificando {len(new_emails)} emails..."
        gmail_check_result["current"] = 2
        _update_pct()

        # Paso 3: Extraccion con contexto completo
        cases_to_process = []
        cases_seen = set()
        for email_info in new_emails:
            if not email_info.get("matched_case"):
                continue
            case = db.query(Case).filter(
                Case.folder_name == email_info["matched_case"]
            ).first()
            if case and case.id not in cases_seen:
                cases_seen.add(case.id)
                cases_to_process.append(case)

        total_fields = 0
        cases_processed = 0
        # Expandir total: 2 pasos base + N casos
        gmail_check_result["total"] = 2 + len(cases_to_process)

        for i, case in enumerate(cases_to_process):
            gmail_check_result["current"] = 2 + i
            gmail_check_result["step"] = f"Paso 3/3: Analizando ({i+1}/{len(cases_to_process)}): {case.folder_name[:40]}..."
            _update_pct()

            try:
                stats = process_folder(db, case)
                fields = stats.get("ai_fields_extracted", 0)
                total_fields += fields
                cases_processed += 1
            except Exception as e:
                add_monitor_log(f"Error procesando {case.folder_name}: {e}", level="error")

        gmail_check_result["current"] = gmail_check_result["total"]
        gmail_check_result["cases_processed"] = cases_processed
        gmail_check_result["total_fields"] = total_fields
        gmail_check_result["step"] = f"Completado: {len(new_emails)} emails, {cases_processed} casos, {total_fields} campos"
        _update_pct()

        add_monitor_log(
            f"Revision manual: {len(new_emails)} emails, {cases_processed} casos, {total_fields} campos actualizados",
        )

    except Exception as e:
        gmail_check_result["step"] = f"Error: {str(e)[:100]}"
        gmail_check_result["error"] = str(e)
        _update_pct()
        add_monitor_log(f"Error en revision manual: {e}", level="error")
    finally:
        gmail_check_in_progress = False
        try:
            db.close()
        except Exception:
            pass


@app.get("/api/emails/gmail-stats")
def api_gmail_stats():
    """Total real de correos en Gmail vs importados en DB."""
    db = SessionLocal()
    try:
        gmail = get_gmail_total()
        db_total = db.query(Email).count()
        db_asignados = db.query(Email).filter(Email.status == "ASIGNADO").count()
        db_pendientes = db.query(Email).filter(Email.status == "PENDIENTE").count()
        return {
            "gmail_total": gmail.get("total", 0),
            "gmail_unread": gmail.get("unread", 0),
            "db_total": db_total,
            "db_asignados": db_asignados,
            "db_pendientes": db_pendientes,
            "faltan": max(0, gmail.get("total", 0) - db_total),
            "error": gmail.get("error"),
        }
    finally:
        db.close()


@app.post("/api/emails/sync")
def api_sync_emails():
    """Sincronizar correos faltantes (leidos + no leidos) desde Gmail."""
    global gmail_check_in_progress, gmail_check_result
    import threading

    if gmail_check_in_progress:
        return {"status": "running", "message": "Ya hay una sincronizacion en progreso."}

    def _run_sync():
        global gmail_check_in_progress, gmail_check_result
        try:
            db = SessionLocal()
            gmail_check_result = {"step": "Sincronizando correos (solo registro, sin crear carpetas)...", "emails_found": 0}
            results = sync_inbox(db)
            imported = results[0].get("imported", 0) if results else 0
            gmail_check_result["emails_found"] = imported
            gmail_check_result["step"] = f"Sync completado: {imported} correos importados"
            add_monitor_log(f"Sync completo: {imported} emails importados")
        except Exception as e:
            gmail_check_result["step"] = f"Error: {e}"
            gmail_check_result["error"] = str(e)
        finally:
            gmail_check_in_progress = False
            try:
                db.close()
            except Exception:
                pass

    gmail_check_in_progress = True
    gmail_check_result = {"step": "Iniciando sync...", "emails_found": 0}
    threading.Thread(target=_run_sync, daemon=True).start()
    return {"status": "started", "message": "Sincronizacion iniciada (todos los correos)"}


@app.post("/api/emails/check")
def api_check_emails_manual():
    """Lanzar revision de Gmail en background. Solo permite UNA revision a la vez."""
    global gmail_check_in_progress, gmail_check_result
    import threading

    if gmail_check_in_progress:
        return {"status": "running", "message": "Ya hay una revision en progreso. Espere a que termine.", "progress": gmail_check_result}

    gmail_check_in_progress = True
    gmail_check_result = {"step": "Iniciando...", "emails_found": 0, "cases_processed": 0, "progress_pct": 0, "elapsed_seconds": 0}

    thread = threading.Thread(target=_run_gmail_check_background, daemon=True)
    thread.start()

    return {"status": "started", "message": "Revision iniciada en background"}


@app.get("/api/emails/check-status")
def api_check_emails_status():
    """Consultar estado de la revision de Gmail en curso."""
    return {
        "in_progress": gmail_check_in_progress,
        **gmail_check_result,
    }


@app.post("/api/emails/check-cancel")
def api_cancel_gmail_check():
    """Cancelar revision de Gmail en curso."""
    global gmail_check_in_progress
    if gmail_check_in_progress:
        gmail_check_in_progress = False
        gmail_check_result["step"] = "Cancelado por usuario"
        add_monitor_log("Revision de Gmail cancelada por usuario")
        return {"message": "Cancelado"}
    return {"message": "No hay revision en curso"}


@app.post("/api/emails/register-md")
def api_register_email_md():
    """Registrar Email_*.md existentes en disco como Documents (retroactivo)."""
    import os
    from backend.database.models import Document
    from backend.config import BASE_DIR

    db = SessionLocal()
    registered = 0
    skipped = 0
    try:
        for case in db.query(Case).filter(Case.folder_path.isnot(None)).all():
            folder = case.folder_path
            if not os.path.isdir(folder):
                continue
            for fname in os.listdir(folder):
                if not fname.startswith("Email_") or not fname.endswith(".md"):
                    continue
                # Verificar si ya está registrado
                existing = db.query(Document).filter(
                    Document.case_id == case.id,
                    Document.filename == fname,
                ).first()
                if existing:
                    skipped += 1
                    continue
                fpath = os.path.join(folder, fname)
                try:
                    content = open(fpath, "r", encoding="utf-8", errors="replace").read()
                except Exception:
                    content = ""
                doc = Document(
                    case_id=case.id,
                    filename=fname,
                    file_path=fpath,
                    doc_type="EMAIL_MD",
                    extracted_text=content,
                    extraction_method="email_md",
                    extraction_date=datetime.utcnow(),
                    verificacion="OK",
                    verificacion_detalle="Email del caso (registrado retroactivamente)",
                    file_size=os.path.getsize(fpath) if os.path.exists(fpath) else 0,
                )
                db.add(doc)
                registered += 1
            if registered % 50 == 0 and registered > 0:
                db.commit()
        db.commit()
    finally:
        db.close()
    return {"registered": registered, "skipped": skipped, "message": f"{registered} archivos Email .md registrados como Documents"}


@app.get("/api/monitor/status")
def api_monitor_status():
    """Estado del monitor automatico de Gmail."""
    return {
        "enabled": gmail_monitor_enabled,
        "interval_minutes": GMAIL_CHECK_INTERVAL // 60,
        "last_check": last_gmail_check,
        "log": gmail_monitor_log[-20:],  # Ultimas 20 entradas
    }


@app.post("/api/monitor/toggle")
def api_toggle_monitor():
    """Activar/desactivar el monitor automatico."""
    global gmail_monitor_enabled
    gmail_monitor_enabled = not gmail_monitor_enabled
    status = "activado" if gmail_monitor_enabled else "desactivado"
    add_monitor_log(f"Monitor de Gmail {status} por el usuario")
    return {"enabled": gmail_monitor_enabled, "message": f"Monitor {status}"}


# Estado global de sincronizacion
sync_in_progress = False
sync_result = {}


@app.get("/api/sync/status")
def api_sync_status():
    """Estado de la sincronizacion."""
    return {"in_progress": sync_in_progress, **sync_result}


def _run_sync_background(force: bool = False):
    """Ejecutar sincronizacion en background usando sync_service optimizado."""
    global sync_in_progress, sync_result
    import time as _time
    from pathlib import Path
    from backend.config import BASE_DIR
    from backend.services.sync_service import run_sync

    _start = _time.time()

    try:
        db = SessionLocal()
        sync_result = {
            "step": "Iniciando...", "current": 0, "total": 7,
            "docs_added": 0, "cases_fixed": 0, "paths_fixed": 0,
            "new_cases": 0, "docs_verified": 0, "docs_moved": 0,
            "docs_suspicious": 0, "progress_pct": 0, "docs_total": 0,
            "elapsed_seconds": 0,
        }

        # Thread para actualizar elapsed_seconds cada segundo
        import threading
        _elapsed_stop = threading.Event()
        def _update_elapsed():
            while not _elapsed_stop.is_set():
                sync_result["elapsed_seconds"] = round(_time.time() - _start)
                _elapsed_stop.wait(1)
        elapsed_thread = threading.Thread(target=_update_elapsed, daemon=True)
        elapsed_thread.start()

        run_sync(
            db=db,
            base_dir=BASE_DIR,
            result=sync_result,
            is_running_fn=lambda: sync_in_progress,
            force=force,
        )

        _elapsed_stop.set()
        sync_result["elapsed_seconds"] = round(_time.time() - _start)
        add_monitor_log(sync_result.get("step", "Sync completa"))
    except Exception as e:
        sync_result["step"] = f"Error: {str(e)[:80]}"
    finally:
        sync_in_progress = False
        _elapsed_stop.set()
        try:
            db.close()
        except Exception:
            pass


def _run_sync_background_LEGACY():
    """[DEPRECATED] Sync anterior — mantener para rollback.
    Usar _run_sync_background() con sync_service.py."""
    global sync_in_progress, sync_result
    from pathlib import Path
    from backend.config import BASE_DIR
    from backend.database.models import Document
    from backend.database.seed import classify_document, is_case_folder
    from backend.services.backup_service import auto_backup

    try:
        auto_backup("pre_sync")

        db = SessionLocal()
        sync_result = {"step": "Escaneando carpetas...", "current": 0, "total": 7, "docs_added": 0, "cases_fixed": 0, "paths_fixed": 0, "new_cases": 0, "docs_verified": 0, "docs_moved": 0, "docs_suspicious": 0}
        VALID_EXT = {".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg", ".md"}

        # Fase 1/7: Registrar documentos faltantes
        sync_result["step"] = "Paso 1/7: Escaneando documentos..."
        cases = db.query(Case).filter(Case.folder_path.isnot(None)).all()
        for i, case in enumerate(cases):
            if not case.folder_path or not Path(case.folder_path).exists():
                continue
            sync_result["case_name"] = case.folder_name or ""
            existing = {d.filename for d in case.documents}
            for f in sorted(Path(case.folder_path).iterdir()):
                if not f.is_file() or f.suffix.lower() not in VALID_EXT or f.name in existing:
                    continue
                db.add(Document(case_id=case.id, filename=f.name, file_path=str(f),
                                doc_type=classify_document(f.name), file_size=f.stat().st_size))
                sync_result["docs_added"] += 1
            if sync_result["docs_added"] > 0:
                sync_result["cases_fixed"] += 1
        sync_result["current"] = 1

        # Fase 2/7: Verificacion inteligente y reasignacion de documentos
        sync_result["step"] = "Paso 2/7: Verificando pertenencia de documentos..."
        from backend.extraction.pipeline import verify_document_belongs, extract_document_text
        reassign_stats = {}

        all_cases = db.query(Case).filter(Case.folder_path.isnot(None)).all()
        for case in all_cases:
            if not case.folder_path or not Path(case.folder_path).exists():
                continue
            if not case.documents:
                continue

            sync_result["case_name"] = case.folder_name or ""

            for doc in list(case.documents):
                if doc.verificacion in ("OK", "REASIGNADO"):
                    continue
                if not doc.extracted_text and doc.file_path and Path(doc.file_path).exists():
                    try:
                        text, method = extract_document_text(doc)
                        if text and len(text.strip()) >= 50:
                            doc.extracted_text = text
                            doc.extraction_method = method
                    except Exception:
                        pass
                if not doc.extracted_text or len(doc.extracted_text or "") < 100:
                    continue

                status, detalle = verify_document_belongs(case, doc)
                doc.verificacion = status
                doc.verificacion_detalle = detalle
                sync_result["docs_verified"] += 1

                if status == "NO_PERTENECE":
                    sync_result["docs_moved"] += 1
                    from backend.database.models import AuditLog
                    db.add(AuditLog(
                        case_id=case.id,
                        field_name="DOC_NO_PERTENECE",
                        old_value=doc.filename,
                        new_value=detalle[:200],
                        action="SYNC_VERIFY",
                        source="sync_fase2",
                    ))
                elif status == "SOSPECHOSO":
                    sync_result["docs_suspicious"] += 1

            try:
                db.commit()
            except Exception:
                db.rollback()

        sync_result["current"] = 2

        # Fase 3/7: Corregir paths rotos
        sync_result["step"] = "Paso 3/7: Corrigiendo paths..."
        all_docs = db.query(Document).all()
        for doc in all_docs:
            if doc.file_path and not Path(doc.file_path).exists():
                case = db.query(Case).filter(Case.id == doc.case_id).first()
                if case and case.folder_path:
                    new_path = Path(case.folder_path) / doc.filename
                    if new_path.exists():
                        doc.file_path = str(new_path)
                        sync_result["paths_fixed"] += 1
        sync_result["current"] = 3

        # Fase 3/3: Buscar carpetas nuevas
        sync_result["step"] = "Paso 4/7: Buscando carpetas nuevas..."
        for entry in sorted(BASE_DIR.iterdir()):
            if not entry.is_dir() or not is_case_folder(entry.name):
                continue
            if not db.query(Case).filter(Case.folder_name == entry.name).first():
                new_case = Case(folder_name=entry.name, folder_path=str(entry), processing_status="PENDIENTE")
                db.add(new_case)
                db.flush()
                for f in sorted(entry.iterdir()):
                    if f.is_file() and f.suffix.lower() in VALID_EXT:
                        db.add(Document(case_id=new_case.id, filename=f.name, file_path=str(f),
                                        doc_type=classify_document(f.name), file_size=f.stat().st_size))
                        sync_result["docs_added"] += 1
                sync_result["new_cases"] += 1
        sync_result["current"] = 4

        # Fase 4/6: Eliminar documentos fantasma (archivo no existe en disco)
        sync_result["step"] = "Paso 5/7: Limpiando documentos fantasma..."
        docs_removed = 0
        all_docs = db.query(Document).all()
        for doc in all_docs:
            if doc.file_path and not Path(doc.file_path).exists():
                db.delete(doc)
                docs_removed += 1
        sync_result["current"] = 5

        # Fase 6/7: Eliminar casos huerfanos (carpeta eliminada del disco)
        sync_result["step"] = "Paso 6/7: Limpiando casos sin carpeta..."
        cases_removed = 0
        from backend.database.models import Email, Extraction, AuditLog as AL, TokenUsage, ComplianceTracking
        all_cases = db.query(Case).filter(Case.folder_path.isnot(None)).all()
        for case in all_cases:
            if case.folder_path and not Path(case.folder_path).exists():
                # Carpeta eliminada del disco — eliminar caso y todas sus relaciones
                db.query(Document).filter(Document.case_id == case.id).delete()
                db.query(Extraction).filter(Extraction.case_id == case.id).delete()
                db.query(AL).filter(AL.case_id == case.id).delete()
                db.query(ComplianceTracking).filter(ComplianceTracking.case_id == case.id).delete()
                db.query(TokenUsage).filter(TokenUsage.case_id == case.id).delete()
                db.query(Email).filter(Email.case_id == case.id).update({"case_id": None, "status": "PENDIENTE"})
                db.delete(case)
                cases_removed += 1
        sync_result["cases_removed"] = cases_removed
        sync_result["current"] = 6

        # Fase 7/7: Renombrar carpetas [PENDIENTE REVISION] si ya tienen accionante
        sync_result["step"] = "Paso 7/7: Renombrando carpetas pendientes..."
        import re
        folders_renamed = 0
        cases_pendiente = db.query(Case).filter(Case.folder_name.contains("[PENDIENTE")).all()
        for case in cases_pendiente:
            if not case.accionante or not case.folder_path or not Path(case.folder_path).exists():
                continue
            # Extraer radicado
            m = re.match(r"(20\d{2}[-\s]?\d+)", case.folder_name or "")
            if not m:
                continue
            rad = m.group(1).strip()
            rm = re.match(r"(20\d{2})[-\s]?0*(\d+)", rad)
            if rm:
                rad = f"{rm.group(1)}-{rm.group(2).zfill(5)}"
            acc = re.sub(r'[\n\r]', ' ', case.accionante).strip()
            acc = re.sub(r'\s+', ' ', acc)
            new_name = f"{rad} {acc}"
            new_name = re.sub(r'[<>:"/\\|?*]', '', new_name).strip()
            new_path = BASE_DIR / new_name
            if new_path.exists() or new_name == case.folder_name:
                continue
            try:
                Path(case.folder_path).rename(new_path)
                old_path = case.folder_path
                case.folder_name = new_name
                case.folder_path = str(new_path)
                for doc in case.documents:
                    if doc.file_path and old_path in doc.file_path:
                        doc.file_path = doc.file_path.replace(old_path, str(new_path))
                folders_renamed += 1
            except Exception:
                pass
        sync_result["current"] = 7

        db.commit()
        parts = []
        if sync_result['docs_added'] > 0: parts.append(f"+{sync_result['docs_added']} docs")
        if sync_result['new_cases'] > 0: parts.append(f"+{sync_result['new_cases']} nuevos")
        if cases_removed > 0: parts.append(f"-{cases_removed} casos eliminados")
        if docs_removed > 0: parts.append(f"-{docs_removed} docs fantasma")
        if folders_renamed > 0: parts.append(f"{folders_renamed} renombradas")
        if sync_result.get('docs_moved', 0) > 0: parts.append(f"{sync_result['docs_moved']} reasignados")
        if sync_result.get('docs_suspicious', 0) > 0: parts.append(f"{sync_result['docs_suspicious']} sospechosos")
        sync_result["step"] = f"Listo: {', '.join(parts)}" if parts else "Listo: sin cambios"
        add_monitor_log(sync_result["step"])
    except Exception as e:
        sync_result["step"] = f"Error: {str(e)[:80]}"
    finally:
        sync_in_progress = False
        try:
            db.close()
        except Exception:
            pass


@app.post("/api/sync")
def api_sync_folders(force: bool = False):
    """Lanzar sincronizacion en background. force=true ignora fingerprint."""
    global sync_in_progress, sync_result
    import threading

    if sync_in_progress:
        return {"status": "running", "message": "Sincronizacion en progreso"}

    sync_in_progress = True
    sync_result = {"step": "Iniciando...", "docs_added": 0, "cases_fixed": 0, "paths_fixed": 0, "new_cases": 0, "progress_pct": 0}
    threading.Thread(target=_run_sync_background, args=(force,), daemon=True).start()
    return {"status": "started", "message": "Sincronizacion iniciada"}


@app.post("/api/sync/cancel")
def api_sync_cancel():
    """Cancelar sincronizacion en progreso."""
    global sync_in_progress
    if sync_in_progress:
        sync_in_progress = False
        return {"status": "cancelling", "message": "Cancelando sincronizacion..."}
    return {"status": "not_running", "message": "No hay sincronizacion en progreso"}


@app.get("/api/settings/status")
def api_settings_status():
    """Estado de la configuracion."""
    import os
    from backend.config import GMAIL_USER, GMAIL_APP_PASSWORD, DB_PATH, BASE_DIR

    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
    gmail_ok = bool(GMAIL_USER and GMAIL_APP_PASSWORD)
    deepseek_ok = bool(deepseek_key)
    db_ok = DB_PATH.exists()
    folders_ok = BASE_DIR.exists()

    # Contar casos y documentos
    cases_count = 0
    documents_count = 0
    try:
        db = SessionLocal()
        cases_count = db.query(Case).count()
        from backend.database.models import Document
        documents_count = db.query(Document).count()
        db.close()
    except Exception:
        pass

    return {
        # Campos que el frontend espera para los 4 servicios
        "gmail": gmail_ok,
        "deepseek": deepseek_ok,
        "database": db_ok,
        "folders": folders_ok,
        # Detalles extra
        "gmail_detail": f"Usuario: {GMAIL_USER}" if gmail_ok else "No configurado en .env",
        "deepseek_detail": f"Key: {deepseek_key[:12]}..." if deepseek_ok else "No configurado en .env",
        "database_detail": f"SQLite: {DB_PATH}",
        "folders_detail": f"Ruta: {BASE_DIR}",
        # Info adicional
        "gmail_configured": gmail_ok,
        "deepseek_configured": deepseek_ok,
        "monitor_enabled": gmail_monitor_enabled,
        "monitor_interval_minutes": GMAIL_CHECK_INTERVAL // 60,
        "last_gmail_check": last_gmail_check,
        "cases_count": cases_count,
        "documents_count": documents_count,
        # API fallback pagada
        "anthropic_configured": bool(os.getenv("ANTHROPIC_API_KEY", "")),
    }


def _run_extraction_background():
    """Ejecutar extraccion masiva en background thread con pool de 3 workers paralelos."""
    global extraction_in_progress, extraction_progress
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from backend.services.backup_service import auto_backup

    # v5.4: 3 workers paralelos. Conservador por RAM (~93% usada en baseline).
    # DeepSeek soporta bien esa concurrencia y smart_router maneja rate limits 429.
    MAX_WORKERS = 3

    def _process_one_case(case_id: int) -> dict:
        """Worker que procesa 1 caso con su propia sesión DB (thread-safe)."""
        thread_db = SessionLocal()
        case_folder = f"ID {case_id}"
        try:
            case = thread_db.query(Case).filter(Case.id == case_id).first()
            if not case:
                return {"case_id": case_id, "folder": case_folder, "error": "case no encontrado"}
            case_folder = case.folder_name or case_folder
            stats = process_folder(thread_db, case)
            return {"case_id": case_id, "folder": case_folder, "stats": stats}
        except Exception as e:
            try:
                thread_db.rollback()
            except Exception:
                pass
            return {"case_id": case_id, "folder": case_folder, "error": str(e)[:120]}
        finally:
            thread_db.close()

    db = None
    try:
        auto_backup("pre_extraction")

        db = SessionLocal()
        pending = db.query(Case).filter(
            Case.processing_status.in_(["PENDIENTE", "REVISION"]),
            Case.folder_path.isnot(None),
        ).all()
        case_ids = [c.id for c in pending]
        total = len(case_ids)

        extraction_progress["total"] = total
        extraction_progress["success"] = 0
        extraction_progress["errors"] = 0
        extraction_progress["progress_pct"] = 0
        add_monitor_log(f"Extraccion masiva iniciada: {total} casos (pool={MAX_WORKERS})")

        failed_cases = []
        completed = 0

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(_process_one_case, cid): cid for cid in case_ids}
            for fut in as_completed(futures):
                if not extraction_in_progress:
                    add_monitor_log("Extraccion masiva cancelada por usuario")
                    for f in futures:
                        f.cancel()
                    break

                result = fut.result()
                completed += 1
                extraction_progress["current"] = completed
                extraction_progress["case_name"] = result.get("folder") or f"ID {result['case_id']}"
                extraction_progress["phase"] = f"Caso {completed}/{total}: {result.get('folder', '')}"
                extraction_progress["progress_pct"] = int((completed / total) * 100) if total else 0

                err = result.get("error")
                stats = result.get("stats") or {}
                ai_error = stats.get("ai_error")
                if err or ai_error:
                    extraction_progress["errors"] += 1
                    reason = err or str(ai_error)[:120]
                    failed_cases.append({"id": result["case_id"], "folder": result.get("folder", ""), "reason": reason})
                    add_monitor_log(f"Error en {result.get('folder', '')}: {reason}", level="error")
                else:
                    extraction_progress["success"] += 1

        ok = extraction_progress["success"]
        extraction_progress["case_name"] = f"Completado: {ok}/{total} exitosos"
        extraction_progress["phase"] = "Completado"
        extraction_progress["progress_pct"] = 100
        extraction_progress["failed_cases"] = failed_cases
        add_monitor_log(f"Extraccion masiva terminada: {ok}/{total} exitosos")

    except Exception as e:
        add_monitor_log(f"Error en extraccion masiva: {e}", level="error")
    finally:
        extraction_in_progress = False
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


@app.post("/api/extraction/run-all")
def api_run_extraction_all():
    """Lanzar extraccion masiva en background. Retorna inmediatamente."""
    global extraction_in_progress, extraction_progress
    import threading

    if extraction_in_progress:
        return {"status": "running", "message": "Ya hay una extraccion en progreso", "progress": extraction_progress}

    extraction_in_progress = True
    extraction_progress = {"current": 0, "total": 0, "case_name": "Iniciando...", "success": 0, "errors": 0}

    thread = threading.Thread(target=_run_extraction_background, daemon=True)
    thread.start()

    return {"status": "started", "message": "Extraccion masiva iniciada en background"}


@app.post("/api/extraction/stop")
def api_stop_extraction():
    """Detener extraccion masiva en curso."""
    global extraction_in_progress
    if extraction_in_progress:
        extraction_in_progress = False
        add_monitor_log("Extraccion masiva detenida por usuario")
        return {"message": "Extraccion detenida"}
    return {"message": "No hay extraccion en curso"}


@app.get("/api/extraction/progress")
def api_extraction_progress():
    """Consultar progreso de extraccion en curso."""
    return {
        "in_progress": extraction_in_progress,
        **extraction_progress,
    }


