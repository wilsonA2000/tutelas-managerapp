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
    text = (text or "")[:8000]  # cap por contexto
    return _PROMPT.format(fields=", ".join(missing), text=text)


def _llm_disabled() -> bool:
    return os.getenv("V9_DISABLE_LLM", "false").lower() == "true"


def _call_llm(prompt: str) -> Optional[str]:
    """Llama al LLM local. Devuelve raw string o None si falla."""
    try:
        from backend.extraction.ai_extractor import _call_local
    except ImportError as e:
        logger.warning("ai_extractor no importable: %s", e)
        return None

    msgs = [
        {"role": "system", "content": "Eres un asistente que extrae datos jurídicos. Responde solo JSON."},
        {"role": "user", "content": prompt},
    ]
    try:
        raw, _, _ = _call_local(msgs, "qwen3-4b-iuris", max_tokens=512)
        return raw
    except Exception as e:
        logger.warning("LLM call falló: %s", str(e)[:200])
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
    raw = _call_llm(prompt)
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
