"""Helpers de resolución de caso compartidos por las DOS rutas de ingesta (F0-A).

El monitor en vivo (`gmail_monitor.check_inbox`) y el script
(`scripts/ingest_from_gmail_v9.py`) deben resolver el caso de un correo con la MISMA
lógica para no crear casos que compiten (causa raíz RC-1 de los duplicados).

Este módulo NO reemplaza el matcher de scoring del monitor — solo aporta las dos piezas
que al monitor le faltaban:
  * F1  `adopt_shell`: adoptar un shell (rad23 NULL, mismo rad_corto) cuando llega el
        rad23 completo, en vez de crear un caso nuevo que lo duplicaría.
  * F2  `match_by_rad_corto` con desambiguación por MUNICIPIO del juzgado (clave para
        respuestas SED que solo traen rad_corto y nombran el juzgado).

Self-contained (solo depende de models + municipios_santander) para que tanto backend
como scripts lo importen sin ciclos.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.database.models import Case
from backend.agent.extractors.municipios_santander import (
    MUNICIPIOS_SANTANDER, _strip_accents as _muni_strip,
)


# ───────────────────────── radicado / nombre ─────────────────────────

def rad_corto_from_rad23(rad23: Optional[str]) -> str:
    """rad23 (>=21 díg.) → 'YYYY-NNNNN'. '' si no aplica."""
    d = re.sub(r"\D", "", rad23 or "")
    return f"{d[12:16]}-{d[16:21]}" if len(d) >= 21 else ""


def norm_accionante(s: Optional[str]) -> str:
    """Normaliza para comparar: sin acentos, MAYÚS, solo alfanum+espacio."""
    if not s:
        return ""
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Za-z0-9 ]", "", s).upper().strip()


# ───────────────────────── municipio del juzgado (F2) ─────────────────────────

_RE_JUZ_MUNI = re.compile(
    r"(?i)juzgado\b[^\n]{0,75}?\bde\s+([A-Za-záéíóúñÁÉÍÓÚÑ]+(?:\s+[A-Za-záéíóúñÁÉÍÓÚÑ]+){0,3})"
)


def extract_juzgado_municipio(text: str) -> Optional[str]:
    """Municipio del despacho de un 'JUZGADO ... DE <MUNICIPIO>', validado contra los
    87 municipios de Santander (prueba 1-3 palabras: 'PUENTE NACIONAL'). Normalizado."""
    if not text:
        return None
    for m in _RE_JUZ_MUNI.finditer(text[:3000]):
        words = _muni_strip(m.group(1)).split()
        for n in range(min(3, len(words)), 0, -1):
            name = " ".join(words[:n])
            if name in MUNICIPIOS_SANTANDER:
                return name
    return None


def case_municipio(c: Case) -> Optional[str]:
    """Municipio del juzgado de un Case: del campo `juzgado`, fallback a `ciudad`."""
    m = extract_juzgado_municipio(c.juzgado or "")
    if m:
        return m
    cu = _muni_strip(c.ciudad) if c.ciudad else ""
    return cu if cu in MUNICIPIOS_SANTANDER else None


# ───────────────────────── matching / adopción ─────────────────────────

def match_by_rad_corto(
    db: Session, rad_corto: str, *, juzgado_code: Optional[str] = None,
    accionante: str = "", municipio: Optional[str] = None,
) -> tuple[Optional[Case], str]:
    """Case por rad_corto en folder_name. Con homónimos year:seq (juzgados distintos)
    desambigua por MUNICIPIO del juzgado (F2), código de juzgado, o accionante. Si no se
    puede desambiguar → (None, ...) (conflar dos expedientes es peor que no asignar)."""
    cases = db.query(Case).filter(Case.folder_name.like(f"{rad_corto} %")).all()
    if not cases:
        return None, "no_match"
    if len(cases) == 1:
        return cases[0], "rad_corto_unique"
    if municipio:
        hits = [c for c in cases if case_municipio(c) == municipio]
        if len(hits) == 1:
            return hits[0], "rad_corto+municipio"
    if juzgado_code:
        jz = [c for c in cases if c.radicado_23_digitos and len(c.radicado_23_digitos) >= 12
              and re.sub(r"\D", "", c.radicado_23_digitos)[5:12] == juzgado_code]
        if len(jz) == 1:
            return jz[0], "rad_corto+juzgado"
    if accionante and len(accionante) >= 6:
        import difflib
        a = norm_accionante(accionante)
        scored = sorted(cases, key=lambda c: difflib.SequenceMatcher(
            None, a, norm_accionante(c.accionante)).ratio(), reverse=True)
        r1 = difflib.SequenceMatcher(None, a, norm_accionante(scored[0].accionante)).ratio()
        r2 = difflib.SequenceMatcher(None, a, norm_accionante(scored[1].accionante)).ratio() if len(scored) > 1 else 0.0
        if r1 >= 0.80 and r1 - r2 >= 0.15:
            return scored[0], "rad_corto+accionante"
    return None, "rad_corto_ambiguous_unresolved"


def adopt_shell(db: Session, rad23: str, accionante: str = "") -> Optional[Case]:
    """F1 (RC-2): adopta un shell (rad23 NULL, mismo rad_corto) cuando llega el rad23
    completo, en vez de crear un caso nuevo que lo duplicaría.

    Seguro: solo si hay EXACTAMENTE 1 shell con ese rad_corto; en cluster de conflación
    (otro caso rad23 mismo rad_corto pero rad21 distinto) exige accionante compatible.
    Fija el rad23 en el shell (deja de ser shell) y devuelve el Case (None si no adopta).
    """
    rad_corto = rad_corto_from_rad23(rad23)
    if not rad_corto:
        return None
    rad21 = re.sub(r"\D", "", rad23)[:21]
    shells = db.query(Case).filter(
        or_(Case.radicado_23_digitos.is_(None), Case.radicado_23_digitos == ""),
        Case.folder_name.like(f"{rad_corto} %"),
    ).all()
    if len(shells) != 1:
        return None
    shell = shells[0]
    others = db.query(Case).filter(
        Case.folder_name.like(f"{rad_corto} %"),
        Case.radicado_23_digitos.isnot(None), Case.radicado_23_digitos != "",
    ).all()
    conflacion = any(
        re.sub(r"\D", "", c.radicado_23_digitos or "")[:21] != rad21
        for c in others if len(re.sub(r"\D", "", c.radicado_23_digitos or "")) >= 21
    )
    if conflacion:
        a, b = norm_accionante(accionante), norm_accionante(shell.accionante)
        if not (a and b and a == b):
            return None
    shell.radicado_23_digitos = rad23
    if accionante and (not shell.accionante or shell.accionante in (
            "(sin accionante)", "(sin radicado)", "(tutela origen no ingestada)")):
        shell.accionante = accionante
    db.flush()
    return shell
