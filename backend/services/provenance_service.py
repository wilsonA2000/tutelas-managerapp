"""Provenance service v4.8: paquetes email inmutables.

Patron "hermanos viajan juntos": si un Document tiene email_id != NULL,
todos los otros Documents con el mismo email_id son sus HERMANOS y deben
moverse juntos al reasignar entre casos.

Funciones puras (sin side effects): solo consultan, no mutan.
Los mutadores viven en sibling_mover.py.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.database.models import Document, Email


def get_siblings(db: Session, doc_id: int) -> list[Document]:
    """Devuelve los Documents hermanos del mismo email_package.

    Incluye al propio doc en la lista (un doc siempre es hermano de si mismo).

    Args:
        db: sesion SQLAlchemy
        doc_id: ID del documento a consultar

    Returns:
        Lista de Documents con el mismo email_id. Lista vacia si doc no existe
        o si email_id is None (doc legacy sin procedencia).
    """
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc or doc.email_id is None:
        return []

    return (
        db.query(Document)
        .filter(Document.email_id == doc.email_id)
        .order_by(Document.id)
        .all()
    )


def get_package_by_email(db: Session, email_id: int) -> dict[str, Any] | None:
    """Devuelve el paquete email completo: Email + todos sus Documents hijos.

    Args:
        db: sesion SQLAlchemy
        email_id: ID del Email

    Returns:
        dict con {email, documents, case_id, count} o None si no existe.
    """
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        return None

    documents = (
        db.query(Document)
        .filter(Document.email_id == email_id)
        .order_by(Document.id)
        .all()
    )

    return {
        "email": email,
        "documents": documents,
        "case_id": email.case_id,
        "count": len(documents),
    }


def has_siblings(db: Session, doc_id: int) -> bool:
    """True si el doc tiene al menos 1 hermano (mas alla de si mismo)."""
    siblings = get_siblings(db, doc_id)
    return len(siblings) > 1


def list_packages_in_case(db: Session, case_id: int) -> list[dict[str, Any]]:
    """Lista todos los paquetes email de un caso (para vista timeline).

    Retorna solo los emails que tienen al menos 1 Document vinculado,
    ordenados por fecha de recepcion descendente.
    """
    # DOC-CÉNTRICO (v9): un email "pertenece" a este caso si tiene ≥1 documento EN ESTE
    # CASO, sin importar el `Email.case_id` (lo fija el matcher y puede estar desfasado del
    # placement por contenido de la v9; además un email puede abarcar varios casos). Antes
    # filtraba por Email.case_id → la pestaña Correos salía vacía cuando los docs estaban
    # bien (por contenido) pero el email apuntaba a otro caso.
    email_ids = [
        row[0] for row in db.query(Document.email_id)
        .filter(Document.case_id == case_id, Document.email_id.isnot(None))
        .distinct().all()
    ]
    emails = (
        db.query(Email)
        .filter(Email.id.in_(email_ids))
        .order_by(Email.date_received.desc().nullslast())
        .all()
    ) if email_ids else []

    packages = []
    for em in emails:
        docs = (
            db.query(Document)
            .filter(Document.email_id == em.id, Document.case_id == case_id)
            .order_by(Document.id)
            .all()
        )
        if docs:  # solo paquetes no vacios
            packages.append({
                "email_id": em.id,
                "message_id": em.message_id,
                "subject": em.subject or "",
                "sender": em.sender or "",
                "date_received": em.date_received,
                "document_count": len(docs),
                "documents": [d.to_dict() for d in docs],
            })
    return packages


def count_orphan_documents(db: Session) -> int:
    """Cuenta documentos sin email_id (legacy, sin procedencia).

    Util para metricas del backfill y reportes de cleanup.
    """
    return db.query(Document).filter(Document.email_id.is_(None)).count()


def count_linked_documents(db: Session) -> int:
    """Cuenta documentos con email_id asignado."""
    return db.query(Document).filter(Document.email_id.isnot(None)).count()
