"""Sincronización de la línea de ACTUACIONES procesales reales (CPNU) a
`case_actuaciones` (Fase C).

Vuelca la línea de tiempo del expediente (fecha + tipo + anotación de cada actuación)
con `source='rama_judicial_api'`, dedup por (case_id, fecha, tipo). Detecta actuaciones
NUEVAS (las que no estaban) → base para alertas de novedad (nuevo fallo/sanción).

Convive con la bitácora administrativa del Excel CONTROL TUTELAS (source distinto):
ambas en la misma tabla, distinguibles por `source`.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from backend.core.time import utcnow
from backend.email.rad_utils import derive_rad_corto_from_rad23

logger = logging.getLogger("tutelas.rama_judicial_sync")

SOURCE = "rama_judicial_api"


def sync_case_actuaciones(db: Session, case, proceso: dict) -> dict:
    """Upsert de las actuaciones CPNU de `proceso` (ProcesoCPNU.to_dict()) a
    case_actuaciones. Returns {added, total_api, nuevas:[...]}. No-op si no hay actuaciones."""
    from backend.database.models import CaseActuacion

    acts = proceso.get("actuaciones") or []
    if not acts:
        return {"added": 0, "total_api": 0, "nuevas": []}

    rad_corto = derive_rad_corto_from_rad23(getattr(case, "radicado_23_digitos", None))
    sv = utcnow().strftime("%Y-%m-%d")

    # dedup contra lo ya cargado de ESTA fuente para este caso
    existing = {
        (a.fecha_actuacion or "", (a.tipo_actuacion or "").upper())
        for a in db.query(CaseActuacion).filter(
            CaseActuacion.case_id == case.id, CaseActuacion.source == SOURCE).all()
    }

    added, nuevas = 0, []
    for a in acts:
        fecha = a.get("fecha") or ""
        tipo = (a.get("actuacion") or "").strip()
        key = (fecha, tipo.upper())
        if not tipo or key in existing:
            continue
        db.add(CaseActuacion(
            case_id=case.id,
            radicado_corto=rad_corto or None,
            fecha_actuacion=fecha or None,
            tipo_actuacion=tipo,
            observaciones=(a.get("anotacion") or None),
            source=SOURCE,
            source_version=sv,
            imported_at=utcnow(),
        ))
        existing.add(key)
        added += 1
        nuevas.append({"fecha": fecha, "tipo": tipo})
    if added:
        db.commit()
        logger.info("c%s: +%d actuaciones CPNU (source=%s)", case.id, added, SOURCE)
    return {"added": added, "total_api": len(acts), "nuevas": nuevas}
