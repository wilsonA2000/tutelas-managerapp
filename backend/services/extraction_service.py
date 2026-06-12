"""Servicio de extraccion - orquesta batch y revision."""

from sqlalchemy.orm import Session

from backend.database.models import Case, Document, Extraction
from backend.extraction.doc_ops import reextract_document


def get_review_queue(db: Session) -> list[dict]:
    """Obtener casos que necesitan revision/extracción.

    Ciclo de vida 2026-06-12 — cada fila lleva `estado_extraccion` (autoridad
    derivada de case_service): NUNCA_EXTRAIDO (candidata, típicamente caso nuevo
    de la ingesta) / DESACTUALIZADO (docs llegados después de la última pasada
    v9) / AL_DIA. Incluye también casos COMPLETO con docs nuevos (antes
    invisibles: el filtro por processing_status no los veía).
    Orden: candidatas primero, luego desactualizados, luego el resto.
    """
    from sqlalchemy.orm import selectinload
    from backend.services.case_service import (
        estado_extraccion, case_last_extraction_at,
    )

    # QUERY 1: Casos con eager load de documentos (evita N lazy loads)
    cases = db.query(Case).filter(
        Case.processing_status.in_(["REVISION", "PENDIENTE"]),
        Case.folder_name.isnot(None), Case.folder_name != "None", Case.folder_name != "",
    ).options(selectinload(Case.documents)).all()

    # QUERY 1b: casos extraídos (COMPLETO) que recibieron docs DESPUÉS de su
    # última extracción — el "necesita re-extracción" que Wilson no podía ver.
    seen = {c.id for c in cases}
    completos = db.query(Case).filter(
        Case.processing_status == "COMPLETO",
        Case.folder_name.isnot(None), Case.folder_name != "None", Case.folder_name != "",
    ).options(selectinload(Case.documents)).all()
    for c in completos:
        if c.id in seen:
            continue
        last = case_last_extraction_at(c)
        if last and any(d.created_at and d.created_at > last for d in c.documents):
            cases.append(c)
            seen.add(c.id)

    if not cases:
        return []

    # QUERY 2: Batch — todas las extractions BAJA de estos casos en 1 query
    case_ids = [c.id for c in cases]
    low_conf_rows = db.query(
        Extraction.case_id, Extraction.field_name,
    ).filter(
        Extraction.case_id.in_(case_ids),
        Extraction.confidence == "BAJA",
    ).all()

    # Agrupar por case_id
    low_conf_map: dict[int, list[str]] = {}
    for row in low_conf_rows:
        low_conf_map.setdefault(row.case_id, []).append(row.field_name)

    # Construir respuesta sin queries adicionales
    queue = []
    for case in cases:
        empty_fields = [csv_col for csv_col, attr in Case.CSV_FIELD_MAP.items() if not getattr(case, attr)]
        docs = case.documents  # Ya cargados por selectinload
        ext = estado_extraccion(db, case)
        queue.append({
            "case_id": case.id,
            "folder_name": case.folder_name,
            "accionante": case.accionante or "",
            "low_confidence_fields": low_conf_map.get(case.id, []),
            "empty_fields": empty_fields,
            "document_count": len(docs),
            "docs_no_pertenece": sum(1 for d in docs if d.verificacion == "NO_PERTENECE"),
            "docs_sospechosos": sum(1 for d in docs if d.verificacion == "SOSPECHOSO"),
            "estado_extraccion": ext["estado"],
            "last_extraction_at": ext["last_extraction_at"],
            "docs_nuevos": ext["docs_nuevos"],
        })

    _orden = {"NUNCA_EXTRAIDO": 0, "DESACTUALIZADO": 1, "AL_DIA": 2}
    queue.sort(key=lambda q: (_orden.get(q["estado_extraccion"], 3), -q["docs_nuevos"]))
    return queue


def reextract_doc(db: Session, document_id: int) -> dict:
    """Re-extraer texto de un documento especifico."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        return {"error": "Documento no encontrado"}

    text, method = reextract_document(db, doc)
    return {
        "document_id": doc.id,
        "filename": doc.filename,
        "method": method,
        "text_length": len(text),
        "success": bool(text.strip()),
    }
