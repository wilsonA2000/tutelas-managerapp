"""Entropía de Shannon aplicada a casos jurídicos.

Cuantifica el desorden de un caso en términos de completitud y consistencia
de sus 28 campos. Caso ideal (todos los campos aplicables llenos con alta
confianza) → H ≈ 0. Caso caótico (muchos campos vacíos o inconsistentes) →
H alto.

Uso:
    from backend.cognition.entropy import entropy_of_case, entropy_of_db
    h = entropy_of_case(case)                # float bits
    report = entropy_of_db(session)          # dict con H global y por caso
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable


# ============================================================
# Mapeo de campo → estado
# ============================================================

# Campos del protocolo 28 que son SIEMPRE aplicables (identidad del caso)
ALWAYS_EXPECTED = {
    "radicado_23_digitos", "radicado_forest", "abogado_responsable",
    "accionante", "accionados", "derecho_vulnerado", "juzgado",
    "ciudad", "fecha_ingreso", "asunto", "pretensiones",
    "oficina_responsable", "observaciones",
}

# Campos aplicables solo bajo ciertas condiciones (para no contar N/A como "vacío")
CONDITIONAL_FIELDS = {
    "vinculados": lambda case: True,                                  # opcional en todos
    "estado": lambda case: True,
    "fecha_respuesta": lambda case: True,
    "sentido_fallo_1st": lambda case: bool(getattr(case, "fecha_fallo_1st", None) or
                                            getattr(case, "sentido_fallo_1st", None)),
    "fecha_fallo_1st": lambda case: bool(getattr(case, "fecha_fallo_1st", None) or
                                          getattr(case, "sentido_fallo_1st", None)),
    "impugnacion": lambda case: True,                                 # siempre SI/NO
    "quien_impugno": lambda case: (getattr(case, "impugnacion", "") or "").upper().startswith("S"),
    "forest_impugnacion": lambda case: (getattr(case, "impugnacion", "") or "").upper().startswith("S"),
    "juzgado_2nd": lambda case: (getattr(case, "impugnacion", "") or "").upper().startswith("S"),
    "sentido_fallo_2nd": lambda case: (getattr(case, "impugnacion", "") or "").upper().startswith("S"),
    "fecha_fallo_2nd": lambda case: (getattr(case, "impugnacion", "") or "").upper().startswith("S"),
    "incidente": lambda case: True,                                   # siempre SI/NO
    "fecha_apertura_incidente": lambda case: (getattr(case, "incidente", "") or "").upper().startswith("S"),
    "responsable_desacato": lambda case: (getattr(case, "incidente", "") or "").upper().startswith("S"),
    "decision_incidente": lambda case: (getattr(case, "incidente", "") or "").upper().startswith("S"),
}


# Estados discretos de un campo (con probabilidad implícita en el cálculo)
FIELD_STATES = (
    "filled_high",            # valor presente, confianza ≥0.85
    "filled_medium",          # valor presente, confianza 0.6-0.85
    "filled_low",              # valor presente, confianza <0.6
    "empty_expected",         # campo aplica pero no tenemos valor
    "empty_not_applicable",   # campo no aplica (ej. fallo_2nd sin impugnación)
    "inconsistent",            # contradice a otro campo del caso
)


# ============================================================
# Clasificación de estado por campo
# ============================================================

def _is_filled(value) -> bool:
    if value is None:
        return False
    s = str(value).strip()
    if not s:
        return False
    return s.lower() not in ("n/a", "no aplica", "-", "pendiente", "revision", "null", "none")


def _field_confidence(case, field: str) -> float:
    """Confianza heurística cuando no viene de un sistema explícito.

    En v5.5 la confianza por campo no está persistida en la DB. Usamos
    heurística: si el campo viene de regex fuerte (rad23 completo) → 0.9;
    si viene de cognición local → 0.75; si es IA (por los campos que solo
    IA llena) → 0.7; si es observaciones/narrativa → 0.65.
    """
    val = getattr(case, field, "") or ""
    if not _is_filled(val):
        return 0.0
    # Campos que típicamente vienen de regex (alta confianza)
    if field in ("radicado_23_digitos", "radicado_forest", "fecha_ingreso",
                 "fecha_fallo_1st", "fecha_fallo_2nd", "fecha_apertura_incidente",
                 "abogado_responsable", "ciudad", "juzgado", "juzgado_2nd",
                 "forest_impugnacion"):
        return 0.9
    # Campos típicamente de cognición local
    if field in ("accionante", "accionados", "vinculados", "derecho_vulnerado",
                 "asunto", "pretensiones", "impugnacion", "incidente"):
        return 0.75
    # Campos típicamente de IA
    if field in ("sentido_fallo_1st", "sentido_fallo_2nd", "quien_impugno",
                 "oficina_responsable", "decision_incidente", "responsable_desacato"):
        return 0.7
    # Observaciones y estado
    return 0.65


def _inconsistencies(case) -> set[str]:
    """Detecta contradicciones entre campos. Retorna nombres de campos inconsistentes."""
    bad: set[str] = set()
    imp = (getattr(case, "impugnacion", "") or "").upper()
    # Si impugnacion=NO pero hay datos de 2da instancia
    if imp.startswith("N"):
        for f in ("quien_impugno", "forest_impugnacion", "juzgado_2nd",
                  "sentido_fallo_2nd", "fecha_fallo_2nd"):
            if _is_filled(getattr(case, f, None)):
                bad.add(f)
    inc = (getattr(case, "incidente", "") or "").upper()
    # Si incidente=NO pero hay datos de desacato
    if inc.startswith("N"):
        for f in ("fecha_apertura_incidente", "responsable_desacato", "decision_incidente"):
            if _is_filled(getattr(case, f, None)):
                bad.add(f)
    # Si hay fallo 2nd pero no sentido_fallo_1st (contradicción lógica:
    # no puede haber 2da instancia sin 1ra instancia). La falta solo de
    # fecha_fallo_1st no es inconsistencia — es dato incompleto.
    if _is_filled(getattr(case, "sentido_fallo_2nd", None)) and \
       not _is_filled(getattr(case, "sentido_fallo_1st", None)):
        bad.add("sentido_fallo_1st")
    return bad


def _classify_field(case, field: str, inconsistent: set[str]) -> str:
    """Devuelve uno de FIELD_STATES para el campo dado."""
    val = getattr(case, field, "") or ""
    filled = _is_filled(val)

    if field in inconsistent:
        return "inconsistent"

    # ¿Es aplicable?
    if field in ALWAYS_EXPECTED:
        applies = True
    elif field in CONDITIONAL_FIELDS:
        applies = CONDITIONAL_FIELDS[field](case)
    else:
        applies = True

    if not filled:
        return "empty_expected" if applies else "empty_not_applicable"

    conf = _field_confidence(case, field)
    if conf >= 0.85:
        return "filled_high"
    if conf >= 0.6:
        return "filled_medium"
    return "filled_low"


# ============================================================
# Cálculo de entropía
# ============================================================

# Todos los campos que miramos para H
ALL_FIELDS = sorted(ALWAYS_EXPECTED | set(CONDITIONAL_FIELDS.keys()))


def shannon_entropy(counts: dict[str, int]) -> float:
    """H = -Σ p·log₂(p). Ignora estados con count=0."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    h = 0.0
    for n in counts.values():
        if n <= 0:
            continue
        p = n / total
        h -= p * math.log2(p)
    return h


@dataclass
class CaseEntropyReport:
    case_id: int
    folder_name: str
    processing_status: str
    state_counts: dict[str, int]
    entropy_bits: float
    inconsistent_fields: list[str]
    expected_empty_fields: list[str]


def entropy_of_case(case) -> CaseEntropyReport:
    """Calcula H para un caso y devuelve reporte detallado."""
    inconsistent = _inconsistencies(case)
    counts: dict[str, int] = {s: 0 for s in FIELD_STATES}
    expected_empty: list[str] = []
    for f in ALL_FIELDS:
        state = _classify_field(case, f, inconsistent)
        counts[state] += 1
        if state == "empty_expected":
            expected_empty.append(f)
    h = shannon_entropy(counts)
    return CaseEntropyReport(
        case_id=getattr(case, "id", -1),
        folder_name=getattr(case, "folder_name", "") or "",
        processing_status=getattr(case, "processing_status", "") or "",
        state_counts=counts,
        entropy_bits=round(h, 4),
        inconsistent_fields=sorted(inconsistent),
        expected_empty_fields=expected_empty,
    )


def entropy_of_db(cases: Iterable) -> dict:
    """Calcula H global del sistema sobre todos los casos."""
    reports = [entropy_of_case(c) for c in cases]
    completos = [r for r in reports if r.processing_status == "COMPLETO"]
    if not reports:
        return {"total_cases": 0, "mean_entropy": 0.0, "reports": []}

    mean_h_all = sum(r.entropy_bits for r in reports) / len(reports)
    mean_h_completos = (sum(r.entropy_bits for r in completos) / len(completos)
                        if completos else 0.0)

    # Agregado global de estados
    agg: dict[str, int] = {s: 0 for s in FIELD_STATES}
    for r in reports:
        for s, n in r.state_counts.items():
            agg[s] += n

    return {
        "total_cases": len(reports),
        "completos": len(completos),
        "mean_entropy_all": round(mean_h_all, 4),
        "mean_entropy_completos": round(mean_h_completos, 4),
        "aggregate_states": agg,
        "cases_with_inconsistencies": sum(1 for r in reports if r.inconsistent_fields),
        "total_inconsistencies": sum(len(r.inconsistent_fields) for r in reports),
        "worst_cases": [
            {"id": r.case_id, "folder": r.folder_name, "h": r.entropy_bits,
             "empty": len(r.expected_empty_fields), "inconsistent": len(r.inconsistent_fields)}
            for r in sorted(reports, key=lambda r: -r.entropy_bits)[:10]
        ],
        "reports": [r for r in reports],
    }
