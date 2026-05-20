"""Etapa 5 — LLM gap fill. ÚLTIMO RECURSO.

Solo se invoca si quedan campos vacíos después de regex+catalog+excel.
Hace UNA SOLA llamada multi-campo al LLM local (Qwen3-4B en `127.0.0.1:8765`)
con un prompt ajustado a los campos faltantes.

Esta etapa puede desactivarse globalmente con `V9_DISABLE_LLM=true` en .env.
Si llama-server no responde, NO falla el pipeline — devuelve los `fields`
intactos y registra `llm_calls=0`.

Diferencia clave vs v8:
  - v8 hacía 5-10 llamadas seriales (1 por campo). v9 hace 1 multi-campo.
  - v8 invocaba LLM aunque el campo ya estuviera. v9 solo si está vacío.
  - v8 usaba `complementary_ai` + `focused_field_extractors` + `agent`. v9
    tiene un solo punto de invocación.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

from backend.v9.types import ExtractedFields, FieldSource

logger = logging.getLogger("tutelas.v9.llm_gap")

import urllib.request
LLM_URL = os.getenv("LLM_LOCAL_URL", f"http://127.0.0.1:{os.getenv('LLM_LOCAL_PORT', '8765')}")

# Vocabularios cerrados para constrained decoding (json_schema enum). El "" permite
# al modelo decir "no sé" sin inventar.
_ENUMS = {
    "derecho_vulnerado": ["EDUCACION", "SALUD", "PETICION", "DEBIDO_PROCESO", "VIDA",
                           "SEGURIDAD_SOCIAL", "MINIMO_VITAL", "TRABAJO", "IGUALDAD",
                           "INTIMIDAD", "HABEAS_DATA", "OTRO", ""],
    "decision_incidente":   ["SI", "NO", "EN_TRAMITE", ""],
    "decision_incidente_2": ["SI", "NO", "EN_TRAMITE", ""],
    "decision_incidente_3": ["SI", "NO", "EN_TRAMITE", ""],
    "quien_impugno":        ["ACCIONANTE", "ACCIONADO", "MINISTERIO_PUBLICO", "AMBOS", ""],
}
_MAXLEN = {"asunto": 140, "pretensiones": 240, "accionados": 200, "vinculados": 200,
           "responsable_desacato": 120, "responsable_desacato_2": 120, "responsable_desacato_3": 120}


def _build_schema(missing: list[str]) -> dict:
    """JSON-schema que ACOTA la salida del LLM: enum para vocab cerrado, maxLength para
    texto libre. Acelera (generación corta) y elimina valores inventados."""
    props = {}
    for f in missing:
        props[f] = {"type": "string", "enum": _ENUMS[f]} if f in _ENUMS \
            else {"type": "string", "maxLength": _MAXLEN.get(f, 160)}
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(missing)}


# Solo estos campos pueden ser llenados por LLM. Los demás son datos
# estructurales (radicado, FOREST, fechas) que si no salieron por regex,
# probablemente están en un doc escaneado y necesitan OCR, no LLM.
_LLM_FILLABLE = (
    "quien_impugno",
    "responsable_desacato",
    "decision_incidente",
    "responsable_desacato_2",
    "decision_incidente_2",
    "responsable_desacato_3",
    "decision_incidente_3",
    "asunto",
    "pretensiones",
    "derecho_vulnerado",
    "accionados",
    "vinculados",
)


# Campos hijos que solo aplican cuando el flag padre = SI.
# Si el padre = NO, NO permitimos al LLM rellenarlos (evita decision_incidente=EN_TRAMITE
# cuando incidente=NO).
_DEPENDENT_FIELDS = {
    "impugnacion": ("quien_impugno", "forest_impugnacion", "juzgado_2nd",
                    "sentido_fallo_2nd", "fecha_fallo_2nd"),
    "incidente":   ("fecha_apertura_incidente", "responsable_desacato",
                    "decision_incidente"),
    "incidente_2": ("fecha_apertura_incidente_2", "responsable_desacato_2",
                    "decision_incidente_2"),
    "incidente_3": ("fecha_apertura_incidente_3", "responsable_desacato_3",
                    "decision_incidente_3"),
}


def _filter_by_consistency(fields, missing: list[str]) -> list[str]:
    """Excluye campos hijos cuyo flag padre dice NO. Mantiene la consistencia
    semántica: si `incidente=NO`, no tiene sentido llenar `decision_incidente`.
    """
    excluded: set[str] = set()
    for parent, children in _DEPENDENT_FIELDS.items():
        if fields.values.get(parent) == "NO":
            excluded.update(children)
    return [f for f in missing if f not in excluded]


_PROMPT = """/no_think
Eres un extractor jurídico. Devuelve SOLO un JSON con los campos solicitados.
Si un campo no está claro en el texto, devuelve cadena vacía "".

Campos a extraer: {fields}

Definiciones:
- quien_impugno: nombre de la parte que impugnó (ACCIONANTE o ACCIONADO o "")
- responsable_desacato: nombre completo del funcionario contra quien va el incidente
- decision_incidente: SI / NO / EN_TRAMITE
- asunto: 1 línea, qué pide el accionante (≤ 120 caracteres)
- pretensiones: lista resumida de lo solicitado (≤ 200 caracteres)
- derecho_vulnerado: derecho fundamental invocado (SALUD, EDUCACION, PETICION, ...)
- accionados: entidades/personas demandadas, separadas por coma
- vinculados: entidades vinculadas (no accionados directos)

Responde SOLO con JSON: {{"campo": "valor", ...}}

Texto:
{text}
"""


def _build_prompt(missing: list[str], text: str) -> str:
    # El texto ya viene curado field-aware (backend/v9/field_context.py): solo las
    # páginas relevantes al campo. Aquí solo un tope de seguridad.
    t = (text or "")[:5200]
    return _PROMPT.format(fields=", ".join(missing), text=t)


def _llm_disabled() -> bool:
    return os.getenv("V9_DISABLE_LLM", "false").lower() == "true"


def _call_llm(prompt: str, missing: list[str]) -> Optional[str]:
    """Llama al LLM local con CONSTRAINED DECODING (json_schema). La salida queda
    acotada al esquema (enum + maxLength) → ~5-6× más rápido en CPU y sin valores
    inventados. Si el server no soporta response_format, reintenta libre. None si falla."""
    body = {
        "messages": [
            {"role": "system", "content": "Eres un asistente jurídico. Extraes datos de tutelas y respondes SOLO el JSON pedido."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 400, "temperature": 0,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "gap_fill", "schema": _build_schema(missing), "strict": True}},
    }

    def _post(payload: dict) -> str:
        req = urllib.request.Request(LLM_URL + "/v1/chat/completions",
                                     data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        raw = urllib.request.urlopen(req, timeout=120).read().decode()
        return json.loads(raw)["choices"][0]["message"]["content"] or ""

    try:
        return _post(body)
    except Exception as e:
        logger.warning("LLM con json_schema falló (%s); reintento sin schema", str(e)[:120])
        try:
            body.pop("response_format", None)
            return _post(body)
        except Exception as e2:
            logger.warning("LLM call falló: %s", str(e2)[:200])
            return None


def _parse_json_loose(raw: str) -> dict:
    """Extrae el primer bloque JSON del raw. Tolera prefijos/sufijos."""
    if not raw:
        return {}
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def run(fields: ExtractedFields, full_text: str) -> tuple[ExtractedFields, int]:
    """Llena campos faltantes con UNA llamada multi-campo. Retorna (fields, llm_calls).

    `full_text` es la concatenación del texto de los docs más relevantes
    (típicamente: auto_admisorio + sentencia + impugnación). Se cap-ea a
    8K caracteres en el prompt.
    """
    if _llm_disabled():
        return fields, 0

    missing_all = fields.missing_fields()
    missing_llm = [f for f in missing_all if f in _LLM_FILLABLE]
    # Aplicar consistencia: no rellenar hijos de flags=NO
    missing_llm = _filter_by_consistency(fields, missing_llm)
    if not missing_llm:
        return fields, 0

    if not full_text or len(full_text.strip()) < 100:
        logger.info("LLM skip: texto insuficiente (%d chars)", len(full_text or ""))
        return fields, 0

    prompt = _build_prompt(missing_llm, full_text)
    raw = _call_llm(prompt, missing_llm)
    if not raw:
        return fields, 0  # falló silencioso, no hay llm_call exitoso

    parsed = _parse_json_loose(raw)
    if not parsed:
        logger.warning("LLM devolvió respuesta no parseable: %r", raw[:200])
        return fields, 1

    for k, v in parsed.items():
        if k in missing_llm and isinstance(v, str) and v.strip():
            fields.set(k, v, FieldSource.LLM)

    return fields, 1
