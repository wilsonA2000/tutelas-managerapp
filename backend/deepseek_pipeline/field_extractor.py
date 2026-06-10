"""Extractor de 43 campos usando DeepSeek con contexto completo del expediente."""
from __future__ import annotations
import logging
import time
from pathlib import Path
from sqlalchemy.orm import Session

from .client import call_deepseek_json
from .prompts import FIELD_EXTRACTOR
from .types import FieldExtractionResult, FieldValue

log = logging.getLogger("tutelas.deepseek_pipeline.field_extractor")

# Orden de prioridad para enviar documentos (los más informativos primero)
DOC_PRIORITY = [
    "DEMANDA_TUTELA", "AUTO_ADMISORIO", "SENTENCIA_1RA",
    "RESPUESTA_SED", "SENTENCIA_2DA", "IMPUGNACION",
    "AUTO_CONCEDE_IMPUGNACION", "INCIDENTE_DESACATO", "AUTO_INCIDENTE",
    "NOTIFICACION", "OFICIO_CUMPLIMIENTO", "AUTO_VINCULA",
]

# Todos los campos del cuadro Excel (mismo orden que EXCEL_FIELDS en types.py)
ALL_FIELDS = [
    "radicado_23_digitos", "radicado_forest", "tipo_actuacion",
    "accionante", "accionados", "vinculados",
    "derecho_vulnerado", "categoria_tematica",
    "juzgado", "ciudad",
    "fecha_ingreso", "asunto", "pretensiones",
    "oficina_responsable", "abogado_responsable", "estado", "fecha_respuesta",
    "sentido_fallo_1st", "fecha_fallo_1st", "parte_resolutiva_1st",
    "impugnacion", "quien_impugno", "forest_impugnacion",
    "juzgado_2nd", "sentido_fallo_2nd", "fecha_fallo_2nd", "parte_resolutiva_2nd",
    "incidente", "fecha_apertura_incidente", "responsable_desacato",
    "abogado_incidente", "decision_incidente",
    "incidente_2", "fecha_apertura_incidente_2", "responsable_desacato_2",
    "abogado_incidente_2", "decision_incidente_2",
    "incidente_3", "fecha_apertura_incidente_3", "responsable_desacato_3",
    "abogado_incidente_3", "decision_incidente_3",
    "observaciones",
]


def _get_doc_text(doc, max_chars: int = 3000) -> str:
    """Devuelve head+tail del texto del documento."""
    text = doc.extracted_text or ""
    if not text and doc.file_path:
        try:
            from backend.extraction.doc_ops import extract_document_text
            text, _ = extract_document_text(Path(doc.file_path))
        except Exception:
            pass
    if not text:
        return ""
    head = text[:2000]
    tail = text[-1000:] if len(text) > 2500 else ""
    return head + ("\n[...]\n" + tail if tail else "")


def _select_docs_for_extraction(
    db: Session, case_id: int,
    classified_types: dict[int, str] | None = None,
) -> list[tuple[str, str, str]]:
    """
    Selecciona los documentos más relevantes para la extracción.
    Retorna lista de (tipo_canónico, filename, texto).
    classified_types: {doc_id: tipo_canónico} del doc_classifier (opcional).
    """
    from backend.database.models import Document

    docs = db.query(Document).filter(Document.case_id == case_id).all()
    if not docs:
        return []

    # Mapa doc_type DB → tipo canónico del pipeline
    DB_TO_CANONICAL = {
        "DEMANDA_TUTELA": "DEMANDA_TUTELA", "DEMANDA": "DEMANDA_TUTELA",
        "AUTO_ADMISORIO": "AUTO_ADMISORIO", "PDF_AUTO_ADMISORIO": "AUTO_ADMISORIO",
        "SENTENCIA_1RA": "SENTENCIA_1RA", "PDF_SENTENCIA": "SENTENCIA_1RA",
        "RESPUESTA": "RESPUESTA_SED", "DOCX_RESPUESTA": "RESPUESTA_SED", "RESPUESTA_SED": "RESPUESTA_SED",
        "SENTENCIA_2DA": "SENTENCIA_2DA", "AUTO_2DA": "SENTENCIA_2DA",
        "IMPUGNACION": "IMPUGNACION", "PDF_IMPUGNACION": "IMPUGNACION",
        "AUTO_CONCEDE_IMPUGNACION": "AUTO_CONCEDE_IMPUGNACION",
        "INCIDENTE_DESACATO": "INCIDENTE_DESACATO", "PDF_INCIDENTE": "INCIDENTE_DESACATO",
        "AUTO_INCIDENTE": "AUTO_INCIDENTE",
        "NOTIFICACION": "NOTIFICACION", "NOTIFICACION_FALLO": "NOTIFICACION",
        "OFICIO_CUMPLIMIENTO": "OFICIO_CUMPLIMIENTO",
        "AUTO_VINCULA": "AUTO_VINCULA",
    }

    # Agrupar docs por tipo canónico, usar DeepSeek classification si disponible
    by_type: dict[str, list] = {}
    for doc in docs:
        if classified_types and doc.id in classified_types:
            tipo = classified_types[doc.id]
        else:
            tipo = DB_TO_CANONICAL.get(doc.doc_type or "", None)
        if tipo is None:
            continue
        by_type.setdefault(tipo, []).append(doc)

    # Seleccionar en orden de prioridad, máximo 1 doc por tipo clave
    selected = []
    for tipo in DOC_PRIORITY:
        if tipo not in by_type:
            continue
        # Tomar el doc con más texto (más información)
        best = max(by_type[tipo], key=lambda d: len(d.extracted_text or ""))
        text = _get_doc_text(best)
        if text:
            selected.append((tipo, best.filename or "", text))

    return selected


def extract_fields(
    db: Session,
    case_id: int,
    classified_types: dict[int, str] | None = None,
) -> FieldExtractionResult:
    """
    Extrae los 43 campos del cuadro usando DeepSeek.
    classified_types: resultado del doc_classifier (mejora la selección).
    """
    from backend.database.models import Case
    case = db.query(Case).filter(Case.id == case_id).first()
    folder_name = case.folder_name if case else f"case_{case_id}"

    docs = _select_docs_for_extraction(db, case_id, classified_types)
    if not docs:
        return FieldExtractionResult(
            case_id=case_id, folder_name=folder_name,
            campos={}, docs_usados=[],
            error="Sin documentos con texto para extraer",
        )

    # Construir el mensaje del usuario con los documentos
    docs_text = ""
    docs_usados = []
    for tipo, filename, text in docs:
        docs_text += f"\n[{tipo} — {filename}]\n{text}\n"
        docs_usados.append(tipo)

    user_msg = f"Expediente: {folder_name}\n\nDOCUMENTOS DEL EXPEDIENTE:{docs_text}"

    t0 = time.perf_counter()
    try:
        data = call_deepseek_json(
            FIELD_EXTRACTOR, user_msg,
            max_tokens=2500,
            temperature=0,
        )
        elapsed = int((time.perf_counter() - t0) * 1000)

        # Parsear respuesta campo por campo
        campos: dict[str, FieldValue] = {}
        for field_name in ALL_FIELDS:
            raw = data.get(field_name, {})
            if isinstance(raw, dict):
                campos[field_name] = FieldValue(
                    valor=str(raw.get("valor", "") or "").strip(),
                    fuente_doc=str(raw.get("fuente", "") or ""),
                    confianza=str(raw.get("confianza", "baja") or "baja"),
                    nota=str(raw.get("nota", "") or ""),
                )
            elif isinstance(raw, str):
                campos[field_name] = FieldValue(valor=raw.strip(), fuente_doc="", confianza="baja")
            else:
                campos[field_name] = FieldValue(valor="", fuente_doc="", confianza="baja")

        return FieldExtractionResult(
            case_id=case_id,
            folder_name=folder_name,
            campos=campos,
            docs_usados=docs_usados,
            elapsed_ms=elapsed,
            llm_calls=1,
        )

    except Exception as exc:
        elapsed = int((time.perf_counter() - t0) * 1000)
        log.exception("extract_fields case%d falló", case_id)
        return FieldExtractionResult(
            case_id=case_id, folder_name=folder_name,
            campos={}, docs_usados=docs_usados,
            elapsed_ms=elapsed, llm_calls=1,
            error=str(exc)[:300],
        )
