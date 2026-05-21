"""Etapa 6 — Persistencia con tracking de fuente.

Escribe `ExtractedFields` al `Case` ORM existente. Por cada campo escrito,
registra en `field_sources_json` de qué etapa vino. Esto permite que la UI
muestre el origen ("regex" / "excel" / "llm") y la auditoría sea trivial.

NO toca campos que v9 no maneja (ej. `direccion`, `grupo`, `equipo` en SED_ORG
los maneja `cognition/cognitive_persist.py` v8 — los dejamos intactos para no
romper compatibilidad).

Modos:
  - dry_run=True (default): no escribe a DB. Devuelve el diff que escribiría.
  - dry_run=False: aplica cambios y hace commit.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from backend.v9.types import ExtractedFields, FieldSource
from backend.cognition.folder_renamer import normalize_homoglyphs

logger = logging.getLogger("tutelas.v9.persist")


# F7 (2026-05-21): cota de año por campo fecha, relativa al año del rad (= año de radicación
# de la tutela). Ninguna actuación procesal antecede a la radicación (lo más bajo es +0).
# Mata el bug recurrente del extractor que toma fechas CITADAS (Decreto 2002, sentencia
# 2024 en un caso 2026, etc.) como fecha de fallo/respuesta → fecha_fallo < ingreso, año off.
_DATE_YEAR_BOUNDS: dict[str, tuple[int, int]] = {
    "fecha_ingreso":               (0, 1),
    "fecha_fallo_1st":             (0, 1),
    "fecha_respuesta":             (0, 1),
    "fecha_fallo_2nd":             (0, 2),
    "fecha_apertura_incidente":    (0, 3),
    "fecha_apertura_incidente_2":  (0, 3),
    "fecha_apertura_incidente_3":  (0, 3),
}


def _rad_year(case) -> Optional[int]:
    """Año de radicación (díg. 12-16 del rad23)."""
    d = re.sub(r"\D", "", getattr(case, "radicado_23_digitos", None) or "")
    if len(d) >= 16 and d[12:16].isdigit():
        return int(d[12:16])
    return None


def _date_out_of_range(v9_key: str, value: str, rad_year: Optional[int]) -> bool:
    """True si `value` (DD/MM/YYYY) cae fuera de [rad_year+lo, rad_year+hi] del campo."""
    if rad_year is None or v9_key not in _DATE_YEAR_BOUNDS:
        return False
    m = re.search(r"\b(20\d{2})\b", value or "")
    if not m:
        return False
    y = int(m.group(1))
    lo, hi = _DATE_YEAR_BOUNDS[v9_key]
    return not (rad_year + lo <= y <= rad_year + hi)


# Mapeo ExtractedFields key → Case ORM column.
# Solo los campos que v9 escribe. El resto se deja como esté.
_CASE_FIELD_MAP = {
    # Excel field → Case attribute
    "radicado_23_digitos": "radicado_23_digitos",  # SÍ existe en Case (lo lee el cuadro Excel)
    "radicado_forest": "radicado_forest",
    "tipo_actuacion": "tipo_actuacion",
    "accionante": "accionante",
    "accionados": "accionados",
    "vinculados": "vinculados",
    "derecho_vulnerado": "derecho_vulnerado",
    "categoria_tematica": "categoria_tematica",
    "juzgado": "juzgado",
    "ciudad": "ciudad",
    "fecha_ingreso": "fecha_ingreso",
    "asunto": "asunto",
    "pretensiones": "pretensiones",
    "oficina_responsable": "oficina_responsable",
    "abogado_responsable": "abogado_responsable",
    "estado": "estado",
    "fecha_respuesta": "fecha_respuesta",
    "impugnacion": "impugnacion",
    "quien_impugno": "quien_impugno",
    "forest_impugnacion": "forest_impugnacion",
    "incidente": "incidente",
    "fecha_apertura_incidente": "fecha_apertura_incidente",
    "responsable_desacato": "responsable_desacato",
    "abogado_incidente": "abogado_incidente",
    "decision_incidente": "decision_incidente",
    # Incidente 2
    "incidente_2": "incidente_2",
    "fecha_apertura_incidente_2": "fecha_apertura_incidente_2",
    "responsable_desacato_2": "responsable_desacato_2",
    "abogado_incidente_2": "abogado_incidente_2",
    "decision_incidente_2": "decision_incidente_2",
    # Incidente 3
    "incidente_3": "incidente_3",
    "fecha_apertura_incidente_3": "fecha_apertura_incidente_3",
    "responsable_desacato_3": "responsable_desacato_3",
    "abogado_incidente_3": "abogado_incidente_3",
    "decision_incidente_3": "decision_incidente_3",
    # Texto libre
    "observaciones": "observaciones",
    # Fallo 1ra y 2da viven en Case (también en ComplianceTracking pero son distintos)
    "sentido_fallo_1st": "sentido_fallo_1st",
    "fecha_fallo_1st": "fecha_fallo_1st",
    "sentido_fallo_2nd": "sentido_fallo_2nd",
    "fecha_fallo_2nd": "fecha_fallo_2nd",
    "juzgado_2nd": "juzgado_2nd",
}

# Campos identificadores del expediente: una vez establecidos NUNCA se sobreescriben
# por re-extracción. El extractor de regex_pass puede capturar rads ajenos del texto
# (anexos de antecedentes, citas jurisprudenciales, oficios multiplexados, etc.) —
# si pisara el rad del case, perderíamos el identificador único.
#
# Si el rad detectado por v9 difiere del actual, generamos warning para que el
# operador lo revise en la UI; pero NO escribimos.
#
# Para corregir el rad de un case se edita manualmente en la ficha (UI o
# `UPDATE cases SET radicado_23_digitos=... WHERE id=...`), no por re-extract.
STICKY_FIELDS: frozenset[str] = frozenset({
    "radicado_23_digitos",
    "radicado_forest",
    # 2026-05-18: `accionante` es campo de identidad del case. Si la carpeta tiene
    # docs prestados (otras tutelas con mismo rad corto), el extractor puede
    # proponer el accionante equivocado (visto en case 25: rad23 contaminado).
    # Una vez establecido (manual u extracción inicial), NO pisar por re-extract.
    "accionante",
})


def persist(
    db: Session,
    case_id: int,
    fields: ExtractedFields,
    dry_run: bool = True,
) -> dict:
    """Aplica `fields` al Case `case_id`. Retorna dict con cambios.

    Política:
      - Solo escribe si el campo en DB está vacío/None y v9 tiene valor.
      - NUNCA sobrescribe valor humano (FieldSource.MANUAL en sources_json).
      - Persiste tracking en `Case.field_confidences_json` con shape:
        {
          "v9_extracted_at": "ISO timestamp",
          "v9_sources": {field: "regex"|"catalog"|"excel"|"llm", ...},
          "v9_completitud": 78.5,
          "v9_abogado_canonical_confidence": 0.95,
          "v9_dependencia_canonical_confidence": 0.85
        }
    """
    from backend.database.models import Case  # import lazy

    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return {"error": f"Case {case_id} no existe", "changes": {}}

    # Detectar valores manuales previos para no pisarlos
    prev_sources: dict = {}
    if case.field_confidences_json:
        try:
            prev_sources = json.loads(case.field_confidences_json).get("v9_sources", {})
        except (json.JSONDecodeError, TypeError):
            prev_sources = {}

    changes: dict[str, dict] = {}
    sticky_conflicts: list[dict] = []  # rads ajenos detectados que NO se aplican
    rejected_dates: list[dict] = []    # F7: fechas fuera del año del rad ±N
    rad_year = _rad_year(case)
    for v9_key, value in fields.values.items():
        if not value:
            continue
        col = _CASE_FIELD_MAP.get(v9_key)
        if not col:
            continue
        # Normaliza homóglifos cirílicos (О→O, Т→T, …) en cualquier valor de texto
        # antes de persistir. El OCR/LLM los introduce y ensucian campos de identidad
        # como `accionante` (visto en c325). Latinizar siempre es seguro.
        if isinstance(value, str):
            value = normalize_homoglyphs(value)
        # F7: rechazar fechas cuyo año cae fuera de la ventana del rad (fecha citada mal
        # tomada como fallo/respuesta). No se persiste — deja el campo vacío.
        if _date_out_of_range(v9_key, value, rad_year):
            rejected_dates.append({"field": v9_key, "value": value, "rad_year": rad_year})
            logger.warning(
                "Case %d: %s=%r rechazado por F7 (fuera del año del rad %s)",
                case_id, v9_key, value, rad_year,
            )
            continue
        current = getattr(case, col, None)
        # Respeta valor manual previo
        if prev_sources.get(v9_key) == FieldSource.MANUAL.value:
            continue
        # STICKY: identificadores del expediente nunca se sobreescriben una vez
        # establecidos (regresión 2026-05-15: v9 pisaba radicado_23_digitos con
        # rads ajenos capturados en anexos de antecedentes).
        if v9_key in STICKY_FIELDS and current and current != value:
            sticky_conflicts.append({
                "field": v9_key,
                "current": current,
                "v9_proposed": value,
                "source": fields.sources[v9_key].value,
            })
            logger.warning(
                "Case %d: v9 propuso %s=%r pero campo ya es %r (sticky, no se pisa)",
                case_id, v9_key, value, current,
            )
            continue
        # Una vez que un campo tiene valor (venga de v9, v8 o manual), v9 NO lo
        # sobrescribe en re-extracciones posteriores. Política de "first-writer
        # wins": el primer pase v9 escribe el valor; los siguientes pases solo
        # llenan vacíos. Esto reproduce el contrato `fields.set() rechaza
        # sobrescrituras` documentado en CLAUDE.md y evita regresiones donde un
        # texto OCR posterior degrada un campo previamente rico (ej. case 73:
        # texto del Auto de incidente reemplazando observaciones de IA).
        # Para forzar refresh: marcar el campo MANUAL=null en v9_sources, o
        # editar a mano vía UI/UPDATE.
        if current:
            continue
        if current == value:
            continue
        changes[v9_key] = {
            "column": col,
            "old": current,
            "new": value,
            "source": fields.sources[v9_key].value,
        }

    # Canónicos
    if fields.abogado_canonical and fields.abogado_canonical_confidence >= 0.85:
        if case.abogado_canonical != fields.abogado_canonical:
            changes["__abogado_canonical"] = {
                "column": "abogado_canonical",
                "old": case.abogado_canonical,
                "new": fields.abogado_canonical,
                "confidence": fields.abogado_canonical_confidence,
            }
    if fields.dependencia_canonical and fields.dependencia_canonical_confidence >= 0.7:
        if case.dependencia_canonical != fields.dependencia_canonical:
            changes["__dependencia_canonical"] = {
                "column": "dependencia_canonical",
                "old": case.dependencia_canonical,
                "new": fields.dependencia_canonical,
                "confidence": fields.dependencia_canonical_confidence,
            }
        # Jerarquía SED L1/L2/L3 — se escriben juntos con el canonical
        for attr_name, value in (("direccion", fields.direccion),
                                 ("grupo", fields.grupo),
                                 ("equipo", fields.equipo)):
            current = getattr(case, attr_name, None)
            if value and current != value:
                changes[f"__{attr_name}"] = {
                    "column": attr_name,
                    "old": current,
                    "new": value,
                    "source": "derived_from_dependencia_canonical",
                }

    if dry_run:
        return {
            "case_id": case_id,
            "dry_run": True,
            "changes": changes,
            "sticky_conflicts": sticky_conflicts,
            "rejected_dates": rejected_dates,
            "completitud": fields.completitud(),
        }

    # Aplicar cambios reales
    for v9_key, ch in changes.items():
        col = ch["column"]
        setattr(case, col, ch["new"])

    # Update tracking JSON
    tracking = {}
    if case.field_confidences_json:
        try:
            tracking = json.loads(case.field_confidences_json)
        except (json.JSONDecodeError, TypeError):
            tracking = {}
    tracking.update({
        "v9_extracted_at": datetime.utcnow().isoformat(),
        "v9_sources": {**prev_sources, **{k: v.value for k, v in fields.sources.items() if fields.values[k]}},
        "v9_completitud": fields.completitud(),
        "v9_abogado_canonical_confidence": fields.abogado_canonical_confidence,
        "v9_dependencia_canonical_confidence": fields.dependencia_canonical_confidence,
    })
    case.field_confidences_json = json.dumps(tracking, ensure_ascii=False)
    case.updated_at = datetime.utcnow()

    db.commit()

    return {
        "case_id": case_id,
        "dry_run": False,
        "changes": changes,
        "sticky_conflicts": sticky_conflicts,
        "rejected_dates": rejected_dates,
        "completitud": fields.completitud(),
    }
