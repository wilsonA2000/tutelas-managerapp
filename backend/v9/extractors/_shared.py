"""Helpers cross-cutting del motor de extracción v9 (usados por varios dominios).

Extraídos de field_extractor.py en la de-sobreingeniería F6. Son autocontenidos
(solo stdlib + modelos ORM) → sin ciclo de imports. field_extractor.py los re-importa
y re-exporta para preservar el contrato público (tests/scripts importan estos nombres).
"""
from __future__ import annotations

import os
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


# `_best_claim_text` elige el doc que mejor refleja el RECLAMO original del accionante
# (no la etapa procesal posterior). Compartido por los semánticos (derecho/asunto) y
# pipeline.py → vive en _shared.
_CLAIM_DEM_MARK = [r"BAJO LA GRAVEDAD DEL JURAMENTO", r"NO HE PRESENTADO OTRA",
                   r"PRETENSIONES", r"\bHECHOS\b", r"JURAMENTO", r"ACCION DE TUTELA",
                   r"instaur", r"interpong", r"agente oficios", r"en mi calidad de"]
# Head que delata una etapa procesal POSTERIOR (no la demanda original).
_CLAIM_NOT_DEMANDA = re.compile(
    r"INCIDENTE DE DESACATO|\bAUTO\b|INFORME DE CUMPLIMIENTO|VISITA OCULAR|"
    r"REQUERIMIENTO PREVIO|DECIDE SANCI|APERTURA.{0,8}PRUEBAS|NO SANCIONA", re.I)


def _best_claim_text(db: Session, case: Case,
                     max_chars: int = int(os.getenv("V9_LLM_FIELD_CAP", "20000"))) -> tuple[str, bool]:
    """Devuelve (texto, es_demanda_real) del doc que mejor refleja el reclamo
    original del accionante. Penaliza autos/desacato/informes (etapa procesal).
    `es_demanda_real=False` ⇒ no hay demanda fiable → el caller debe ser honesto
    (SIN_DETERMINAR/flag) en vez de clasificar una etapa procesal."""
    scored: list[tuple[int, str]] = []
    for d in db.query(Document).filter(Document.case_id == case.id).all():
        t = d.extracted_text if d.extracted_text else (_read_doc_text(d) or "")
        if len(t) < 250:
            continue
        head = t[:6000]
        sc = sum(2 for m in _CLAIM_DEM_MARK if re.search(m, head, re.I))
        dt = d.doc_type or "OTRO"
        if dt in ("DEMANDA_TUTELA", "ANEXO_DEMANDA"):
            sc += 2
        if dt == "AUTO_ADMISORIO":
            sc += 3  # el auto admisorio reenuncia el reclamo original limpio
        if dt in ("RESPUESTA", "DOCX_RESPUESTA", "RESPUESTA_SED"):
            sc -= 4   # defensa de la SED, NO el reclamo del accionante
        if _CLAIM_NOT_DEMANDA.search(t[:1400]):
            sc -= 6   # head de etapa procesal posterior → NO es la demanda
        scored.append((sc, t[:max_chars]))
    if not scored:
        return "", False
    scored.sort(key=lambda x: (-x[0], -len(x[1])))
    sc, t = scored[0]
    return t, sc >= 4
