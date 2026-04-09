"""Servicio de extraccion - orquesta batch y revision."""

from sqlalchemy.orm import Session

from backend.database.models import Case, Document, Extraction
from backend.extraction.pipeline import process_folder, reextract_document


def extract_single(db: Session, case_id: int) -> dict:
    """Extraer datos de un caso individual."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return {"error": "Caso no encontrado"}

    stats = process_folder(db, case)
    return {
        "case_id": case.id,
        "folder_name": case.folder_name,
        "status": case.processing_status,
        **stats,
    }



def get_review_queue(db: Session) -> list[dict]:
    """Obtener casos que necesitan revision. Optimizado v4.0: 3 queries en vez de 1+2N."""
    from sqlalchemy.orm import selectinload
    from sqlalchemy import func

    # QUERY 1: Casos con eager load de documentos (evita N lazy loads)
    cases = db.query(Case).filter(
        Case.processing_status.in_(["REVISION", "PENDIENTE"]),
        Case.folder_name.isnot(None), Case.folder_name != "None", Case.folder_name != "",
    ).options(selectinload(Case.documents)).all()

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
        queue.append({
            "case_id": case.id,
            "folder_name": case.folder_name,
            "accionante": case.accionante or "",
            "low_confidence_fields": low_conf_map.get(case.id, []),
            "empty_fields": empty_fields,
            "document_count": len(docs),
            "docs_no_pertenece": sum(1 for d in docs if d.verificacion == "NO_PERTENECE"),
            "docs_sospechosos": sum(1 for d in docs if d.verificacion == "SOSPECHOSO"),
        })

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
