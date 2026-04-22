"""v5.2 — Folder Correlator: Etapa 5 del análisis forense.

Correlaciona archivos de una carpeta antes de procesarlos. Detecta:
- Series numéricas (001_, 002_, 003_) → mismo caso
- Anexos huérfanos (sin texto) → heredan del escrito principal
- Múltiples accionantes en carpeta → casos mezclados
"""

import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

from backend.services.forensic_analyzer import analyze_document, DocumentAnalysis


def detect_series_prefix(filenames: list[str]) -> dict[str, list[str]]:
    """Agrupa archivos por prefijo de serie numérica (001_, 002_, 003_)."""
    series = defaultdict(list)
    for fn in filenames:
        m = re.match(r"^(\d{1,3})[_.\s]+(.+)$", fn)
        if m:
            # Extraer solo el sufijo estructural (sin extensión ni variantes)
            suffix = re.sub(r"\.[a-z0-9]+$", "", m.group(2))
            series[f"serie_{len(m.group(1))}dig"].append(fn)
    return dict(series)


def correlate_folder(folder_path: Path | str) -> dict:
    """Analiza todos los archivos de una carpeta y decide agrupación.

    Returns:
        {
            "groups": [list[list[DocumentAnalysis]]],   # cada grupo = 1 caso
            "accionantes_detected": set[str],
            "rad23_detected": set[str],
            "recommendation": str  # "SINGLE_CASE" | "MULTIPLE_CASES" | "NEEDS_REVIEW"
        }
    """
    path = Path(folder_path)
    if not path.is_dir():
        return {"error": "no es directorio"}

    files = [f for f in path.iterdir() if f.is_file()
             and f.suffix.lower() in (".pdf", ".docx", ".doc", ".md", ".txt")]

    # Analizar cada archivo
    analyses = [analyze_document(f) for f in files]

    # Recolectar firmas
    accionantes = set()
    rad23s = set()
    ccs = set()
    for a in analyses:
        if a.accionante:
            accionantes.add(a.accionante)
        if a.rad23:
            rad23s.add(a.rad23)
        if a.cc_accionante:
            ccs.add(a.cc_accionante)

    # Detectar series
    series_info = detect_series_prefix([a.filename for a in analyses])

    # Heurística de agrupación
    groups = []
    if not analyses:
        return {"groups": [], "accionantes_detected": set(), "rad23_detected": set(),
                "recommendation": "EMPTY"}

    if len(rad23s) == 1:
        groups = [analyses]
        recommendation = "SINGLE_CASE_BY_RAD23"
    elif len(ccs) == 1 and len(accionantes) <= 2:  # tolera variaciones tildes
        groups = [analyses]
        recommendation = "SINGLE_CASE_BY_CC"
    elif len(accionantes) == 1:
        groups = [analyses]
        recommendation = "SINGLE_CASE_BY_ACCIONANTE"
    elif series_info and len(accionantes) <= 1:
        groups = [analyses]  # todos en una serie con o sin accionante único
        recommendation = "SINGLE_CASE_BY_SERIES"
    elif len(accionantes) >= 2:
        # Agrupar por accionante
        by_acc = defaultdict(list)
        sin_acc = []
        for a in analyses:
            if a.accionante:
                by_acc[a.accionante].append(a)
            else:
                sin_acc.append(a)
        # Los sin_acc van al grupo con más archivos (heurística)
        groups = list(by_acc.values())
        if sin_acc and groups:
            groups[max(range(len(groups)), key=lambda i: len(groups[i]))].extend(sin_acc)
        elif sin_acc:
            groups.append(sin_acc)
        recommendation = "MULTIPLE_CASES"
    else:
        groups = [analyses]
        recommendation = "NEEDS_REVIEW"

    return {
        "folder": str(path),
        "file_count": len(analyses),
        "groups": groups,
        "accionantes_detected": list(accionantes),
        "rad23_detected": list(rad23s),
        "cc_detected": list(ccs),
        "series_info": series_info,
        "recommendation": recommendation,
    }


def find_case_for_group(db, group: list[DocumentAnalysis]) -> Optional[dict]:
    """Busca caso existente en DB que coincida con las firmas del grupo.

    Returns: {"case_id": int, "match_type": str, "confidence": str} o None.
    """
    from backend.database.models import Case
    from sqlalchemy import or_

    # Recolectar firmas del grupo
    rad23s = set()
    ccs = set()
    accionantes = set()
    for a in group:
        if a.rad23: rad23s.add(a.rad23)
        if a.cc_accionante: ccs.add(a.cc_accionante)
        if a.accionante: accionantes.add(a.accionante)

    # Prioridad 1: rad23 exacto
    if rad23s:
        for r23 in rad23s:
            digits = re.sub(r"\D", "", r23)[:20]
            if len(digits) >= 18:
                cand = db.query(Case).filter(
                    Case.processing_status != "DUPLICATE_MERGED",
                    Case.radicado_23_digitos.isnot(None),
                ).all()
                for c in cand:
                    c_d = re.sub(r"\D", "", c.radicado_23_digitos or "")
                    if len(c_d) >= 18 and c_d[:20] == digits:
                        return {"case_id": c.id, "match_type": "rad23", "confidence": "ALTA"}

    # Prioridad 2: CC (exacto)
    if ccs:
        for cc in ccs:
            cand = db.query(Case).filter(
                Case.processing_status != "DUPLICATE_MERGED",
                or_(
                    Case.observaciones.like(f"%{cc}%"),
                    Case.accionante.like(f"%{cc}%"),
                ),
            ).first()
            if cand:
                return {"case_id": cand.id, "match_type": "cc", "confidence": "ALTA"}

    # Prioridad 3: accionante ≥2 tokens
    for acc in accionantes:
        tokens = [t for t in acc.split() if len(t) >= 4]
        if len(tokens) < 2:
            continue
        cand = db.query(Case).filter(
            Case.processing_status != "DUPLICATE_MERGED",
            Case.accionante.isnot(None),
        ).all()
        for c in cand:
            c_acc = (c.accionante or "").upper()
            matches = sum(1 for t in tokens if t in c_acc)
            if matches >= 2:
                return {"case_id": c.id, "match_type": "accionante_tokens",
                        "confidence": "MEDIA"}

    return None
