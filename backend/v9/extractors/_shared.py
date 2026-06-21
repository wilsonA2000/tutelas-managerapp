"""Helpers cross-cutting del motor de extracción v9 (usados por varios dominios).

Extraídos de field_extractor.py en la de-sobreingeniería F6. Son autocontenidos
(solo stdlib + modelos ORM) → sin ciclo de imports. field_extractor.py los re-importa
y re-exporta para preservar el contrato público (tests/scripts importan estos nombres).
"""
from __future__ import annotations

import re
import unicodedata as _ud
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from backend.database.models import Case, Document, Email


def _read_doc_text(doc: Document) -> str:
    """Devuelve el texto del doc. Para .md lee del disco; para PDF/DOCX usa extracted_text."""
    if doc.doc_type in ("EMAIL_JUDICIAL", "EMAIL_INTERNO") or (doc.filename or "").endswith(".md"):
        p = Path(doc.file_path) if doc.file_path else None
        if p and p.exists():
            try:
                return p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                return ""
        return ""
    return doc.extracted_text or ""


def _emails_chronological(db: Session, case_id: int) -> list[Email]:
    """Emails del case ordenados del más antiguo al más reciente."""
    return (
        db.query(Email)
        .filter(Email.case_id == case_id)
        .order_by(Email.date_received.asc())
        .all()
    )


def _rad_year(case: Case) -> Optional[int]:
    """Año del radicado de 23 dígitos (chars 12-15) — usado como cota de cordura
    para las fechas (el auto/admisión cae el mismo año o ±1 del radicado)."""
    rad = getattr(case, "radicado_23_digitos", None) or ""
    rad = re.sub(r"\D", "", rad)
    if len(rad) >= 16:
        try:
            y = int(rad[12:16])
            if 2018 <= y <= 2030:
                return y
        except ValueError:
            pass
    return None


def _fold(s: str) -> str:
    """minúsculas + sin tildes (para matching robusto de keywords)."""
    s = _ud.normalize("NFKD", s)
    return "".join(c for c in s if not _ud.combining(c)).lower()
