"""Wrapper stateless del orquestador cognitivo v6.0 para ejecutarse en el pod.

Crea una DB SQLite en memoria por request, inserta el caso recibido, ejecuta
las capas 0-5 del pipeline cognitivo (OCR + NER + IR + identifiers + bayesian
+ actor graph + cognitive fill + timeline + classifier), y serializa el
resultado para que el cliente (backend local) lo aplique a su DB real.

Las capas 6 (live_consolidator, cross-case) y 7 (persist + entropy gate +
audit_log) SE QUEDAN LOCAL porque dependen de la DB real con todos los casos.

Este módulo reutiliza el mismo código de `backend/extraction/unified_cognitive.py`
pasándole `skip_consolidation_and_persist=True`.
"""

from __future__ import annotations

import io
import json
import logging
import shutil
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from backend.database.models import AuditLog, Base, Case, Document, Email
from backend.extraction.unified_cognitive import unified_cognitive_extract


logger = logging.getLogger("tutelas.pod.worker")


# ============================================================
# Campos que se serializan en el response
# ============================================================

CASE_FIELDS_TO_RETURN = (
    "radicado_23_digitos", "radicado_forest", "abogado_responsable",
    "accionante", "accionados", "vinculados", "derecho_vulnerado",
    "juzgado", "ciudad", "fecha_ingreso", "asunto", "pretensiones",
    "oficina_responsable", "estado", "fecha_respuesta",
    "sentido_fallo_1st", "fecha_fallo_1st", "impugnacion", "quien_impugno",
    "forest_impugnacion", "juzgado_2nd", "sentido_fallo_2nd",
    "fecha_fallo_2nd", "incidente", "fecha_apertura_incidente",
    "responsable_desacato", "decision_incidente",
    "incidente_2", "fecha_apertura_incidente_2", "responsable_desacato_2",
    "decision_incidente_2", "incidente_3", "fecha_apertura_incidente_3",
    "responsable_desacato_3", "decision_incidente_3",
    "observaciones", "categoria_tematica",
    # v6.0
    "origen", "estado_incidente", "entropy_score", "convergence_iterations",
    "processing_status", "tipo_actuacion",
)

DOC_FIELDS_TO_RETURN = (
    "extracted_text", "extraction_method", "page_count", "file_size",
    "doc_type", "verificacion", "verificacion_detalle", "file_hash",
    "institutional_score", "visual_signature_json",
)


# ============================================================
# Session factory in-memory
# ============================================================

def _make_in_memory_session() -> Session:
    """Crea una nueva engine+session SQLite in-memory con el schema completo."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        echo=False,
    )

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    SessionCls = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return SessionCls()


def _parse_datetime(val: Any) -> datetime | None:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(str(val).replace("Z", ""))
    except Exception:
        return None


# ============================================================
# Reconstrucción del caso desde el JSON del cliente
# ============================================================

def _hydrate_case(db: Session, case_meta: dict, tmp_dir: Path) -> tuple[Case, dict]:
    """Inserta Case + Emails + Documents en la DB in-memory.

    Retorna (case, mapping) donde mapping = {
        "docs_id_map": {in_memory_id: original_id},
        "emails_id_map": {in_memory_id: original_id},
    }
    """
    case_data = case_meta["case"]
    case_kwargs = {
        k: v for k, v in case_data.items()
        if hasattr(Case, k) and k not in ("id", "documents", "emails", "audit_logs")
    }
    # Fechas
    for dt_field in ("created_at", "updated_at"):
        if dt_field in case_kwargs:
            case_kwargs[dt_field] = _parse_datetime(case_kwargs[dt_field])
    case_kwargs.pop("created_at", None)  # que se autogenere
    case_kwargs.pop("updated_at", None)
    case = Case(**case_kwargs)
    db.add(case)
    db.flush()

    # Emails
    emails_id_map = {}
    for em_data in case_meta.get("emails", []) or []:
        original_id = em_data.get("id")
        kwargs = {
            k: v for k, v in em_data.items()
            if hasattr(Email, k) and k not in ("id", "case_id", "documents")
        }
        for dt_field in ("date_received", "processed_at"):
            if dt_field in kwargs:
                kwargs[dt_field] = _parse_datetime(kwargs[dt_field])
        em = Email(case_id=case.id, **kwargs)
        db.add(em)
        db.flush()
        if original_id is not None:
            emails_id_map[em.id] = original_id

    # Mapeo inverso para resolver email_id de documentos
    original_email_to_new = {v: k for k, v in emails_id_map.items()}

    # Documents: file_path apunta a los archivos extraídos del ZIP
    docs_id_map = {}
    for doc_data in case_meta.get("documents", []) or []:
        original_doc_id = doc_data.get("id")
        filename = doc_data["filename"]
        local_path = tmp_dir / filename
        # Si el archivo no está en el ZIP (email sin adjunto, body_md, etc.)
        # dejamos el path aunque no exista: el pipeline decidirá extraction_method.
        kwargs = {
            "case_id": case.id,
            "filename": filename,
            "file_path": str(local_path),
            "doc_type": doc_data.get("doc_type") or "OTRO",
            "extracted_text": doc_data.get("extracted_text"),
            "extraction_method": doc_data.get("extraction_method"),
            "page_count": doc_data.get("page_count"),
            "file_size": doc_data.get("file_size"),
            "verificacion": doc_data.get("verificacion") or "",
            "verificacion_detalle": doc_data.get("verificacion_detalle") or "",
            "file_hash": doc_data.get("file_hash") or "",
            "email_message_id": doc_data.get("email_message_id"),
            "institutional_score": doc_data.get("institutional_score"),
            "visual_signature_json": doc_data.get("visual_signature_json"),
        }
        if "extraction_date" in doc_data:
            kwargs["extraction_date"] = _parse_datetime(doc_data["extraction_date"])
        # email_id traducido
        orig_email_id = doc_data.get("email_id")
        if orig_email_id in original_email_to_new:
            kwargs["email_id"] = original_email_to_new[orig_email_id]

        doc = Document(**kwargs)
        db.add(doc)
        db.flush()
        if original_doc_id is not None:
            docs_id_map[doc.id] = original_doc_id

    db.commit()
    db.refresh(case)

    return case, {"docs_id_map": docs_id_map, "emails_id_map": emails_id_map}


# ============================================================
# Serialización del resultado
# ============================================================

def _serialize_case(case: Case) -> dict:
    out = {}
    for field in CASE_FIELDS_TO_RETURN:
        val = getattr(case, field, None)
        if isinstance(val, datetime):
            out[field] = val.isoformat()
        else:
            out[field] = val
    return out


def _serialize_documents(db: Session, docs_id_map: dict[int, int]) -> list[dict]:
    out = []
    for in_mem_id, original_id in docs_id_map.items():
        doc = db.query(Document).filter(Document.id == in_mem_id).first()
        if not doc:
            continue
        upd = {"original_id": original_id, "filename": doc.filename}
        for field in DOC_FIELDS_TO_RETURN:
            val = getattr(doc, field, None)
            if val is not None and val != "":
                upd[field] = val
        if doc.extraction_date:
            upd["extraction_date"] = doc.extraction_date.isoformat()
        out.append(upd)
    return out


def _serialize_audit_logs(db: Session, case_id: int) -> list[dict]:
    """Serializa los audit_log generados en la DB in-memory durante phases 0-5."""
    out = []
    for log_entry in db.query(AuditLog).filter(AuditLog.case_id == case_id).all():
        out.append({
            "action": log_entry.action,
            "source": log_entry.source,
            "created_at": log_entry.created_at.isoformat() if log_entry.created_at else None,
        })
    return out


# ============================================================
# Entry point
# ============================================================

@dataclass
class PodResult:
    case_updates: dict
    documents_updates: list[dict]
    audit_logs: list[dict]
    stats: dict

    def to_dict(self) -> dict:
        return asdict(self)


def process_case(case_meta: dict, zip_bytes: bytes) -> PodResult:
    """Procesa un caso stateless. Raise en caso de error fatal.

    Args:
        case_meta: dict con claves "case", "documents", "emails"
        zip_bytes: ZIP con los archivos (filename → bytes) de los documentos

    Returns:
        PodResult con updates a aplicar en la DB real del cliente.
    """
    t0 = datetime.utcnow()
    tmp_root = Path(tempfile.mkdtemp(prefix="pod_case_"))
    try:
        # 1. Extraer ZIP a directorio temporal
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(tmp_root)
        logger.info("ZIP extraído a %s (%d archivos)",
                    tmp_root, len(list(tmp_root.iterdir())))

        # 2. Crear DB in-memory y hidratar el caso
        db = _make_in_memory_session()
        try:
            case, id_maps = _hydrate_case(db, case_meta, tmp_root)
            logger.info("Case hidratado id=%d docs=%d emails=%d",
                        case.id, len(id_maps["docs_id_map"]), len(id_maps["emails_id_map"]))

            # 3. Ejecutar pipeline 0-5
            stats = unified_cognitive_extract(
                db, case,
                base_dir=str(tmp_root),
                classify_docs=False,
                skip_consolidation_and_persist=True,
            )

            # 4. Serializar resultado
            db.refresh(case)
            case_updates = _serialize_case(case)
            documents_updates = _serialize_documents(db, id_maps["docs_id_map"])
            audit_logs = _serialize_audit_logs(db, case.id)

            stats["pod_duration_s"] = (datetime.utcnow() - t0).total_seconds()

            return PodResult(
                case_updates=case_updates,
                documents_updates=documents_updates,
                audit_logs=audit_logs,
                stats=stats,
            )
        finally:
            db.close()
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
