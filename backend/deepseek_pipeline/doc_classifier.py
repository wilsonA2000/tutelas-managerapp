"""Clasificador de documentos usando DeepSeek."""
from __future__ import annotations
import logging
import time
from pathlib import Path
from sqlalchemy.orm import Session

from .client import call_deepseek_json
from .prompts import DOC_CLASSIFIER
from .types import DocClassification

log = logging.getLogger("tutelas.deepseek_pipeline.doc_classifier")

# Mapa de tipos canónicos del pipeline → tipos que usa el resto de la app
CANONICAL_TO_APP: dict[str, str] = {
    "DEMANDA_TUTELA":           "DEMANDA_TUTELA",
    "AUTO_ADMISORIO":           "AUTO_ADMISORIO",
    "SENTENCIA_1RA":            "SENTENCIA_1RA",
    "NOTIFICACION":             "NOTIFICACION",
    "RESPUESTA_SED":            "RESPUESTA",
    "IMPUGNACION":              "IMPUGNACION",
    "AUTO_CONCEDE_IMPUGNACION": "AUTO_CONCEDE_IMPUGNACION",
    "SENTENCIA_2DA":            "SENTENCIA_2DA",
    "INCIDENTE_DESACATO":       "INCIDENTE_DESACATO",
    "AUTO_INCIDENTE":           "AUTO_INCIDENTE",
    "EMAIL_MD":                 "EMAIL_MD",
    "ACTA_REPARTO":             "ACTA_REPARTO",
    "AUTO_VINCULA":             "AUTO_VINCULA",
    "OFICIO_CUMPLIMIENTO":      "OFICIO_CUMPLIMIENTO",
    "ANEXO":                    "ANEXO_PRUEBA",
    "INSUMO_SED":               "INSUMO_CONTESTACION",
    "AUTO_OTRO":                "PDF_OTRO",
    "OTRO":                     "PDF_OTRO",
}


def classify_document(
    doc_id: int,
    filename: str,
    text: str,
) -> DocClassification:
    """Clasifica un solo documento usando DeepSeek."""
    head = text[:2000] if text else ""
    tail = text[-1000:] if len(text) > 2500 else ""
    snippet = head + ("\n[...]\n" + tail if tail else "")

    user_msg = f"NOMBRE DE ARCHIVO: {filename}\n\nCONTENIDO:\n{snippet}"

    t0 = time.perf_counter()
    try:
        data = call_deepseek_json(DOC_CLASSIFIER, user_msg, max_tokens=300)
        elapsed = int((time.perf_counter() - t0) * 1000)
        return DocClassification(
            doc_id=doc_id,
            filename=filename,
            tipo=data.get("tipo", "OTRO"),
            instancia=data.get("instancia", "N/A"),
            confianza=data.get("confianza", "baja"),
            señales=data.get("señales_usadas", []),
            razon=data.get("razon", ""),
            elapsed_ms=elapsed,
        )
    except Exception as exc:
        elapsed = int((time.perf_counter() - t0) * 1000)
        log.warning("classify_document doc%d falló: %s", doc_id, exc)
        return DocClassification(
            doc_id=doc_id, filename=filename,
            tipo="OTRO", instancia="N/A", confianza="baja",
            señales=[], razon="", elapsed_ms=elapsed,
            error=str(exc)[:200],
        )


def classify_case_docs(db: Session, case_id: int) -> list[DocClassification]:
    """Clasifica todos los documentos de un caso."""
    from backend.database.models import Document
    docs = db.query(Document).filter(Document.case_id == case_id).all()
    results = []
    for doc in docs:
        text = doc.extracted_text or ""
        if not text and doc.file_path:
            # Intentar leer el texto del disco
            try:
                from backend.extraction.doc_ops import extract_document_text
                text, _ = extract_document_text(Path(doc.file_path))
            except Exception:
                pass
        result = classify_document(doc.id, doc.filename or "", text)
        results.append(result)
        log.info("doc%d '%s' → %s (%s)", doc.id, doc.filename, result.tipo, result.confianza)
    return results
