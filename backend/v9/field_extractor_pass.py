"""Etapa CASE-level del pipeline v9: corre los extractores de `field_extractor.py`.

Hasta v9.x el pipeline (`pipeline.py`) solo hacía regex doc-por-doc + catálogo + LLM
gap-fill, así que producía ~30% de completitud. Los 18 campos del cuadro que están
en la DB los escribió `scripts/v9_extract_fields.py` invocando los 22
`extract_<campo>_for_case(db, case)` de `field_extractor.py`. Esta etapa los integra
al pipeline: se ejecuta ANTES de `regex_pass` (es la autoridad de los campos a nivel
case) y escribe vía `ExtractedFields.set()` (que NO sobrescribe lo ya escrito), así
que `regex_pass`/`catalog_resolve`/`llm_gap_fill` solo rellenan lo que falte.

`use_llm` controla los fallbacks LLM de derecho/asunto/pretensiones (lentos en este
equipo) — default False para el preview; True solo en CLI/batch nocturno.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from backend.v9.types import ExtractedFields, FieldSource

logger = logging.getLogger("tutelas.v9.field_extractor_pass")


def _src(s: Optional[str]) -> FieldSource:
    return FieldSource.LLM if (s or "").lower() == "llm" else FieldSource.REGEX


def run(db: Session, case, fields: ExtractedFields, *, use_llm: bool = False) -> int:
    """Aplica los extractores a nivel case sobre `fields`. Devuelve cuántos campos escribió.

    Cada extractor va en su propio try/except: un fallo aislado no tumba el resto.
    """
    from backend.v9 import field_extractor as fe

    written = 0

    def _set(name: str, value, source: FieldSource = FieldSource.REGEX) -> None:
        nonlocal written
        try:
            if value and str(value).strip() and fields.set(name, str(value), source):
                written += 1
        except Exception as e:  # noqa: BLE001
            logger.debug("field_extractor_pass: set(%s) falló: %s", name, e)

    def _try(label: str, fn):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            logger.warning("field_extractor_pass: %s falló para case#%s: %s", label, getattr(case, "id", "?"), str(e)[:200])
            return None

    # ── identificación / partes ──
    forest = _try("forest", lambda: fe.extract_forest_for_case(db, case))
    if forest:
        rf, fi = forest
        _set("radicado_forest", rf)
        _set("forest_impugnacion", fi)

    acc = _try("accionante", lambda: fe.extract_accionante_for_case(db, case))
    nota_acc: Optional[str] = None
    if acc:
        a, nota_acc = acc
        _set("accionante", a)

    _set("accionados", _try("accionados", lambda: fe.extract_accionados_for_case(db, case)))
    _set("vinculados", _try("vinculados", lambda: fe.extract_vinculados_for_case(db, case)))

    # ── materia ──
    dv = _try("derecho_vulnerado", lambda: fe.extract_derecho_vulnerado_for_case(db, case, use_llm=use_llm))
    if dv:
        val, s = dv
        _set("derecho_vulnerado", val, _src(s))

    # ── juzgado / geografía ──
    j1 = _try("juzgado", lambda: fe.extract_juzgado_for_case(db, case))
    _set("juzgado", j1)
    j2 = _try("juzgado_2nd", lambda: fe.extract_juzgado_2nd_for_case(db, case, j1))
    if j2:
        val, _s = j2
        _set("juzgado_2nd", val)
    ci = _try("ciudad", lambda: fe.extract_ciudad_for_case(db, case))
    if ci:
        val, _s = ci
        _set("ciudad", val)

    # ── fechas / narrativa ──
    fing = _try("fecha_ingreso", lambda: fe.extract_fecha_ingreso_for_case(db, case))
    if fing:
        val, _s = fing
        _set("fecha_ingreso", val)
    asu = _try("asunto", lambda: fe.extract_asunto_for_case(db, case, use_llm=use_llm))
    if asu:
        val, s = asu
        _set("asunto", val, _src(s))
        # categoria_tematica se DERIVA del asunto recién extraído
        try:
            from backend.cognition.legal_schema import categoria_tematica_de_asunto
            cat = categoria_tematica_de_asunto(val)
            _set("categoria_tematica", cat or "SIN_DETERMINAR")
        except Exception as e:  # noqa: BLE001
            logger.debug("categoria_tematica derivada falló: %s", e)
    pret = _try("pretensiones", lambda: fe.extract_pretensiones_for_case(db, case, use_llm=use_llm))
    if pret:
        val, s = pret
        _set("pretensiones", val, _src(s))

    # ── asignación interna ──
    ofi = _try("oficina_responsable", lambda: fe.extract_oficina_responsable_for_case(db, case))
    if ofi:
        val, _s = ofi
        _set("oficina_responsable", val)
    abo = _try("abogado_responsable", lambda: fe.extract_abogado_responsable_for_case(db, case))
    if abo:
        val, _s = abo
        _set("abogado_responsable", val)

    # ── fallo 1ra instancia ──
    sf1 = _try("sentido_fallo_1ra", lambda: fe.extract_sentido_fallo_1ra_for_case(db, case))
    if sf1:
        val, _s = sf1
        _set("sentido_fallo_1st", val)
    ff1 = _try("fecha_fallo_1ra", lambda: fe.extract_fecha_fallo_1ra_for_case(db, case))
    if ff1:
        val, _s = ff1
        _set("fecha_fallo_1st", val)

    # ── cluster impugnación ──
    imp = _try("impugnacion_cluster", lambda: fe.extract_impugnacion_cluster_for_case(db, case))
    if imp:
        flag, quien, sent2, fec2, _s = imp
        _set("impugnacion", flag)
        _set("quien_impugno", quien)
        _set("sentido_fallo_2nd", sent2)
        _set("fecha_fallo_2nd", fec2)

    # ── cluster incidentes (slots 1/2/3) ──
    inc = _try("incidentes_cluster", lambda: fe.extract_incidentes_cluster_for_case(db, case))
    if isinstance(inc, dict):
        inc.pop("_n_incidentes", None)
        for k, v in inc.items():
            _set(k, v)

    # ── estado (derivado) — se calcula sobre lo que ya hay en `fields` ──
    try:
        _set("estado", _derive_estado(fields))
    except Exception as e:  # noqa: BLE001
        logger.debug("estado derivado falló: %s", e)

    # ── fecha_respuesta ──
    fr = _try("fecha_respuesta", lambda: fe.extract_fecha_respuesta_for_case(db, case))
    if fr:
        val, _s = fr
        _set("fecha_respuesta", val)

    # ── observaciones: nota de agente oficioso (campo 4) + banderas (campo 18) ──
    obs_parts: list[str] = []
    if nota_acc:
        obs_parts.append(nota_acc)
    flags = _try("observaciones", lambda: fe.extract_observaciones_for_case(db, case)) or []
    obs_parts.extend(flags)
    if obs_parts:
        # observaciones puede venir ya escrita por una etapa anterior; aquí solo si está vacía
        _set("observaciones", "\n".join(dict.fromkeys(obs_parts)))

    logger.info("field_extractor_pass case#%s: %d campos escritos (use_llm=%s)", getattr(case, "id", "?"), written, use_llm)
    return written


def _derive_estado(fields: ExtractedFields) -> str:
    """ACTIVO/INACTIVO derivado de los campos ya extraídos (misma regla que
    field_extractor.extract_estado_for_case, pero leyendo de `fields`)."""
    v = fields.values
    if not v.get("sentido_fallo_1st"):
        return "ACTIVO"
    if (v.get("impugnacion") or "").upper() == "SI" and not v.get("sentido_fallo_2nd"):
        return "ACTIVO"
    for n in ("", "_2", "_3"):
        if (v.get(f"incidente{n}") or "").upper() == "SI":
            d = (v.get(f"decision_incidente{n}") or "").upper()
            if not d or d == "EN_TRAMITE":
                return "ACTIVO"
    return "INACTIVO"
