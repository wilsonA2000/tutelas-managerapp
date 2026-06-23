"""Capa COMPLEMENTO: normaliza la salida del extractor único DeepSeek al formato canónico
del cuadro (re-arquitectura 2026-06-22). NO compite con DeepSeek — toma su valor (correcto)
y lo snapea al formato/catálogo oficial. Reusa los normalizadores que ya existían.

- fechas → DD/MM/YYYY (incluye ISO de DeepSeek)
- juzgado/juzgado_2nd → ordinal canónico (23 → VIGÉSIMO TERCERO)
- abogados → nombre canónico del roster (catálogo)
- categoria_tematica + oficina_responsable → DERIVADAS de asunto (deterministas)
- mayúsculas en nombres/entidades
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("tutelas.v9.normalize")

_DATE_FIELDS = ("fecha_ingreso", "fecha_respuesta", "fecha_fallo_1st", "fecha_fallo_2nd",
                "fecha_apertura_incidente", "fecha_apertura_incidente_2", "fecha_apertura_incidente_3")
_JUZGADO_FIELDS = ("juzgado", "juzgado_2nd")
_ABOGADO_FIELDS = ("abogado_responsable", "abogado_incidente", "abogado_incidente_2", "abogado_incidente_3")
_UPPER_FIELDS = ("accionante", "accionados", "vinculados", "ciudad",
                 "responsable_desacato", "responsable_desacato_2", "responsable_desacato_3")
_MESES = {1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
          7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"}

# Mapa asunto→categoria_tematica DERIVADO del cuadro CURADO (verdad humana, 100% consistente).
# Se usa en vez de legal_schema (cuya taxonomía más amplia devuelve valores fuera del enum del
# cuadro, ej. INFRAESTRUCTURA_EDUCATIVA). F1.5 fix 2026-06-22.
_ASUNTO_TO_CATEGORIA = {
    "ALIMENTACION_PAE": "PERMANENCIA_ESCOLAR", "CALIDAD_EDUCATIVA": "CALIDAD_EDUCATIVA",
    "CESANTIAS": "PRESTACIONES_SOCIALES", "CNSC_CONCURSO": "CARRERA_DOCENTE",
    "DEBIDO_PROCESO": "APOYO_JURIDICO", "DERECHO_PETICION": "APOYO_JURIDICO",
    "EDUCACION": "COBERTURA_EDUCATIVA", "INCIDENTE_DESACATO": "APOYO_JURIDICO",
    "INCLUSION_DISCAPACIDAD": "COBERTURA_EDUCATIVA", "INSPECCION": "INSPECCION_VIGILANCIA",
    "MATRICULA": "COBERTURA_EDUCATIVA", "NOMBRAMIENTO": "ADMINISTRACION_PLANTA",
    "PENSION": "PRESTACIONES_SOCIALES", "PETICION": "APOYO_JURIDICO",
    "PROTECCION_MENOR": "COBERTURA_EDUCATIVA", "REINTEGRO": "CARRERA_DOCENTE",
    "SALARIO": "NOMINA", "SALUD_DOCENTE": "PRESTACIONES_SOCIALES",
    "TESORERIA": "FINANCIERA", "TRANSPORTE_ESCOLAR": "PERMANENCIA_ESCOLAR",
    "TRASLADO": "CARRERA_DOCENTE", "TUTELA_GENERICA": "DERECHOS_FUNDAMENTALES",
    "TUTOR_SOMBRA": "COBERTURA_EDUCATIVA",
}


def _to_ddmmyyyy(s: str) -> str:
    """ISO (YYYY-MM-DD) o variantes → DD/MM/YYYY. Si no parsea, deja el original."""
    s = (s or "").strip()
    if not s:
        return s
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)  # ISO de DeepSeek
    if m:
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        return f"{d:02d}/{mo:02d}/{y}"
    try:
        from backend.v9.regex_pass import _norm_fecha
        n = _norm_fecha(s)
        if n:
            return n
    except Exception:
        pass
    return s


def normalize_fields(out: dict) -> dict:
    """Devuelve una copia normalizada de los campos extraídos por DeepSeek."""
    r = dict(out)

    # radicado_23: el cuadro guarda 23 DÍGITOS PUROS; DeepSeek a veces pone separadores/desglosa
    # el año (ej. '683684089001-2026-00008-00'). Stripear no-dígitos → forma canónica.
    rad = r.get("radicado_23_digitos", "")
    if rad:
        d = re.sub(r"\D", "", rad)
        if len(d) >= 18:
            r["radicado_23_digitos"] = d

    for f in _DATE_FIELDS:
        if r.get(f):
            r[f] = _to_ddmmyyyy(r[f])

    try:
        from backend.v9.catalog_resolve import normalize_juzgado, resolve_abogado
        for f in _JUZGADO_FIELDS:
            if r.get(f):
                r[f] = normalize_juzgado(r[f])
        for f in _ABOGADO_FIELDS:
            if r.get(f):
                canon, conf = resolve_abogado(r[f])
                if canon and conf >= 0.7:
                    r[f] = canon
    except Exception as e:  # noqa: BLE001
        logger.debug("normalize juzgado/abogado falló: %s", e)

    # categoria_tematica + oficina_responsable DERIVADAS de asunto (deterministas, no LLM)
    asunto = (r.get("asunto") or "").strip().upper()
    if asunto and asunto not in ("SIN_DETERMINAR", "OTRO"):
        cat = _ASUNTO_TO_CATEGORIA.get(asunto)
        if cat:
            r["categoria_tematica"] = cat   # mapa del cuadro curado (en el enum del cuadro)
        try:
            from backend.v9.field_extractor import _ASUNTO_TO_L1
            ofi = _ASUNTO_TO_L1.get(asunto)
            if ofi:
                r["oficina_responsable"] = ofi
        except Exception as e:  # noqa: BLE001
            logger.debug("derivar oficina falló: %s", e)

    for f in _UPPER_FIELDS:
        if r.get(f):
            r[f] = r[f].upper()

    return r
