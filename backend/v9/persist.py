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
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from backend.v9.types import ExtractedFields, FieldSource

logger = logging.getLogger("tutelas.v9.persist")


# Mapeo ExtractedFields key → Case ORM column.
# Solo los campos que v9 escribe. El resto se deja como esté.
_CASE_FIELD_MAP = {
    # Excel field → Case attribute
    "radicado_23_digitos": None,         # NO existe en Case (es virtual / vía Extraction)
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
    "decision_incidente": "decision_incidente",
    # Incidente 2
    "incidente_2": "incidente_2",
    "fecha_apertura_incidente_2": "fecha_apertura_incidente_2",
    "responsable_desacato_2": "responsable_desacato_2",
    "decision_incidente_2": "decision_incidente_2",
    # Incidente 3
    "incidente_3": "incidente_3",
    "fecha_apertura_incidente_3": "fecha_apertura_incidente_3",
    "responsable_desacato_3": "responsable_desacato_3",
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
    for v9_key, value in fields.values.items():
        if not value:
            continue
        col = _CASE_FIELD_MAP.get(v9_key)
        if not col:
            continue
        current = getattr(case, col, None)
        # Respeta valor manual previo
        if prev_sources.get(v9_key) == FieldSource.MANUAL.value:
            continue
        # Respeta valor existente que no vino de v9 (no pisar v8 todavía)
        if current and v9_key not in prev_sources:
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
        "completitud": fields.completitud(),
    }
