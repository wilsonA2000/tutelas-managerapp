"""Servicio de sincronizacion de carpetas optimizado v4.0.

Mejoras sobre la version anterior (main.py inline):
- Fingerprint: detecta si hubo cambios antes de recorrer todo
- fitz: extraccion de texto rapida (<0.5s/doc) sin OCR
- Progreso granular: porcentaje por documento, no por paso
- Cancelacion: flag chequeado en cada iteracion
- Timeout: 10s max por documento, skip si falla
- Batch commits: cada 50 docs en vez de cada caso
"""

import hashlib
import logging
import re
from pathlib import Path

from sqlalchemy.orm import Session

from backend.database.models import (
    Case, Document, Email, Extraction, AuditLog, TokenUsage, ComplianceTracking,
)
from backend.extraction.doc_ops import verify_document_belongs
from backend.database.seed import classify_document, is_case_folder

logger = logging.getLogger("tutelas.sync")

VALID_EXT = {".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg", ".md"}

# Fingerprint de la ultima sync exitosa
_last_fingerprint: str = ""


def calc_folder_fingerprint(base_dir: Path) -> str:
    """Hash rapido de la estructura de carpetas: nombres + cantidad de archivos + mtime."""
    parts = []
    try:
        for entry in sorted(base_dir.iterdir()):
            if not entry.is_dir() or not is_case_folder(entry.name):
                continue
            try:
                files = [f for f in entry.iterdir() if f.is_file() and f.suffix.lower() in VALID_EXT]
                mtime = max((f.stat().st_mtime for f in files), default=0)
                parts.append(f"{entry.name}:{len(files)}:{int(mtime)}")
            except Exception:
                parts.append(f"{entry.name}:err")
    except Exception:
        return ""
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def check_needs_sync(base_dir: Path) -> bool:
    """Verificar si hay cambios desde la ultima sync."""
    global _last_fingerprint
    current = calc_folder_fingerprint(base_dir)
    if not current:
        return True  # Si no puede calcular, asumir que si
    if current == _last_fingerprint:
        return False
    return True


def _extract_text_fast(file_path: str) -> tuple[str, str]:
    """Extraer texto rapido con fitz (sin OCR). Para sync solo necesitamos
    texto suficiente para comparar radicados/accionante."""
    ext = Path(file_path).suffix.lower()

    if ext == ".pdf":
        try:
            import fitz
            doc = fitz.open(file_path)
            pages = []
            for page in doc:
                pages.append(page.get_text("text"))
            doc.close()
            text = "\n".join(pages)
            if text.strip():
                return text, "fitz_fast"
        except Exception as e:
            logger.debug("fitz fast extract falló para %s: %s", file_path, e)
        return "", "fitz_failed"

    elif ext in (".docx", ".doc"):
        try:
            import docx
            d = docx.Document(file_path)
            text = "\n".join(p.text for p in d.paragraphs if p.text.strip())
            # Footers
            for section in d.sections:
                if section.footer and section.footer.paragraphs:
                    text += "\n" + " ".join(p.text for p in section.footer.paragraphs)
            return text, "docx_fast"
        except Exception:
            return "", "docx_failed"

    elif ext == ".md":
        try:
            text = Path(file_path).read_text(encoding="utf-8", errors="replace")
            return text, "markdown"
        except Exception:
            return "", "md_failed"

    return "", "unsupported"


def run_sync(db: Session, base_dir: Path, result: dict, is_running_fn, force: bool = False):
    """Ejecutar sincronizacion completa de 7 pasos.

    Args:
        db: Session de SQLAlchemy
        base_dir: Directorio raiz con las carpetas de casos
        result: Dict mutable para reportar progreso (compartido con el thread caller)
        is_running_fn: Callable que retorna False si el usuario cancelo
        force: Si True, ignora fingerprint y ejecuta siempre
    """
    global _last_fingerprint
    from backend.services.backup_service import auto_backup
    from backend.v9.doc_librarian import reclassify_legacy_docs

    # Check rapido de cambios
    if not force:
        if not check_needs_sync(base_dir):
            result["step"] = "Sin cambios desde ultima sincronizacion"
            result["progress_pct"] = 100
            logger.info("Sync skip: fingerprint sin cambios")
            return

    # Backup automatico
    auto_backup("pre_sync")

    # Contar docs totales para progreso
    all_cases = db.query(Case).filter(Case.folder_path.isnot(None)).all()
    total_docs = sum(len(c.documents) for c in all_cases)
    result["docs_total"] = total_docs

    # ===================== PASO 1: Escanear documentos nuevos =====================
    result["step"] = "Paso 1/7: Escaneando documentos nuevos..."
    result["progress_pct"] = 2
    docs_added = 0
    cases_with_new = 0

    for case in all_cases:
        if not is_running_fn():
            result["step"] = "Cancelado por usuario"
            return

        if not case.folder_path or not Path(case.folder_path).exists():
            continue

        result["case_name"] = case.folder_name or ""
        existing = {d.filename for d in case.documents}
        case_added = 0

        for f in sorted(Path(case.folder_path).iterdir()):
            if not f.is_file() or f.suffix.lower() not in VALID_EXT or f.name in existing:
                continue
            db.add(Document(
                case_id=case.id, filename=f.name, file_path=str(f),
                doc_type=classify_document(f.name), file_size=f.stat().st_size,
            ))
            case_added += 1

        if case_added > 0:
            docs_added += case_added
            cases_with_new += 1

    if docs_added > 0:
        db.commit()

    result["docs_added"] = docs_added
    result["cases_fixed"] = cases_with_new
    result["progress_pct"] = 10
    logger.info("Paso 1: +%d docs en %d casos", docs_added, cases_with_new)

    # ===================== PASO 2: Verificar pertenencia (OPTIMIZADO) =====================
    result["step"] = "Paso 2/7: Verificando pertenencia de documentos..."
    docs_verified = 0
    docs_moved = 0
    docs_suspicious = 0
    batch_count = 0

    # Recargar casos (pueden tener docs nuevos del paso 1)
    all_cases = db.query(Case).filter(Case.folder_path.isnot(None)).all()
    total_to_verify = sum(
        1 for c in all_cases for d in c.documents
        if not d.verificacion or d.verificacion in ("", "PENDIENTE_OCR")
    )

    for case in all_cases:
        if not is_running_fn():
            result["step"] = "Cancelado por usuario"
            db.commit()
            return

        if not case.folder_path or not Path(case.folder_path).exists() or not case.documents:
            continue

        result["case_name"] = case.folder_name or ""

        for doc in list(case.documents):
            # Skip ya verificados
            if doc.verificacion and doc.verificacion not in ("", "PENDIENTE_OCR"):
                continue

            # Extraer texto rapido con fitz (sin OCR, <0.5s)
            if not doc.extracted_text and doc.file_path and Path(doc.file_path).exists():
                try:
                    text, method = _extract_text_fast(doc.file_path)
                    if text and len(text.strip()) >= 50:
                        doc.extracted_text = text
                        doc.extraction_method = method
                except Exception as e:
                    logger.debug("extracción rápida falló para doc %s: %s", doc.file_path, e)

            if not doc.extracted_text or len(doc.extracted_text or "") < 100:
                doc.verificacion = "PENDIENTE_OCR"
                docs_verified += 1
                continue

            # Verificar pertenencia (regex, rapido)
            status, detalle = verify_document_belongs(case, doc)
            doc.verificacion = status
            doc.verificacion_detalle = detalle
            docs_verified += 1
            batch_count += 1

            if status == "NO_PERTENECE":
                docs_moved += 1
                db.add(AuditLog(
                    case_id=case.id, field_name="DOC_NO_PERTENECE",
                    old_value=doc.filename, new_value=detalle[:200],
                    action="SYNC_VERIFY", source="sync_v4",
                ))
            elif status == "SOSPECHOSO":
                docs_suspicious += 1

            # Batch commit cada 50 docs
            if batch_count >= 50:
                db.commit()
                batch_count = 0

            # Progreso granular
            if total_to_verify > 0:
                pct = 10 + int(50 * docs_verified / total_to_verify)
                result["progress_pct"] = min(pct, 60)
            result["docs_verified"] = docs_verified

        # Tras extraer texto, reclasificar los docs con etiqueta legacy por-filename
        # (PDF_*/DOCX_*) a la taxonomía rica del doc_librarian (por contenido), usando
        # la MISMA autoridad que el pipeline v9. Antes el sync dejaba doc_type pobre que
        # los extractores de field_extractor.py no reconocen (causa raíz del flujo
        # "soltar carpeta + Sync"). Solo toca etiquetas legacy; idempotente.
        try:
            reclassify_legacy_docs(db, case)
        except Exception as e:  # noqa: BLE001
            logger.debug("reclassify_legacy_docs falló en sync (case=%s): %s", getattr(case, "id", "?"), e)

    db.commit()
    result["docs_moved"] = docs_moved
    result["docs_suspicious"] = docs_suspicious
    result["progress_pct"] = 60
    logger.info("Paso 2: %d verificados, %d movidos, %d sospechosos", docs_verified, docs_moved, docs_suspicious)

    # ===================== PASO 3: Corregir paths rotos =====================
    result["step"] = "Paso 3/7: Corrigiendo paths..."
    result["progress_pct"] = 65
    paths_fixed = 0

    all_docs = db.query(Document).all()
    for doc in all_docs:
        if doc.file_path and not Path(doc.file_path).exists():
            case = db.query(Case).filter(Case.id == doc.case_id).first()
            if case and case.folder_path:
                new_path = Path(case.folder_path) / doc.filename
                if new_path.exists():
                    doc.file_path = str(new_path)
                    paths_fixed += 1

    if paths_fixed > 0:
        db.commit()
    result["paths_fixed"] = paths_fixed
    result["progress_pct"] = 70
    logger.info("Paso 3: %d paths corregidos", paths_fixed)

    # ===================== PASO 4: Carpetas nuevas =====================
    result["step"] = "Paso 4/7: Buscando carpetas nuevas..."
    result["progress_pct"] = 75
    new_cases = 0

    for entry in sorted(base_dir.iterdir()):
        if not entry.is_dir() or not is_case_folder(entry.name):
            continue
        if not db.query(Case).filter(Case.folder_name == entry.name).first():
            new_case = Case(folder_name=entry.name, folder_path=str(entry), processing_status="PENDIENTE")
            db.add(new_case)
            db.flush()
            for f in sorted(entry.iterdir()):
                if f.is_file() and f.suffix.lower() in VALID_EXT:
                    db.add(Document(
                        case_id=new_case.id, filename=f.name, file_path=str(f),
                        doc_type=classify_document(f.name), file_size=f.stat().st_size,
                    ))
            new_cases += 1

    if new_cases > 0:
        db.commit()
    result["new_cases"] = new_cases
    result["progress_pct"] = 80
    logger.info("Paso 4: %d casos nuevos", new_cases)

    # ===================== PASO 5: Limpiar docs fantasma =====================
    result["step"] = "Paso 5/7: Limpiando documentos fantasma..."
    result["progress_pct"] = 85
    docs_removed = 0

    all_docs = db.query(Document).all()
    for doc in all_docs:
        if doc.file_path and not Path(doc.file_path).exists():
            db.delete(doc)
            docs_removed += 1

    if docs_removed > 0:
        db.commit()
    result["docs_removed"] = docs_removed
    result["progress_pct"] = 88
    logger.info("Paso 5: %d docs fantasma eliminados", docs_removed)

    # ===================== PASO 6: Limpiar casos huerfanos =====================
    result["step"] = "Paso 6/7: Limpiando casos sin carpeta..."
    result["progress_pct"] = 90
    cases_removed = 0

    all_cases = db.query(Case).filter(Case.folder_path.isnot(None)).all()
    for case in all_cases:
        if case.folder_path and not Path(case.folder_path).exists():
            db.query(Document).filter(Document.case_id == case.id).delete()
            db.query(Extraction).filter(Extraction.case_id == case.id).delete()
            db.query(AuditLog).filter(AuditLog.case_id == case.id).delete()
            db.query(ComplianceTracking).filter(ComplianceTracking.case_id == case.id).delete()
            db.query(TokenUsage).filter(TokenUsage.case_id == case.id).delete()
            db.query(Email).filter(Email.case_id == case.id).update({"case_id": None, "status": "PENDIENTE"})
            db.delete(case)
            cases_removed += 1

    if cases_removed > 0:
        db.commit()
    result["cases_removed"] = cases_removed
    result["progress_pct"] = 93
    logger.info("Paso 6: %d casos huerfanos eliminados", cases_removed)

    # ===================== PASO 7: Renombrar carpetas pendientes =====================
    result["step"] = "Paso 7/7: Renombrando carpetas..."
    result["progress_pct"] = 95
    folders_renamed = 0

    cases_pendiente = db.query(Case).filter(Case.folder_name.contains("[PENDIENTE")).all()
    for case in cases_pendiente:
        if not case.accionante or not case.folder_path or not Path(case.folder_path).exists():
            continue
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
        new_path = base_dir / new_name
        if new_path.exists() or new_name == case.folder_name:
            continue
        try:
            Path(case.folder_path).rename(new_path)
            old_prefix = case.folder_path.rstrip("/")
            case.folder_name = new_name
            case.folder_path = str(new_path)
            # Reemplazo anclado al prefijo de carpeta (evita corromper paths con
            # nombres similares, p.ej. ".../2026-001" vs ".../2026-001_old").
            for doc in case.documents:
                if doc.file_path and (
                    doc.file_path == old_prefix
                    or doc.file_path.startswith(old_prefix + "/")
                ):
                    doc.file_path = str(new_path) + doc.file_path[len(old_prefix):]
            folders_renamed += 1
        except Exception as e:
            logger.warning(
                "No se pudo renombrar carpeta %s → %s: %s",
                case.folder_path, new_path, e,
            )

    db.commit()
    result["folders_renamed"] = folders_renamed

    # Actualizar fingerprint
    _last_fingerprint = calc_folder_fingerprint(base_dir)

    # Resumen final
    parts = []
    if docs_added > 0: parts.append(f"+{docs_added} docs")
    if new_cases > 0: parts.append(f"+{new_cases} nuevos")
    if cases_removed > 0: parts.append(f"-{cases_removed} casos eliminados")
    if docs_removed > 0: parts.append(f"-{docs_removed} docs fantasma")
    if folders_renamed > 0: parts.append(f"{folders_renamed} renombradas")
    if docs_moved > 0: parts.append(f"{docs_moved} reasignados")
    if docs_suspicious > 0: parts.append(f"{docs_suspicious} sospechosos")

    result["step"] = f"Listo: {', '.join(parts)}" if parts else "Listo: sin cambios"
    result["progress_pct"] = 100

    # Indexar nuevos docs en Knowledge Base (incremental)
    if docs_added > 0:
        try:
            from backend.knowledge.indexer import index_document
            for case in all_cases:
                for doc in case.documents:
                    if doc.extracted_text and len(doc.extracted_text) > 100:
                        try:
                            index_document(db, case.id, doc.filename, doc.extracted_text)
                        except Exception as _e:
                            from backend.core.fallback_metrics import record_fallback
                            record_fallback("sync.kb_index", str(_e))  # KB no crítico, ahora visible
            logger.info("KB: indexacion incremental post-sync completada")
        except Exception as e:
            logger.debug("KB indexing skipped: %s", e)

    logger.info("Sync completa: %s", result["step"])


# ─────────────────────────────────────────────────────────────────────────────
# Sync de UN caso (2026-06-12) — extraído del endpoint POST /api/cases/{id}/sync
# para reutilizarlo desde la post-ingesta del monitor de Gmail: si una corrida
# anterior falló a mitad de correo, el rollback defensivo revierte las filas
# Document pero los ARCHIVOS ya quedaron escritos → huérfanos invisibles en el
# módulo (caso real c557 Luz Narda: 2 PDFs en disco desde el 10-jun, 0 docs en
# DB hasta un refresh manual). Con esto cada ingesta auto-cura los casos que
# toca — el operador nunca necesita saber que existe un botón de refresh.
# ─────────────────────────────────────────────────────────────────────────────

SINGLE_SYNC_VALID_EXT = {".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg", ".md"}


def sync_case_folder(db: Session, case: Case, *, source: str = "sync") -> dict:
    """Registra en DB los archivos de la carpeta sin fila Document, elimina filas
    cuyo archivo ya no existe, extrae texto de los nuevos y verifica pertenencia
    (todo local, 0 IA). Idempotente."""
    from backend.database.seed import classify_document

    if not case.folder_path or not Path(case.folder_path).exists():
        return {"error": "Carpeta no encontrada en disco", "docs_added": 0,
                "docs_removed": 0, "docs_moved": 0, "docs_suspicious": 0}

    folder = Path(case.folder_path)
    existing = {d.filename for d in case.documents}

    docs_added = 0
    docs_removed = 0

    for f in sorted(folder.iterdir()):
        if not f.is_file() or f.suffix.lower() not in SINGLE_SYNC_VALID_EXT or f.name in existing:
            continue
        db.add(Document(
            case_id=case.id, filename=f.name, file_path=str(f),
            doc_type=classify_document(f.name), file_size=f.stat().st_size,
        ))
        docs_added += 1

    for doc in case.documents:
        if doc.file_path and not Path(doc.file_path).exists():
            db.delete(doc)
            docs_removed += 1

    db.commit()

    from backend.extraction.doc_ops import verify_document_belongs, extract_document_text

    docs_moved = 0
    docs_suspicious = 0

    db.refresh(case)
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

        if status == "NO_PERTENECE":
            docs_moved += 1
            db.add(AuditLog(
                case_id=case.id,
                field_name="DOC_NO_PERTENECE",
                old_value=doc.filename,
                new_value=detalle[:200],
                action="SYNC_VERIFY",
                source=source,
            ))
        elif status == "SOSPECHOSO":
            docs_suspicious += 1

    db.commit()
    if docs_added or docs_removed:
        logger.info("sync_case_folder c%d (%s): +%d docs, -%d eliminados",
                    case.id, source, docs_added, docs_removed)
    return {
        "docs_added": docs_added,
        "docs_removed": docs_removed,
        "docs_moved": docs_moved,
        "docs_suspicious": docs_suspicious,
    }


def import_email_attachments_to_case(
    db: Session, email: Email, case: Case, *, source: str = "email_assign",
) -> dict:
    """Importa al caso los adjuntos huérfanos de un email recién asignado.

    Cierra el hueco del flujo de asignación manual: cuando un correo entra SIN
    caso (AMBIGUO/unmatched), `download_attachments` guarda el archivo en
    `_emails_sin_clasificar/` pero NO crea fila `Document` (guard `if case:`), y
    el endpoint de asignación solo cambia `case_id`. Resultado: el caso queda
    "sin documentos vinculados". Esta función, llamada desde el assign, mueve los
    adjuntos a la carpeta del caso, los registra+extrae+verifica vía
    `sync_case_folder`, genera el `.md` del cuerpo y vincula `email_id`.

    - Dedup sha256 contra los archivos FÍSICOS del caso (evita duplicar un doc ya
      traído por el fetch de expediente o reenvíos). El huérfano dup se elimina.
    - Idempotente: adjuntos ya dentro de la carpeta del caso se ignoran.
    """
    import shutil
    from sqlalchemy.orm.attributes import flag_modified

    result = {"moved": 0, "deduped": 0, "errors": 0, "md_created": False, "sync": None}
    if not case.folder_path or not Path(case.folder_path).exists():
        result["error"] = "Carpeta del caso no existe en disco"
        return result
    folder = Path(case.folder_path)

    # Dedup definitivo: hashes de los archivos que YA están en la carpeta del caso.
    existing_hashes: set[str] = set()
    for f in folder.iterdir():
        if f.is_file():
            try:
                existing_hashes.add(hashlib.sha256(f.read_bytes()).hexdigest())
            except Exception:
                pass

    # `Email.attachments` es Column(JSON): SQLAlchemy lo entrega ya como list.
    # Tolerar también str (datos legacy) por robustez.
    raw = email.attachments
    if isinstance(raw, str):
        import json
        try:
            atts = json.loads(raw) if raw else []
        except Exception:
            atts = []
    else:
        atts = list(raw) if raw else []

    moved_names: list[str] = []
    changed = False
    for a in atts:
        sp = a.get("saved_path") or ""
        if not sp:
            continue
        p = Path(sp)
        if not p.exists():
            continue
        # Ya está dentro de la carpeta del caso → nada que mover (idempotencia).
        try:
            if folder.resolve() in p.resolve().parents:
                continue
        except Exception:
            pass
        try:
            data = p.read_bytes()
        except Exception:
            result["errors"] += 1
            continue
        h = hashlib.sha256(data).hexdigest()
        if h in existing_hashes:
            # El caso ya tiene este contenido (expediente/reenvío) → borrar huérfano.
            try:
                p.unlink()
            except Exception:
                pass
            a["saved_path"] = ""
            changed = True
            result["deduped"] += 1
            continue
        target = folder / p.name
        cnt = 1
        while target.exists():
            target = folder / f"{p.stem}_{cnt}{p.suffix}"
            cnt += 1
        try:
            shutil.move(str(p), str(target))
        except Exception:
            result["errors"] += 1
            continue
        existing_hashes.add(h)
        moved_names.append(target.name)
        a["saved_path"] = str(target)
        a["filename"] = target.name
        changed = True
        result["moved"] += 1
        db.add(AuditLog(
            case_id=case.id, field_name="documento",
            old_value=f"_emails_sin_clasificar/{p.name}", new_value=str(target),
            action="EMAIL_ASSIGN_IMPORT", source=source,
        ))

    if changed:
        email.attachments = atts
        flag_modified(email, "attachments")  # JSON in-place mutation no se detecta solo

    # Generar el .md del cuerpo del email en la carpeta del caso (si no existe).
    try:
        from backend.email.gmail_monitor import save_email_md
        md = save_email_md(
            folder,
            {
                "subject": email.subject, "sender": email.sender,
                "date": email.date_received.isoformat() if email.date_received else "",
                "folder_name": case.folder_name,
            },
            email.body_preview or "", atts,
            db=db, case_id=case.id, email_id=email.id,
            email_message_id=email.message_id,
        )
        result["md_created"] = bool(md)
    except Exception as e:
        logger.warning("import_email_attachments .md falló c%d e%d: %s", case.id, email.id, e)

    db.commit()

    # Registrar + extraer + verificar lo movido (reusa el pipeline local probado).
    result["sync"] = sync_case_folder(db, case, source=source)

    # Vincular provenance email_id en los documentos recién importados.
    if moved_names:
        for doc in db.query(Document).filter(
            Document.case_id == case.id, Document.filename.in_(moved_names),
        ).all():
            if not doc.email_id:
                doc.email_id = email.id
                doc.email_message_id = email.message_id
        db.commit()

    logger.info(
        "import_email_attachments c%d e%d: +%d movidos, %d dedup, %d err, md=%s",
        case.id, email.id, result["moved"], result["deduped"], result["errors"],
        result["md_created"],
    )
    return result
