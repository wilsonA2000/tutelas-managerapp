"""Fase 6.6: Auto-normalización de flags impugnacion/incidente.

Si el pipeline determinista o la IA llenó datos de 2da instancia o de desacato,
las flags binarias deben reflejarlo. Esto elimina inconsistencias artificiales
que disparan REVISION cuando en realidad el case está correcto.

Reglas:
  1. Si HAY datos de 2da instancia (sentido_fallo_2nd, juzgado_2nd, fecha_fallo_2nd,
     quien_impugno, forest_impugnacion) → impugnacion=SI
  2. Si HAY datos de desacato (decision_incidente, responsable_desacato,
     fecha_apertura_incidente) → incidente=SI

Idempotente: solo modifica flags si están vacías o contradicen los datos.
"""
from __future__ import annotations
import logging

logger = logging.getLogger("tutelas.flag_normalizer")


def _is_filled(v) -> bool:
    if v is None:
        return False
    s = str(v).strip()
    if not s:
        return False
    return s.lower() not in ("n/a", "no aplica", "-", "none", "null", "no")


def normalize_flags(case) -> dict:
    """Auto-corrige impugnacion/incidente flags si datos los contradicen.

    Returns: dict con flags corregidos: {flag_name: ("from", "to")}
    """
    changes = {}
    imp = (getattr(case, "impugnacion", "") or "").strip().upper()
    inc = (getattr(case, "incidente", "") or "").strip().upper()

    # Detectar evidencia de 2da instancia
    has_2nd_instance = any(_is_filled(getattr(case, f, None)) for f in (
        "sentido_fallo_2nd", "juzgado_2nd", "fecha_fallo_2nd",
        "quien_impugno", "forest_impugnacion",
    ))

    if has_2nd_instance and (not imp or imp.startswith("N")):
        old = case.impugnacion
        case.impugnacion = "SI"
        changes["impugnacion"] = (str(old), "SI")

    # Detectar evidencia de desacato
    has_desacato = any(_is_filled(getattr(case, f, None)) for f in (
        "decision_incidente", "responsable_desacato", "fecha_apertura_incidente",
    ))

    if has_desacato and (not inc or inc.startswith("N")):
        old = case.incidente
        case.incidente = "SI"
        changes["incidente"] = (str(old), "SI")

    return changes
