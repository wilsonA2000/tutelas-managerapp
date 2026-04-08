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
    """Obtener casos que necesitan revision (pendientes, baja confianza o campos vacios)."""
    cases = db.query(Case).filter(
        Case.processing_status.in_(["REVISION", "PENDIENTE"]),
        Case.folder_name.isnot(None), Case.folder_name != "None", Case.folder_name != "",
    ).all()

    queue = []
    for case in cases:
        low_confidence = db.query(Extraction).filter(
            Extraction.case_id == case.id,
            Extraction.confidence == "BAJA",
        ).all()

        empty_fields = []
        for csv_col, attr in Case.CSV_FIELD_MAP.items():
            if not getattr(case, attr):
                empty_fields.append(csv_col)

        # Contar docs con alertas de verificacion
        docs_no_pertenece = sum(1 for d in case.documents if d.verificacion == "NO_PERTENECE")
        docs_sospechosos = sum(1 for d in case.documents if d.verificacion == "SOSPECHOSO")

        queue.append({
            "case_id": case.id,
            "folder_name": case.folder_name,
            "accionante": case.accionante or "",
            "low_confidence_fields": [e.field_name for e in low_confidence],
            "empty_fields": empty_fields,
            "document_count": len(case.documents),
            "docs_no_pertenece": docs_no_pertenece,
            "docs_sospechosos": docs_sospechosos,
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
