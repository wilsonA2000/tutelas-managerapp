"""Extractor ÚNICO de campos vía DeepSeek (re-arquitectura 2026-06-22).

Una sola autoridad: DeepSeek lee el EXPEDIENTE COMPLETO del caso (ventana 1M de v4-flash) y
emite los 44 campos del cuadro en UNA llamada estructurada. Reemplaza la competencia
regex+gap_fill+catálogo (cada campo tenía hasta 3 autoridades). Las capas deterministas pasan
a COMPLEMENTAR (validar identificadores, normalizar catálogos, cruzar API) — ver validate.py.

Decisión de Wilson: DeepSeek hace TODO (incl. identificadores); los validadores son el
blindaje anti-alucinación, no autoridades competidoras.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

from backend.v9.types import EXCEL_FIELDS

logger = logging.getLogger("tutelas.v9.llm_extract")

# Campos VERBATIM (transcripción textual del RESUELVE / pretensiones): NO van al LLM —
# el LLM parafrasea + infla la salida (trunca el JSON). Se llenan con la transcripción
# determinista (mejor para texto legal literal). Decisión de diseño del benchmark F2.
_VERBATIM_FIELDS = ("pretensiones", "parte_resolutiva_1st", "parte_resolutiva_2nd",
                    "parte_resolutiva_incidente")
_LLM_FIELDS = tuple(f for f in EXCEL_FIELDS if f not in _VERBATIM_FIELDS)

# Presupuesto de chars del expediente que se manda al LLM. v4-flash = 1M tokens ≈ ~3.5M chars;
# 600k chars ≈ ~170K tokens deja margen de sobra para prompt + salida. env-tunable.
_BUNDLE_CAP = int(os.getenv("V9_EXTRACT_BUNDLE_CAP", "600000"))
_PER_DOC_CAP = int(os.getenv("V9_EXTRACT_PER_DOC_CAP", "60000"))  # cota por doc (docs monstruo)

# Vocabularios controlados (deben coincidir con los enums del cuadro).
_VOCAB = {
    "derecho_vulnerado": ["EDUCACION", "SALUD", "PETICION", "DEBIDO_PROCESO", "VIDA",
                          "SEGURIDAD_SOCIAL", "MINIMO_VITAL", "TRABAJO", "IGUALDAD",
                          "INTIMIDAD", "HABEAS_DATA", "OTRO"],
    "asunto": ["TRASLADO", "REINTEGRO", "NOMBRAMIENTO", "PENSION", "CESANTIAS",
               "HISTORIA_LABORAL", "CNSC_CONCURSO", "ACOSO_LABORAL", "SALUD_DOCENTE", "SALARIO",
               "FSE", "TESORERIA", "TUTOR_SOMBRA", "INCLUSION_DISCAPACIDAD", "MATRICULA",
               "PROTECCION_MENOR", "EDUCACION", "CALIDAD_EDUCATIVA", "TRANSPORTE_ESCOLAR",
               "ALIMENTACION_PAE", "INCIDENTE_DESACATO", "DERECHO_PETICION", "DEBIDO_PROCESO",
               "INSPECCION", "TUTELA_GENERICA"],
    "categoria_tematica": ["ADMINISTRACION_PLANTA", "APOYO_JURIDICO", "CALIDAD_EDUCATIVA",
                           "CARRERA_DOCENTE", "COBERTURA_EDUCATIVA", "DERECHOS_FUNDAMENTALES",
                           "FINANCIERA", "INSPECCION_VIGILANCIA", "NOMINA", "PERMANENCIA_ESCOLAR",
                           "PRESTACIONES_SOCIALES", "SIN_DETERMINAR"],
    "sentido_fallo_1st": ["CONCEDE", "CONCEDE_PARCIAL", "NIEGA", "IMPROCEDENTE",
                          "HECHO_SUPERADO", "CARENCIA_OBJETO", "DESISTIMIENTO"],
    "sentido_fallo_2nd": ["CONFIRMA", "REVOCA", "MODIFICA", "CONFIRMA_MODIFICANDO",
                          "CONFIRMA_PARCIAL", "NULIDAD"],
    "decision_incidente": ["SANCIONA", "NO_SANCIONA", "CIERRA", "EN_TRAMITE", "NIEGA_APERTURA"],
    "decision_incidente_2": ["SANCIONA", "NO_SANCIONA", "CIERRA", "EN_TRAMITE", "NIEGA_APERTURA"],
    "decision_incidente_3": ["SANCIONA", "NO_SANCIONA", "CIERRA", "EN_TRAMITE", "NIEGA_APERTURA"],
    "tipo_actuacion": ["TUTELA"],
    "estado": ["ACTIVO", "INACTIVO"],
    "impugnacion": ["SI", "NO"],
    "incidente": ["SI", "NO"],
    "incidente_2": ["SI", "NO"],
    "incidente_3": ["SI", "NO"],
}

# Reglas jurídicas clave por campo (las no obvias). Se inyectan en el prompt.
_RULES = (
    "REGLAS JURÍDICAS (Colombia, tutelas SED Santander):\n"
    "- radicado_23_digitos: el CUP de 23 dígitos del JUZGADO (no el número interno de la "
    "Gobernación). Si no aparece el de 23, deja vacío.\n"
    "- radicado_forest: SOLO si aparece literal en un correo de la Gobernación (formato GESTA, "
    "ej '2-2026-104200-001763' o continuo year-prefixed). NUNCA lo inventes ni lo derives del PDF.\n"
    "- derecho_vulnerado: lista TODOS los derechos fundamentales invocados como vulnerados "
    "(no solo el principal), separados por ' - '. Ej: 'SALUD - PETICION - VIDA'.\n"
    "- accionante: quien interpone. Si es un MENOR, el accionante es el PADRE/MADRE/AGENTE "
    "OFICIOSO (nunca el menor). Si la presenta un personero, accionante = 'PERSONERÍA MUNICIPAL DE <municipio>'.\n"
    "- accionados / vinculados: entidades demandadas / vinculadas (Secretaría de Educación, etc.).\n"
    "- ciudad: el municipio de AFECTACIÓN del derecho (plaza del docente / colegio del menor), "
    "NO la ciudad del juzgado.\n"
    "- juzgado: el de PRIMERA instancia. fecha_ingreso: fecha de admisión/radicación (no la de un correo).\n"
    "- sentido_fallo_*: lee TODO el RESUELVE (fallos mixtos niegan en un punto y conceden en otro).\n"
    "- parte_resolutiva_1st/2nd/incidente: TRANSCRIPCIÓN VERBATIM del RESUELVE (copia textual, sin parafrasear).\n"
    "- impugnacion: SI solo si hay escrito de impugnación real. quien_impugno: ACCIONANTE o ACCIONADO.\n"
    "- incidente: SI si hay incidente de desacato. responsable_desacato: la persona NOMBRADA/SANCIONADA "
    "(gobernador/secretaria/rector), NO el abogado. Hasta 3 incidentes (_2,_3).\n"
    "- abogado_responsable: SOLO si hay respuesta SED firmada en el expediente que lo identifique; si no, vacío.\n"
    "- estado: ACTIVO si el proceso sigue vivo (sin fallo en firme/cumplido), INACTIVO si terminó.\n"
    "- Si un dato NO está en el expediente, deja el campo "" (vacío) o 'SIN_DETERMINAR' donde aplique. "
    "NO inventes. Mejor vacío que incorrecto.\n"
)


def build_expediente_bundle(db, case) -> str:
    """Concatena TODO el texto del expediente (docs + emails) ordenado, con cotas."""
    from backend.database.models import Document
    docs = (db.query(Document)
            .filter(Document.case_id == case.id)
            .order_by(Document.id.asc())
            .all())
    parts: list[str] = []
    used = 0
    for d in docs:
        txt = (d.extracted_text or "").strip()
        if not txt:
            continue
        txt = txt[:_PER_DOC_CAP]
        block = f"\n===== DOC #{d.id} [{d.doc_type or 'OTRO'}] {d.filename or ''} =====\n{txt}\n"
        if used + len(block) > _BUNDLE_CAP:
            block = block[: max(0, _BUNDLE_CAP - used)]
            parts.append(block)
            break
        parts.append(block)
        used += len(block)
    return "".join(parts)


def _build_prompt(bundle: str, folder_name: str) -> str:
    fields_list = ", ".join(_LLM_FIELDS)
    vocab_lines = "\n".join(
        f"- {f}: uno de [{', '.join(v)}]" + (" (o 'SIN_DETERMINAR'/'' si no aplica)" if f in
        ("derecho_vulnerado", "asunto", "categoria_tematica") else "")
        for f, v in _VOCAB.items()
    )
    return (
        "Eres un abogado experto en tutelas de la Secretaría de Educación de Santander (Colombia). "
        "Lee el EXPEDIENTE COMPLETO y extrae los campos del cuadro de control. Responde ÚNICAMENTE "
        "con un objeto JSON con EXACTAMENTE estas claves (sin texto adicional):\n"
        f"{fields_list}\n\n"
        f"{_RULES}\n"
        "CAMPOS CON VOCABULARIO CONTROLADO (usa EXACTAMENTE uno de los valores listados):\n"
        f"{vocab_lines}\n\n"
        f"Carpeta del caso: {folder_name!r}\n"
        "=== EXPEDIENTE ===\n"
        f"{bundle}\n"
        "=== FIN EXPEDIENTE ===\n\n"
        f"Responde SOLO el JSON con esas {len(_LLM_FIELDS)} claves. Valores como string (vacío \"\" si no hay dato)."
    )


def _parse_json(raw: str) -> Optional[dict]:
    raw = re.sub(r"```(?:json)?|```", "", raw or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def extract_all(db, case) -> dict:
    """Extrae los 44 campos del caso en 1 llamada DeepSeek. Devuelve {campo: valor}.

    Solo emite valores que el LLM extrajo; el caller valida (validate.py) y persiste (no-clobber).
    Si el LLM está off o falla, devuelve {} (sin extracción — el caller decide).
    """
    bundle = build_expediente_bundle(db, case)
    if len(bundle) < 100:
        logger.info("extract_all case=%s: expediente sin texto suficiente (%d chars)", case.id, len(bundle))
        return {}
    prompt = _build_prompt(bundle, case.folder_name or "")
    try:
        from backend.extraction.ai_extractor import _call_local
        raw, _, _ = _call_local(
            [{"role": "system", "content": "Extraes campos de tutelas. Respondes solo JSON."},
             {"role": "user", "content": prompt}],
            max_tokens=4000,
        )
    except Exception as e:
        logger.warning("extract_all case=%s: LLM falló: %s", case.id, str(e)[:200])
        return {}
    data = _parse_json(raw)
    if not isinstance(data, dict):
        logger.warning("extract_all case=%s: respuesta no-JSON", case.id)
        return {}
    # Quedarse solo con las claves válidas del cuadro, normalizar a string.
    out = {}
    for f in EXCEL_FIELDS:
        v = data.get(f, "")
        out[f] = ("" if v is None else str(v)).strip()
    # Capa COMPLEMENTO: normaliza al formato canónico (juzgado/fechas/abogado) + deriva
    # categoria/oficina de asunto. No compite con DeepSeek; snapea su valor al cuadro.
    from backend.v9.normalize_extract import normalize_fields
    out = normalize_fields(out)
    # Validador determinista: borra identificadores que NO aparecen literal en el expediente
    # (anti-alucinación: un radicado/FOREST inventado es catastrófico).
    from backend.v9.validate import apply_identifier_guards
    out, _vwarn = apply_identifier_guards(out, bundle)
    if _vwarn:
        logger.info("extract_all case=%s validaciones: %s", case.id, "; ".join(_vwarn[:4]))
    logger.info("extract_all case=%s: %d/%d campos no vacíos (bundle %d chars)",
                case.id, sum(1 for x in out.values() if x), len(EXCEL_FIELDS), len(bundle))
    return out
