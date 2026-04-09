"""Indexador de conocimiento: agrega contenido de múltiples fuentes al Knowledge Base."""

import hashlib
import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.knowledge.models import KnowledgeEntry

logger = logging.getLogger("tutelas.knowledge")


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def index_document(db: Session, case_id: int, filename: str, content: str, source_type: str = "pdf"):
    """Indexar un documento extraído (PDF, DOCX, etc.)."""
    if not content or len(content.strip()) < 10:
        return
    h = _content_hash(content)
    existing = db.query(KnowledgeEntry).filter(
        KnowledgeEntry.case_id == case_id,
        KnowledgeEntry.content_hash == h,
    ).first()
    if existing:
        return  # Already indexed
    entry = KnowledgeEntry(
        case_id=case_id,
        source_type=source_type,
        source_name=filename,
        content=content[:50000],  # Limit to 50K chars
        content_hash=h,
    )
    db.add(entry)
    db.commit()


def index_email(db: Session, case_id: int | None, email_id: int, subject: str, body: str, sender: str = ""):
    """Indexar un email."""
    content = f"Subject: {subject}\nFrom: {sender}\n\n{body or ''}"
    if len(content.strip()) < 10:
        return
    h = _content_hash(content)
    existing = db.query(KnowledgeEntry).filter(
        KnowledgeEntry.content_hash == h,
    ).first()
    if existing:
        return
    entry = KnowledgeEntry(
        case_id=case_id,
        source_type="email",
        source_name=f"email_{email_id}_{subject[:50]}",
        content=content[:50000],
        content_hash=h,
    )
    db.add(entry)
    db.commit()


def index_case_fields(db: Session, case_id: int, fields: dict):
    """Indexar campos de un caso como conocimiento."""
    content_parts = []
    for key, val in fields.items():
        if val and str(val).strip():
            content_parts.append(f"{key}: {val}")
    if not content_parts:
        return
    content = "\n".join(content_parts)
    # Remove old db_field entry for this case
    db.query(KnowledgeEntry).filter(
        KnowledgeEntry.case_id == case_id,
        KnowledgeEntry.source_type == "db_field",
    ).delete()
    entry = KnowledgeEntry(
        case_id=case_id,
        source_type="db_field",
        source_name=f"case_{case_id}_fields",
        content=content,
        content_hash=_content_hash(content),
    )
    db.add(entry)
    db.commit()


def index_md_file(db: Session, case_id: int | None, filename: str, content: str, source_type: str = "email_md"):
    """Indexar un archivo .md (Email_*.md o Cowork .md)."""
    if not content or len(content.strip()) < 10:
        return
    h = _content_hash(content)
    existing = db.query(KnowledgeEntry).filter(
        KnowledgeEntry.content_hash == h,
    ).first()
    if existing:
        return
    entry = KnowledgeEntry(
        case_id=case_id,
        source_type=source_type,
        source_name=filename,
        content=content[:50000],
        content_hash=h,
    )
    db.add(entry)
    db.commit()


def index_case_incremental(db: Session, case_id: int):
    """Indexar todos los documentos de un caso que no estan en KB (incremental)."""
    from backend.database.models import Case, Document
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return 0
    indexed = 0
    for doc in case.documents:
        if doc.extracted_text and len(doc.extracted_text) > 100:
            ext = (doc.filename or "").rsplit(".", 1)[-1].lower() if doc.filename else ""
            source_type = "email_md" if doc.filename and doc.filename.startswith("Email_") else ext or "pdf"
            h = _content_hash(doc.extracted_text)
            existing = db.query(KnowledgeEntry).filter(
                KnowledgeEntry.case_id == case_id,
                KnowledgeEntry.content_hash == h,
            ).first()
            if not existing:
                entry = KnowledgeEntry(
                    case_id=case_id,
                    source_type=source_type,
                    source_name=doc.filename,
                    content=doc.extracted_text[:50000],
                    content_hash=h,
                )
                db.add(entry)
                indexed += 1
    if indexed > 0:
        db.commit()
    return indexed


def rebuild_index(db: Session, base_dir: str):
    """Reconstruir todo el índice desde cero.
    Lee documentos extraídos de la DB, emails, y archivos .md del disco."""
    from backend.database.models import Case, Document, Email

    logger.info("Rebuilding knowledge index...")

    # Clear existing entries
    db.query(KnowledgeEntry).delete()
    db.commit()
    count = 0

    # 1. Index all documents with extracted text
    docs = db.query(Document).filter(Document.extracted_text.isnot(None)).all()
    for doc in docs:
        if doc.extracted_text and len(doc.extracted_text.strip()) > 10:
            index_document(db, doc.case_id, doc.filename, doc.extracted_text,
                         source_type="docx" if doc.filename.endswith(".docx") else "pdf")
            count += 1

    # 2. Index all emails
    emails = db.query(Email).all()
    for em in emails:
        index_email(db, em.case_id, em.id, em.subject or "", em.body_preview or "", em.sender or "")
        count += 1

    # 3. Index case fields
    cases = db.query(Case).all()
    for case in cases:
        fields = {}
        for col in ["accionante", "accionados", "vinculados", "juzgado", "ciudad",
                     "derecho_vulnerado", "asunto", "pretensiones", "observaciones",
                     "radicado_23_digitos", "radicado_forest", "abogado_responsable"]:
            val = getattr(case, col, None)
            if val:
                fields[col] = val
        if case.folder_name:
            fields["folder_name"] = case.folder_name
        if fields:
            index_case_fields(db, case.id, fields)
            count += 1

    # 4. Index Email_*.md files from case folders
    base = Path(base_dir)
    md_count = 0
    for case in cases:
        if not case.folder_name:
            continue
        folder = base / case.folder_name
        if not folder.exists():
            continue
        for md_file in folder.glob("Email_*.md"):
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                index_md_file(db, case.id, md_file.name, content, "email_md")
                md_count += 1
            except Exception:
                pass

    count += md_count
    logger.info(f"Knowledge index rebuilt: {count} entries indexed ({md_count} .md files)")
    return count
