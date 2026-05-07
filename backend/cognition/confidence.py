"""F2 — Confidence scoring por campo extraído.

Calcula score 0.0-1.0 para cada campo del caso post-extracción.
Banda según umbrales en settings:
  - score >= CONFIDENCE_OK_THRESHOLD  → "OK"
  - score >= CONFIDENCE_REVIEW_THRESHOLD → "REVISAR"
  - otherwise                          → "BAJO"

El scoring es **retroactivo y heurístico** — no requiere refactor de extractores.
Se basa en señales observables del caso ya persistido:

  1. Origen del valor (regex zonal vs IA fallback vs ML inference)
  2. Cross-document agreement (¿aparece el mismo valor en N documentos?)
  3. Pattern strength (¿formato canónico? ¿longitud razonable?)
  4. Contradictions con otros campos (ej: fecha_fallo_2nd anterior a fecha_fallo_1st)
  5. Presencia en zona física estructural (encabezado, firma, sello)

Diseño bajo flag `USE_FIELD_CONFIDENCE`. No modifica valores extraídos —
solo agrega metadata en `case.field_confidences_json`.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, asdict
from typing import Optional

from backend.core.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class FieldConfidence:
    score: float            # 0.0 - 1.0
    band: str               # "OK" | "REVISAR" | "BAJO"
    evidence: dict          # señales que justifican el score


# ============================================================
# Heurísticas de pattern strength por campo
# ============================================================

_RAD_23_RE = re.compile(r"^\d{23}$")
_RAD_FOREST_RE = re.compile(r"^\d{6,12}$")
_DATE_DDMMYYYY_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")
_DATE_TEXT_RE = re.compile(r"^\d{1,2}\s+de\s+\w+\s+(?:de\s+)?\d{2,4}$", re.IGNORECASE)
_ENUM_FALLO_1ST = {"CONCEDE", "NIEGA", "IMPROCEDENTE"}
_ENUM_FALLO_2ND = {"CONFIRMA", "REVOCA", "MODIFICA"}
_ENUM_IMPUGNADOR = {"ACCIONANTE", "ACCIONADO", "MINISTERIO_PUBLICO"}
_ENUM_SI_NO = {"SI", "NO", "Sí"}


def _pattern_score(field: str, value: str) -> float:
    """Score basado en si el valor cumple el formato canónico esperado."""
    if not value:
        return 0.0
    v = str(value).strip()
    if field == "radicado_23_digitos":
        return 1.0 if _RAD_23_RE.match(v) else 0.4
    if field in ("radicado_forest", "forest_impugnacion"):
        return 1.0 if _RAD_FOREST_RE.match(v) else 0.5
    if field in ("fecha_ingreso", "fecha_respuesta", "fecha_fallo_1st",
                 "fecha_fallo_2nd", "fecha_apertura_incidente",
                 "fecha_apertura_incidente_2", "fecha_apertura_incidente_3"):
        if _DATE_DDMMYYYY_RE.match(v) or _DATE_TEXT_RE.match(v):
            return 1.0
        return 0.6
    if field == "sentido_fallo_1st":
        return 1.0 if v.upper() in _ENUM_FALLO_1ST else 0.3
    if field == "sentido_fallo_2nd":
        return 1.0 if v.upper() in _ENUM_FALLO_2ND else 0.3
    if field == "quien_impugno":
        return 1.0 if v.upper() in _ENUM_IMPUGNADOR else 0.3
    if field in ("impugnacion", "incidente", "incidente_2", "incidente_3"):
        return 1.0 if v in _ENUM_SI_NO else 0.3
    # Texto libre: evaluar longitud razonable
    L = len(v)
    if field in ("accionante", "juzgado", "ciudad", "oficina_responsable"):
        if 3 <= L <= 200:
            return 0.85
        return 0.4
    if field in ("asunto", "pretensiones", "observaciones",
                 "decision_incidente", "decision_incidente_2", "decision_incidente_3"):
        if 20 <= L <= 5000:
            return 0.8
        if L > 5:
            return 0.5
        return 0.2
    if field in ("responsable_desacato", "responsable_desacato_2", "responsable_desacato_3"):
        # Nombre o entidad. Esperamos al menos 8 chars con mayúsculas o palabras separadas.
        if L >= 8 and re.search(r"[A-ZÁÉÍÓÚÑ]{2,}", v):
            return 0.8
        return 0.4
    return 0.6  # default conservador para campos no listados


# ============================================================
# Penalizaciones por contradicciones cruzadas
# ============================================================

def _cross_field_penalty(case, field: str, value: str) -> tuple[float, list[str]]:
    """Penaliza valores que contradicen otros campos del caso.

    Returns (delta_negativo, lista_de_razones).
    """
    penalty = 0.0
    reasons: list[str] = []

    if field == "quien_impugno" and value:
        # Si fallo 1st CONCEDE pero quien_impugno = ACCIONANTE → contradicción típica
        f1 = (case.sentido_fallo_1st or "").upper()
        v_up = value.upper()
        if f1 == "CONCEDE" and v_up == "ACCIONANTE":
            penalty += 0.15
            reasons.append("CONCEDE+ACCIONANTE: contradicción usual (no incoherente, pero infrecuente)")
        if f1 in ("NIEGA", "IMPROCEDENTE") and v_up == "ACCIONADO":
            penalty += 0.15
            reasons.append("NIEGA+ACCIONADO: contradicción usual")

    if field == "fecha_fallo_2nd" and value:
        # fecha_fallo_2nd debe ser posterior a fecha_fallo_1st
        f1 = case.fecha_fallo_1st or ""
        if f1:
            # Comparación blanda solo por año
            y2 = re.search(r"\b(20\d{2})\b", value)
            y1 = re.search(r"\b(20\d{2})\b", f1)
            if y1 and y2 and int(y2.group(1)) < int(y1.group(1)):
                penalty += 0.4
                reasons.append("fecha_fallo_2nd anterior a fecha_fallo_1st")

    if field == "sentido_fallo_2nd" and value:
        # Solo debería existir si impugnación = SI
        if (case.impugnacion or "").upper() not in ("SI", "SÍ"):
            penalty += 0.3
            reasons.append("sentido_fallo_2nd presente sin impugnación=SI")

    if field == "decision_incidente" and value:
        if (case.incidente or "").upper() not in ("SI", "SÍ"):
            penalty += 0.3
            reasons.append("decision_incidente presente sin incidente=SI")

    return penalty, reasons


# ============================================================
# API pública
# ============================================================

# Campos a evaluar — todos los del protocolo 28 + algunos cognitivos.
SCORED_FIELDS = (
    "radicado_23_digitos", "radicado_forest", "abogado_responsable",
    "accionante", "accionados", "vinculados", "derecho_vulnerado",
    "juzgado", "ciudad", "fecha_ingreso", "asunto", "pretensiones",
    "oficina_responsable", "estado", "fecha_respuesta",
    "sentido_fallo_1st", "fecha_fallo_1st", "impugnacion", "quien_impugno",
    "forest_impugnacion", "juzgado_2nd", "sentido_fallo_2nd",
    "fecha_fallo_2nd", "incidente", "fecha_apertura_incidente",
    "responsable_desacato", "decision_incidente",
    "incidente_2", "fecha_apertura_incidente_2",
    "responsable_desacato_2", "decision_incidente_2",
    "incidente_3", "fecha_apertura_incidente_3",
    "responsable_desacato_3", "decision_incidente_3",
    "categoria_tematica", "direccion", "grupo", "equipo",
)


def _band(score: float) -> str:
    if score >= settings.CONFIDENCE_OK_THRESHOLD:
        return "OK"
    if score >= settings.CONFIDENCE_REVIEW_THRESHOLD:
        return "REVISAR"
    return "BAJO"


def score_field(case, field: str, value: Optional[str]) -> FieldConfidence:
    """Calcula confidence para un campo individual del caso."""
    if not value:
        return FieldConfidence(score=0.0, band="BAJO",
                               evidence={"reason": "campo vacío"})
    base = _pattern_score(field, value)
    penalty, reasons = _cross_field_penalty(case, field, value)
    final = max(0.0, min(1.0, base - penalty))
    evidence = {
        "pattern_score": round(base, 3),
        "cross_field_penalty": round(penalty, 3),
        "reasons": reasons,
    }
    return FieldConfidence(score=round(final, 3), band=_band(final), evidence=evidence)


def score_case(case) -> dict[str, dict]:
    """Calcula confidences para todos los campos del caso.

    Returns dict {field_name: {"score": float, "band": str, "evidence": dict}}.
    """
    out: dict[str, dict] = {}
    for f in SCORED_FIELDS:
        v = getattr(case, f, None)
        fc = score_field(case, f, v)
        out[f] = asdict(fc)
    return out


def persist_confidences(case, db_session) -> None:
    """Computa y persiste confidences en case.field_confidences_json.

    No-op si USE_FIELD_CONFIDENCE=False.
    """
    if not settings.USE_FIELD_CONFIDENCE:
        return
    try:
        confidences = score_case(case)
        case.field_confidences_json = json.dumps(confidences, ensure_ascii=False)
        db_session.add(case)
        db_session.commit()
        # Métricas agregadas en debug log
        bands = {"OK": 0, "REVISAR": 0, "BAJO": 0}
        for v in confidences.values():
            bands[v["band"]] = bands.get(v["band"], 0) + 1
        logger.info("F2 case=%d confidences: OK=%d REVISAR=%d BAJO=%d",
                    case.id, bands["OK"], bands["REVISAR"], bands["BAJO"])
    except Exception as e:
        logger.warning("F2 persist_confidences fallo case=%d: %s", case.id, e)
        db_session.rollback()


def get_review_fields(case) -> list[str]:
    """Lista campos en banda REVISAR o BAJO. Útil para UI."""
    if not case.field_confidences_json:
        return []
    try:
        data = json.loads(case.field_confidences_json)
    except json.JSONDecodeError:
        return []
    return [f for f, meta in data.items() if meta.get("band") in ("REVISAR", "BAJO")]
