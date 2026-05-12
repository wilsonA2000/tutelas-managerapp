"""Etapa 4 — Reconciliación con el cuadro CONTROL TUTELAS.xlsx.

Si existe una fila en el Excel que coincide (por radicado_corto o FOREST) con
el caso, sus valores autoritativos llenan los campos del cuadro que regex no
pudo extraer. El Excel es autoridad para:

  - abogado_responsable (lo asigna la oficina, no aparece firmando docs)
  - oficina_responsable / dependencia_canonical
  - estado (ACTIVO / INACTIVO según gestión interna)

NO sobrescribe lo que regex ya extrajo de los documentos — solo llena
huecos. Esta etapa es opcional: si no hay Excel cargado, no falla.
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.v9.types import ExtractedFields, FieldSource

logger = logging.getLogger("tutelas.v9.excel")


def run(
    fields: ExtractedFields,
    excel_row: Optional[dict] = None,
) -> ExtractedFields:
    """Aplica datos del Excel al `fields` actual. Solo llena huecos.

    `excel_row` debe tener keys normalizadas (lowercase, snake_case). Se
    espera que el caller ya haya hecho el match radicado→fila usando
    `services/control_tutelas_importer.py`.
    """
    if not excel_row:
        return fields

    # Mapeo Excel column → ExtractedFields key. Ajustar si el Excel cambia.
    mapping = {
        "abogado_responsable": "abogado_responsable",
        "oficina_responsable": "oficina_responsable",
        "estado": "estado",
        "fecha_respuesta": "fecha_respuesta",
        "categoria_tematica": "categoria_tematica",
        "derecho_vulnerado": "derecho_vulnerado",
    }

    for excel_key, field_key in mapping.items():
        v = excel_row.get(excel_key)
        if v and isinstance(v, str) and v.strip():
            fields.set(field_key, v.strip(), FieldSource.EXCEL)

    return fields
