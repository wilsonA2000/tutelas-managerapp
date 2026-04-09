"""Router de emails."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.database.models import Email, Case, AuditLog
from backend.services.email_service import list_emails

router = APIRouter(prefix="/api/emails", tags=["emails"])


@router.get("")
def api_list_emails(
    search: str = "",
    status: str = "",
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return list_emails(db, search, status, page, per_page)


@router.put("/{email_id}/assign/{case_id}")
def api_assign_email(email_id: int, case_id: int, db: Session = Depends(get_db)):
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email no encontrado")

    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Caso no encontrado")

    email.case_id = case_id
    email.status = "ASIGNADO"

    db.add(AuditLog(
        case_id=case_id,
        action="IMPORT_EMAIL",
        source="usuario",
        new_value=f"Email asignado: {email.subject}",
    ))
    db.commit()

    return email.to_dict()


@router.get("/detail/{email_id}")
def api_get_email(email_id: int, db: Session = Depends(get_db)):
    """Obtener un email individual con cuerpo completo y adjuntos."""
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email no encontrado")

    data = email.to_dict()
    # Incluir body completo
    data["body"] = email.body_preview or ""
    # Info del caso asignado
    if email.case_id:
        case = db.query(Case).filter(Case.id == email.case_id).first()
        if case:
            data["case_folder"] = case.folder_name
            data["case_accionante"] = case.accionante or ""
    return data


@router.get("/{email_id}/package")
def api_get_email_package(email_id: int, db: Session = Depends(get_db)):
    """v4.8 Provenance: obtener el paquete completo (email + todos sus documents hijos).

    Devuelve la unidad atomica: email_body + adjuntos + .md generado,
    todos vinculados por el mismo email_id.
    """
    from backend.services.provenance_service import get_package_by_email

    pkg = get_package_by_email(db, email_id)
    if pkg is None:
        raise HTTPException(status_code=404, detail="Email no encontrado")

    email = pkg["email"]
    return {
        "email": {
            "id": email.id,
            "message_id": email.message_id,
            "subject": email.subject,
            "sender": email.sender,
            "date_received": email.date_received.isoformat() if email.date_received else None,
            "body": email.body_preview or "",
            "case_id": email.case_id,
            "status": email.status,
        },
        "documents": [d.to_dict() for d in pkg["documents"]],
        "count": pkg["count"],
    }


@router.post("/generate-md")
def api_generate_email_md(db: Session = Depends(get_db)):
    """Generar archivos .md de todos los emails existentes en sus carpetas de caso.
    Esto permite que la IA lea los correos completos durante la extraccion."""
    from backend.email.gmail_monitor import save_existing_emails_as_md
    saved = save_existing_emails_as_md(db)
    return {"message": f"{saved} emails guardados como .md en carpetas de casos", "saved": saved}


@router.put("/{email_id}/ignore")
def api_ignore_email(email_id: int, db: Session = Depends(get_db)):
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email no encontrado")

    email.status = "IGNORADO"
    db.commit()
    return email.to_dict()
