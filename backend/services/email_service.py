"""Servicio de gestion de emails."""

from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from backend.database.models import Email, Case


def list_emails(db: Session, search: str = "", status: str = "", page: int = 1, per_page: int = 20) -> dict:
    """Listar emails recibidos con busqueda y snippet del body."""
    query = db.query(Email)

    if status:
        query = query.filter(Email.status.ilike(status))

    if search:
        term = f"%{search}%"
        query = query.filter(or_(
            Email.subject.ilike(term),
            Email.sender.ilike(term),
            Email.body_preview.ilike(term),
        ))

    total = query.count()
    rows = query.order_by(Email.date_received.desc()).offset((page - 1) * per_page).limit(per_page).all()

    # Precargar folder_names
    case_ids = {r.case_id for r in rows if r.case_id}
    case_folders = {}
    if case_ids:
        cases = db.query(Case.id, Case.folder_name).filter(Case.id.in_(case_ids)).all()
        case_folders = {c.id: c.folder_name for c in cases}

    items = []
    for r in rows:
        # Convertir fecha UTC a Colombia (UTC-5)
        fecha = None
        if r.date_received:
            from datetime import timezone, timedelta
            utc_dt = r.date_received.replace(tzinfo=timezone.utc)
            colombia_dt = utc_dt.astimezone(timezone(timedelta(hours=-5)))
            fecha = colombia_dt.isoformat()

        # Snippet: primeros 120 chars del body
        snippet = ""
        if r.body_preview:
            snippet = r.body_preview[:120].replace("\n", " ").strip()
            if len(r.body_preview) > 120:
                snippet += "..."

        # Contar adjuntos
        attachments_count = len(r.attachments) if r.attachments else 0

        items.append({
            "id": r.id,
            "message_id": r.message_id,
            "subject": r.subject,
            "sender": r.sender,
            "received_at": fecha,
            "status": (r.status or "").lower(),
            "case_id": r.case_id,
            "case_folder": case_folders.get(r.case_id, ""),
            "snippet": snippet,
            "attachments_count": attachments_count,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
    }
