"""Chequeo de consistencia de carpeta — gate ANTES de extraer.

Regla operativa (Wilson, 2026-05-20): primero DEPURAR la carpeta, después extraer.
Extraer una carpeta con documentos sin depurar produce campos contaminados (p.ej. la
observación de un caso narrando la tutela de OTRO juzgado mezclada por rad corto).

Detecta inconsistencias que la verificación normal (basada en rad corto) NO ve:
- docs marcados NO_PERTENECE / SOSPECHOSO / PENDIENTE_OCR (verificación previa)
- CONFLACIÓN cross-juzgado: el radicado PROPIO del doc (filename o encabezado
  "RADICADO:") tiene un juzgado (primeros 12 dígitos) distinto al del caso, aunque
  comparta el rad corto. Es la firma de las carpetas mezcladas (Lizzy/Oiba/Onzaga).
"""
from __future__ import annotations
import re
from sqlalchemy.orm import Session
from backend.database.models import Case, Document

_RAD23 = re.compile(
    r"\b\d{5}[\s.\-]?\d{2}[\s.\-]?\d{2}[\s.\-]?\d{3}[\s.\-]?\d{4}[\s.\-]?\d{5}[\s.\-]?\d{2}\b"
)


def _norm23(s: str | None) -> str | None:
    d = re.sub(r"\D", "", s or "")
    return d if len(d) == 23 else None


def _own_rad(filename: str | None, text: str | None) -> str | None:
    """Radicado PROPIO del documento: del filename, o de la 1ª línea 'RADICAD[OÓ]:' del
    encabezado. NO de citas dentro del cuerpo (vinculaciones, jurisprudencia)."""
    for m in _RAD23.finditer(filename or ""):
        r = _norm23(m.group(0))
        if r:
            return r
    head = (text or "")[:3000]
    for m in re.finditer(r"RADICAD[OÓ]N?\s*[:#]?\s*([\d\s.\-]{20,40})", head, re.I):
        r = _norm23(m.group(1))
        if r:
            return r
    return None


def _juzgado(rad: str) -> str:
    return rad[:12]


def _recurso(rad: str) -> str:
    return rad[21:23]


# verificaciones que bloquean extracción hasta resolverse
_DIRTY_VERIF = {"NO_PERTENECE", "SOSPECHOSO", "PENDIENTE_OCR"}


def check_folder_consistency(db: Session, case_id: int) -> dict:
    """Returns {clean: bool, n_issues: int, issues: [...]}.
    Cada issue: {doc_id, filename, tipo, detalle}."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return {"clean": True, "n_issues": 0, "issues": [], "error": "caso no existe"}

    crad = (case.radicado_23_digitos or "").strip()
    crad = crad if len(crad) == 23 else None
    issues: list[dict] = []

    for d in db.query(Document).filter(Document.case_id == case_id).all():
        v = (d.verificacion or "").upper()
        if v in _DIRTY_VERIF:
            issues.append({
                "doc_id": d.id, "filename": d.filename, "tipo": v,
                "detalle": d.verificacion_detalle or "",
            })
            continue  # ya marcado; no duplicar con conflación
        if v == "OK":
            continue  # confirmado que pertenece (verificación o decisión humana) → no flaggear
        # conflación cross-juzgado (lo que la verificación por rad corto no ve)
        if crad:
            orad = _own_rad(d.filename, d.extracted_text)
            if orad and orad != crad and _juzgado(orad) != _juzgado(crad):
                # excluir escalamiento legítimo a 2da (recurso -01 vs -00, juzgado superior)
                if _recurso(orad) == "01" and _recurso(crad) == "00":
                    continue
                misma_rc = orad[12:21] == crad[12:21]
                issues.append({
                    "doc_id": d.id, "filename": d.filename,
                    "tipo": "CONFLACION" if misma_rc else "RAD_AJENO",
                    "detalle": f"radicado propio {orad} (juzgado {orad[:5]}) ≠ caso {crad} (juzgado {crad[:5]})",
                    "doc_rad": orad,
                })

    return {"clean": len(issues) == 0, "n_issues": len(issues), "issues": issues}
