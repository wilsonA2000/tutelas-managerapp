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

# lookbehind/lookahead de dígito (no `\b`): así matchea aunque el rad venga pegado a
# `_` o letras en el filename (p.ej. "Fallo_680013333014-2026-00032-00"), pero NUNCA
# como subcadena de un número más largo.
_RAD23 = re.compile(
    r"(?<!\d)\d{5}[\s.\-]?\d{2}[\s.\-]?\d{2}[\s.\-]?\d{3}[\s.\-]?\d{4}[\s.\-]?\d{5}[\s.\-]?\d{2}(?!\d)"
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

# Señales de remisión por competencia / reparto: una tutela que cambia de juzgado
# (y por ende de rad) por competencia NO es contaminación — es la MISMA tutela con
# un rad anterior. Ej.: 2026-00122 (Bucaramanga) → remitida → 2026-00137 (Floridablanca).
_REPARTO_RE = re.compile(
    r"(REMIT\w*\s+(?:LA\s+)?ACCI[ÓO]N|POR\s+COMPETENCIA|ACTA\s+(?:DE\s+)?REPARTO|"
    r"REMITE\s+POR\s+FALTA\s+DE\s+COMPETENCIA|REPARTO\s+N[°º])",
    re.I,
)


def _is_reparto_doc(filename: str | None, text: str | None) -> bool:
    """True si el doc es/contiene una remisión por competencia o acta de reparto
    (vincula legítimamente dos radicados de la MISMA tutela en juzgados distintos)."""
    blob = (filename or "") + " " + (text or "")[:3000]
    return bool(_REPARTO_RE.search(blob))


def _expected_juzgado(crad: str | None, own_rads: list[str]) -> tuple[str | None, str]:
    """Identidad esperada del caso: el juzgado (12 díg) del rad23 del caso si existe;
    si no (rad23 NULL — 16% de los casos), el juzgado MAYORITARIO entre los rads
    propios de los docs. Devuelve (juzgado_esperado, fuente)."""
    if crad:
        return _juzgado(crad), "case_rad23"
    if own_rads:
        from collections import Counter
        juzgados = Counter(_juzgado(r) for r in own_rads)
        ranked = juzgados.most_common(2)
        maj, n = ranked[0]
        # EMPATE (p.ej. 2 docs de un juzgado y 2 de otro) → ambiguo, NO adivinar:
        # marcar mal la "otra mitad" sería peor que no chequear.
        if len(ranked) > 1 and ranked[1][1] == n:
            return None, "indeterminable_empate"
        # mayoría estricta requiere consenso (≥2 docs, o un único juzgado presente)
        if n >= 2 or len(juzgados) == 1:
            return maj, "mayoria_docs"
    return None, "indeterminable"


def check_folder_consistency(db: Session, case_id: int) -> dict:
    """Returns {clean: bool, n_issues: int, issues: [...]}.
    Cada issue: {doc_id, filename, tipo, detalle}."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return {"clean": True, "n_issues": 0, "issues": [], "error": "caso no existe"}

    crad = (case.radicado_23_digitos or "").strip()
    crad = crad if len(crad) == 23 else None
    docs = db.query(Document).filter(Document.case_id == case_id).all()

    # rad propio de cada doc (para identidad esperada y para el chequeo)
    own = {d.id: _own_rad(d.filename, d.extracted_text) for d in docs}
    exp_juzgado, exp_src = _expected_juzgado(crad, [r for r in own.values() if r])

    issues: list[dict] = []
    for d in docs:
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
        if not exp_juzgado:
            continue  # identidad del caso indeterminable → no se puede chequear
        orad = own[d.id]
        if orad and _juzgado(orad) != exp_juzgado:
            # excluir escalamiento legítimo a 2da (recurso -01 vs -00)
            if crad and _recurso(orad) == "01" and _recurso(crad) == "00":
                continue
            # excluir remisión por competencia (misma tutela, rad anterior en otro juzgado)
            if _is_reparto_doc(d.filename, d.extracted_text):
                continue
            misma_rc = crad is not None and orad[12:21] == crad[12:21]
            ref = crad or f"juzgado mayoritario {exp_juzgado}"
            issues.append({
                "doc_id": d.id, "filename": d.filename,
                "tipo": "CONFLACION" if misma_rc else "RAD_AJENO",
                "detalle": f"radicado propio {orad} (juzgado {orad[:5]}) ≠ {ref} [identidad: {exp_src}]",
                "doc_rad": orad,
            })

    return {"clean": len(issues) == 0, "n_issues": len(issues), "issues": issues}
