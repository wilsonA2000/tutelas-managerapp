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
import os
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

    # V9_LLM_SINGLE_CALL: en vez de 3 llamadas LLM por-campo (derecho/asunto/pretensiones),
    # se conserva SOLO lo que halló el regex (multi-derecho, vocab SED canónico, pretensión
    # literal — todo gratis) y se deja VACÍO lo que requería LLM, para que `llm_gap_fill`
    # lo llene en UNA sola llamada multi-campo (contexto enviado una vez). Default: off.
    single_call = os.getenv("V9_LLM_SINGLE_CALL", "false").lower() == "true"
    fe_llm = use_llm and not single_call

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
    dv = _try("derecho_vulnerado", lambda: fe.extract_derecho_vulnerado_for_case(db, case, use_llm=fe_llm))
    if dv:
        val, s = dv
        # single_call: solo conserva el regex; si el regex no halló (s="default"), deja
        # vacío para que gap_fill lo resuelva en la llamada única.
        if not (single_call and s != "regex"):
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
    asu = _try("asunto", lambda: fe.extract_asunto_for_case(db, case, use_llm=fe_llm))
    if asu:
        val, s = asu
        # single_call: si el regex no clasificó (s="default"), deja vacío → gap_fill lo
        # llena con el enum del vocab SED (preserva valor canónico).
        if not (single_call and s != "regex"):
            _set("asunto", val, _src(s))
            # categoria_tematica se DERIVA del asunto recién extraído
            try:
                from backend.cognition.legal_schema import categoria_tematica_de_asunto
                cat = categoria_tematica_de_asunto(val)
                _set("categoria_tematica", cat or "SIN_DETERMINAR")
            except Exception as e:  # noqa: BLE001
                logger.debug("categoria_tematica derivada falló: %s", e)
    # pretensiones usa use_llm REAL (no fe_llm): el localizador LLM extrae VERBATIM del
    # original (no parafrasea), así que es independiente del flag SINGLE_CALL. Si regex y
    # localizador fallan → val=None → campo VACÍO. pretensiones NO está en _LLM_FILLABLE,
    # así que el gap_fill nunca lo parafrasea (requisito jurídico: transcripción literal).
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
    # transcripción verbatim del RESUELVE 1ra (determinista, 0 LLM)
    pr1 = _try("parte_resolutiva_1ra", lambda: fe.extract_parte_resolutiva_1ra_for_case(db, case))
    if pr1:
        val, _s = pr1
        _set("parte_resolutiva_1st", val)

    # ── cluster impugnación ──
    imp = _try("impugnacion_cluster", lambda: fe.extract_impugnacion_cluster_for_case(db, case))
    if imp:
        flag, quien, sent2, fec2, _s = imp
        _set("impugnacion", flag)
        _set("quien_impugno", quien)
        _set("sentido_fallo_2nd", sent2)
        _set("fecha_fallo_2nd", fec2)
    # transcripción verbatim del RESUELVE 2da (determinista, 0 LLM)
    pr2 = _try("parte_resolutiva_2da", lambda: fe.extract_parte_resolutiva_2da_for_case(db, case))
    if pr2:
        val, _s = pr2
        _set("parte_resolutiva_2nd", val)

    # ── cluster incidentes (slots 1/2/3) ──
    inc = _try("incidentes_cluster", lambda: fe.extract_incidentes_cluster_for_case(db, case))
    if isinstance(inc, dict):
        inc.pop("_n_incidentes", None)
        for k, v in inc.items():
            _set(k, v)
    # transcripción verbatim del RESUELVE del auto que sanciona el desacato (0 LLM)
    pri = _try("parte_resolutiva_incidente", lambda: fe.extract_parte_resolutiva_incidente_for_case(db, case))
    if pri:
        val, _s = pri
        _set("parte_resolutiva_incidente", val)

    # ── estado (derivado) — sobre `fields` + lo ya persistido en DB ──
    try:
        _set("estado", _derive_estado(fields, case))
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


_ESTADO_INPUT_FIELDS = (
    "sentido_fallo_1st", "impugnacion", "sentido_fallo_2nd",
    "incidente", "decision_incidente", "incidente_2", "decision_incidente_2",
    "incidente_3", "decision_incidente_3",
)


def _derive_estado(fields: ExtractedFields, case=None) -> str:
    """ACTIVO/INACTIVO derivado de los campos. DELEGA en la autoridad única
    field_extractor.extract_estado_for_case (antes había una reimplementación
    byte-por-byte aquí: dos reglas que podían divergir).

    Lee de `fields` (lo extraído en este pase) PERO cae a los valores ya persistidos
    en `case` para los campos que este pase no re-extrajo. Sin ese fallback, una
    re-extracción parcial (que trae solo algunos campos en `fields`) derivaba un
    estado inconsistente con la DB completa (regresión vista en c12/c60/c390:
    sentido_fallo_2nd seguía en DB pero faltaba en `fields` → estado ACTIVO erróneo)."""
    from types import SimpleNamespace
    from backend.v9 import field_extractor as fe
    v = dict(fields.values)
    if case is not None:
        for k in _ESTADO_INPUT_FIELDS:
            if not v.get(k):
                dbval = getattr(case, k, None)
                if dbval:
                    v[k] = dbval
    # La autoridad lee los inputs vía getattr(case, ...); le pasamos la vista
    # merged (fields + fallback DB) como un objeto con esos atributos.
    merged = SimpleNamespace(**{k: v.get(k) for k in _ESTADO_INPUT_FIELDS})
    return fe.extract_estado_for_case(None, merged)
