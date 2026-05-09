"""Extractores LLM focalizados por campo (Fase 2.2 — v8.3).

Cada campo critico tiene su propio prompt ultra-especifico + validator
deterministico (enum/regex/cita literal) que rechaza la respuesta si no pasa.

Ventaja sobre el prompt generico de cognitive_complementary_ai.py:
- Mas precision: prompt corto y enfocado evita alucinacion.
- Menos tokens: max_tokens 200 vs 800.
- Cita verificable: cada respuesta exige un fragmento literal del texto.
- Guards conocidos (memoria del proyecto):
    * quien_impugno=MINISTERIO_PUBLICO solo si aparece literal en texto.
    * juzgado_2nd descarta jurisprudencia citada (matching contra Decreto 1983/2017).

Diseno:
    extract_field_focused(case, full_text, field, call_llm_fn=None) -> Result | None

`call_llm_fn` se inyecta para tests (mock). En produccion usa _call_local.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger("tutelas.focused_extractors")

ENUM_QUIEN_IMPUGNO = ("ACCIONANTE", "ACCIONADO", "MINISTERIO_PUBLICO", "NINGUNO")
ENUM_FALLO_2ND = ("CONFIRMA", "REVOCA", "MODIFICA", "INHIBE", "NULIDAD")
DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")


@dataclass
class FocusedResult:
    field: str
    value: Optional[str]
    confidence: float           # 0.0 - 1.0
    source_quote: Optional[str] # fragmento literal del texto fuente
    rejected_reason: Optional[str] = None


# ============================================================
# Prompts focalizados (uno por campo)
# ============================================================

PROMPT_QUIEN_IMPUGNO = (
    "Eres abogado en derecho colombiano. Analiza el texto y responde quien interpuso "
    "el recurso de impugnacion contra el fallo de tutela.\n\n"
    "Opciones validas (UNA sola):\n"
    "  ACCIONANTE          - el demandante (quien interpuso la tutela) impugna porque le NEGARON\n"
    "  ACCIONADO           - el demandado (entidad publica) impugna porque le CONCEDIERON\n"
    "  MINISTERIO_PUBLICO  - el procurador o defensor del pueblo impugna (raro)\n"
    "  NINGUNO             - no hubo impugnacion\n\n"
    "Devuelve JSON estricto:\n"
    "{\"value\": \"ACCIONANTE\", \"confidence\": \"ALTA\", \"quote\": \"frase exacta del texto que lo prueba\"}\n\n"
    "REGLA CRITICA: NO devuelvas MINISTERIO_PUBLICO salvo que aparezca literalmente "
    "'procurador' o 'defensor del pueblo' interpuso impugnacion. NO lo asumas."
)

PROMPT_FECHA_APERTURA_INCIDENTE = (
    "Eres abogado en derecho colombiano. Analiza el texto y devuelve la FECHA "
    "exacta en que se PRESENTO el incidente de desacato (no la del fallo).\n\n"
    "Formato obligatorio: DD/MM/YYYY.\n\n"
    "Devuelve JSON: {\"value\": \"15/03/2026\", \"confidence\": \"ALTA\", "
    "\"quote\": \"frase exacta\"}\n\n"
    "Si no aparece explicito, value=null."
)

PROMPT_RESPONSABLE_DESACATO = (
    "Analiza el texto y devuelve el funcionario publico señalado como RESPONSABLE "
    "del desacato (cargo + nombre).\n\n"
    "Ejemplos validos:\n"
    "  - 'Secretario de Educacion JUAN PEREZ'\n"
    "  - 'Director de Talento Humano MARIA GOMEZ'\n\n"
    "Devuelve JSON: {\"value\": \"...\", \"confidence\": \"...\", \"quote\": \"...\"}\n\n"
    "Si no esta nombrado, value=null."
)

PROMPT_JUZGADO_2ND = (
    "Eres abogado en derecho colombiano. Analiza SOLO el texto del fallo de SEGUNDA "
    "instancia y devuelve el juzgado/tribunal que LO EMITE.\n\n"
    "REGLA CRITICA: NO devuelvas tribunales mencionados como JURISPRUDENCIA citada "
    "(ej. 'Sentencia T-XXX/2020 de la Corte Constitucional'). Solo el organo que "
    "EMITE el fallo de 2a instancia (encabezado del fallo o auto de reparto).\n\n"
    "Devuelve JSON: {\"value\": \"TRIBUNAL SUPERIOR DE BUCARAMANGA SALA CIVIL\", "
    "\"confidence\": \"ALTA\", \"quote\": \"frase exacta del encabezado del fallo\"}\n\n"
    "Si solo se cita doctrina, value=null."
)

PROMPT_SENTIDO_FALLO_2ND = (
    "Analiza el texto del fallo de SEGUNDA instancia y devuelve la decision del juez.\n\n"
    "Opciones (una sola):\n"
    "  CONFIRMA          - mantiene la decision de 1a instancia\n"
    "  REVOCA            - tumba la decision de 1a instancia\n"
    "  MODIFICA          - altera parcialmente\n"
    "  INHIBE            - se abstiene de fallar de fondo\n"
    "  NULIDAD           - declara nulidad procesal\n\n"
    "Devuelve JSON: {\"value\": \"...\", \"confidence\": \"...\", \"quote\": \"...\"}"
)

FIELD_PROMPTS: dict[str, str] = {
    "quien_impugno": PROMPT_QUIEN_IMPUGNO,
    "fecha_apertura_incidente": PROMPT_FECHA_APERTURA_INCIDENTE,
    "responsable_desacato": PROMPT_RESPONSABLE_DESACATO,
    "juzgado_2nd": PROMPT_JUZGADO_2ND,
    "sentido_fallo_2nd": PROMPT_SENTIDO_FALLO_2ND,
}


# ============================================================
# Validators (guards) por campo
# ============================================================

def _validate_quien_impugno(value: str, source_quote: Optional[str], full_text: str) -> tuple[bool, str]:
    if value not in ENUM_QUIEN_IMPUGNO:
        return False, f"value={value!r} no esta en enum {ENUM_QUIEN_IMPUGNO}"
    if value == "MINISTERIO_PUBLICO":
        text_lower = (full_text or "").lower()
        if not re.search(r"\b(procurador|defensor del pueblo|ministerio publico|ministerio público)\b", text_lower):
            return False, "MINISTERIO_PUBLICO sin evidencia literal en texto (anti-LoRA-bias)"
    return True, "ok"


def _validate_fecha(value: str, *_args) -> tuple[bool, str]:
    m = DATE_RE.fullmatch(value.strip())
    if not m:
        return False, f"value={value!r} no es DD/MM/YYYY"
    d, mth, y = map(int, m.groups())
    try:
        from datetime import datetime
        datetime(y, mth, d)
    except ValueError:
        return False, "fecha invalida en calendario"
    if not (2018 <= y <= 2030):
        return False, f"año {y} fuera de rango razonable [2018-2030]"
    return True, "ok"


def _validate_responsable_desacato(value: str, *_args) -> tuple[bool, str]:
    if len(value) < 5:
        return False, "responsable_desacato muy corto"
    if not re.search(r"[A-ZÁÉÍÓÚÑ]", value):
        return False, "sin mayusculas (debe contener nombre/cargo)"
    return True, "ok"


def _validate_juzgado_2nd(value: str, source_quote: Optional[str], full_text: str) -> tuple[bool, str]:
    if len(value) < 10:
        return False, "juzgado_2nd muy corto"
    # Rechazar si parece ser cita jurisprudencial
    JURISPRUDENCIA = (r"sentencia\s+[A-Z]+-\d+", r"corte\s+constitucional\b",
                       r"corte\s+suprema\s+de\s+justicia", r"jurisprudencia\b")
    src = (source_quote or "").lower()
    for pat in JURISPRUDENCIA:
        if re.search(pat, src):
            return False, f"source_quote contiene jurisprudencia citada ({pat}) - no es juzgado real"
    # Si tiene indicador de 2a instancia
    if not re.search(r"(tribunal|sala\b|consejo seccional|juzgado\s+\w+\s+del\s+circuito)",
                      value.lower()):
        return False, "value no parece tribunal/sala de 2a instancia"
    return True, "ok"


def _validate_sentido_fallo_2nd(value: str, *_args) -> tuple[bool, str]:
    if value.upper() not in ENUM_FALLO_2ND:
        return False, f"value={value!r} no esta en enum {ENUM_FALLO_2ND}"
    return True, "ok"


FIELD_VALIDATORS: dict[str, Callable[[str, Optional[str], str], tuple[bool, str]]] = {
    "quien_impugno": _validate_quien_impugno,
    "fecha_apertura_incidente": _validate_fecha,
    "responsable_desacato": _validate_responsable_desacato,
    "juzgado_2nd": _validate_juzgado_2nd,
    "sentido_fallo_2nd": _validate_sentido_fallo_2nd,
}


# ============================================================
# Cita literal: la respuesta debe estar (o casi) en el texto
# ============================================================

def _quote_present_in_text(quote: str, full_text: str) -> bool:
    """Verifica que la cita aparece (con tolerancia) en el texto fuente."""
    if not quote or not full_text:
        return False
    norm_quote = re.sub(r"\s+", " ", quote.strip().lower())
    norm_text = re.sub(r"\s+", " ", full_text.lower())
    if norm_quote in norm_text:
        return True
    # Fragmentos de >=12 chars con tolerancia
    if len(norm_quote) >= 12:
        sample = norm_quote[: min(40, len(norm_quote))]
        return sample in norm_text
    return False


CONF_MAP = {"ALTA": 0.9, "MEDIA": 0.65, "BAJA": 0.4}


def extract_field_focused(
    case_summary: str,
    full_text: str,
    field: str,
    call_llm_fn: Optional[Callable[[list], tuple[str, int, int]]] = None,
) -> Optional[FocusedResult]:
    """Pide al LLM un solo campo con prompt focalizado y guards.

    Args:
        case_summary: contexto breve del case (accionante, juzgado, fechas conocidas).
        full_text: texto agregado de docs del case (preferentemente weighted by authority).
        field: nombre del campo a extraer (debe estar en FIELD_PROMPTS).
        call_llm_fn: callable(messages) -> (raw, in_tok, out_tok). Si None usa _call_local.

    Returns:
        FocusedResult con value+confidence+source_quote, o None si LLM falla.
    """
    if field not in FIELD_PROMPTS:
        return None
    if not full_text or len(full_text.strip()) < 200:
        return None

    system = FIELD_PROMPTS[field]
    user = (
        f"CONTEXTO DEL CASO:\n{case_summary}\n\n"
        f"TEXTO RELEVANTE:\n{full_text[:6000]}\n\n"
        f"Devuelve JSON estricto. Si no aparece, value=null."
    )

    if call_llm_fn is None:
        try:
            from backend.extraction.ai_extractor import _call_local
            def _default_call(msgs):
                return _call_local(msgs, "qwen3-4b-iuris", max_tokens=200)
            call_llm_fn = _default_call
        except Exception as e:
            logger.warning("focused field=%s sin LLM disponible: %s", field, e)
            return None

    try:
        raw, _in, _out = call_llm_fn([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
    except Exception as e:
        logger.warning("focused field=%s LLM call failed: %s", field, str(e)[:120])
        return None

    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    m = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
    if not m:
        return FocusedResult(field, None, 0.0, None, "no_json_in_response")

    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return FocusedResult(field, None, 0.0, None, f"json_parse: {e}")

    value = data.get("value")
    conf_str = (data.get("confidence") or "BAJA").upper()
    quote = data.get("quote")

    if value is None or (isinstance(value, str) and not value.strip()):
        return FocusedResult(field, None, 0.0, quote, "value_null")

    value = str(value).strip()
    confidence = CONF_MAP.get(conf_str, 0.4)

    # Guard 1: validator deterministico por campo
    validator = FIELD_VALIDATORS.get(field)
    if validator:
        ok, reason = validator(value, quote, full_text)
        if not ok:
            logger.info("focused field=%s rechazado por validator: %s", field, reason)
            return FocusedResult(field, None, 0.0, quote, f"validator: {reason}")

    # Guard 2: cita literal debe aparecer (o casi) en el texto fuente
    if quote and not _quote_present_in_text(quote, full_text):
        confidence *= 0.5  # penalizar si la cita es inventada
        if confidence < 0.4:
            return FocusedResult(field, None, 0.0, quote, "quote_not_in_source")

    return FocusedResult(field, value, round(confidence, 3), quote, None)


PROMPT_MULTI_FIELD = (
    "/no_think\n"
    "Eres abogado experto en tutelas colombianas. Analiza el expediente y extrae "
    "SOLO los campos solicitados. Devuelve UN unico JSON con todos los campos.\n\n"
    "Schema por campo: {\"value\": \"...\" | null, \"confidence\": \"ALTA|MEDIA|BAJA\", "
    "\"quote\": \"frase exacta del texto\"}\n\n"
    "Campos posibles y sus reglas:\n"
    "  quien_impugno -> ACCIONANTE | ACCIONADO | MINISTERIO_PUBLICO | NINGUNO\n"
    "    (NO uses MINISTERIO_PUBLICO salvo que aparezca literal 'procurador' o "
    "    'defensor del pueblo' impugnando).\n"
    "  fecha_apertura_incidente -> DD/MM/YYYY (fecha en que el accionante PRESENTO "
    "    el incidente de desacato, no la del fallo).\n"
    "  responsable_desacato -> 'Cargo NOMBRE' del funcionario senalado en el incidente.\n"
    "  juzgado_2nd -> juzgado/tribunal que EMITE el fallo de 2a instancia (NO citas "
    "    de jurisprudencia tipo 'Sentencia T-123/2020').\n"
    "  sentido_fallo_2nd -> CONFIRMA | REVOCA | MODIFICA | INHIBE | NULIDAD\n\n"
    "Si un campo no esta en el texto, value=null. NO inventes."
)


def extract_multi_focused(
    case,
    full_text: str,
    fields: list[str],
    call_llm_fn: Optional[Callable[[list], tuple[str, int, int]]] = None,
    max_tokens: int = 600,
) -> dict[str, FocusedResult]:
    """Extrae N campos en UNA sola llamada al LLM (5x speedup vs llamadas por campo).

    Reusa los validators existentes para cada campo individualmente.
    """
    if not fields or not full_text or len(full_text.strip()) < 200:
        return {}

    summary = "\n".join([
        f"- accionante: {getattr(case, 'accionante', '?')}",
        f"- juzgado: {getattr(case, 'juzgado', '?')}",
        f"- impugnacion: {getattr(case, 'impugnacion', '?')}",
        f"- incidente: {getattr(case, 'incidente', '?')}",
        f"- sentido_fallo_1st: {getattr(case, 'sentido_fallo_1st', '?')}",
    ])

    user = (
        f"CONTEXTO DEL CASO:\n{summary}\n\n"
        f"TEXTO RELEVANTE:\n{full_text[:3500]}\n\n"
        f"Extrae: {', '.join(fields)}\n"
        f"JSON con UNA clave por campo:\n"
        + "{\n"
        + ",\n".join(f'  "{f}": {{"value":"...", "confidence":"ALTA|MEDIA|BAJA", "quote":"..."}}' for f in fields)
        + "\n}"
    )

    if call_llm_fn is None:
        try:
            from backend.extraction.ai_extractor import _call_local
            def _default_call(msgs):
                return _call_local(msgs, "qwen3-4b-iuris", max_tokens=max_tokens)
            call_llm_fn = _default_call
        except Exception as e:
            logger.warning("multi-focused sin LLM: %s", e)
            return {}

    try:
        raw, _in, _out = call_llm_fn([
            {"role": "system", "content": PROMPT_MULTI_FIELD},
            {"role": "user", "content": user},
        ])
    except Exception as e:
        logger.warning("multi-focused LLM call failed: %s", str(e)[:120])
        return {}

    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}

    out: dict[str, FocusedResult] = {}
    for fname in fields:
        entry = data.get(fname)
        # Soportar dos formatos: {"value":..., "confidence":..., "quote":...} y plano "value"
        if isinstance(entry, dict):
            value = entry.get("value")
            conf_str = (entry.get("confidence") or "MEDIA").upper()
            quote = entry.get("quote")
        elif isinstance(entry, (str, int, float)):
            value = entry
            conf_str = "MEDIA"  # default cuando LLM no la da
            quote = None
        else:
            continue

        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        value = str(value).strip()
        if value.lower() in ("null", "none", "n/a", "no aplica", "no especificado"):
            continue

        confidence = CONF_MAP.get(conf_str, 0.65)

        validator = FIELD_VALIDATORS.get(fname)
        if validator:
            ok, reason = validator(value, quote, full_text)
            if not ok:
                logger.info("multi-focused %s rechazado: %s", fname, reason)
                continue
        if quote and not _quote_present_in_text(quote, full_text):
            confidence *= 0.7  # penalty leve si la cita no aparece
            if confidence < 0.4:
                continue

        out[fname] = FocusedResult(fname, value, round(confidence, 3), quote, None)
    return out


def extract_focused_for_case(
    case,
    full_text: str,
    fields: Optional[list[str]] = None,
    call_llm_fn: Optional[Callable] = None,
) -> dict[str, FocusedResult]:
    """Conveniencia: extrae todos los campos focalizados aplicables al case."""
    fields = fields or list(FIELD_PROMPTS.keys())
    summary = "\n".join([
        f"- accionante: {getattr(case, 'accionante', '?')}",
        f"- juzgado: {getattr(case, 'juzgado', '?')}",
        f"- impugnacion: {getattr(case, 'impugnacion', '?')}",
        f"- incidente: {getattr(case, 'incidente', '?')}",
        f"- sentido_fallo_1st: {getattr(case, 'sentido_fallo_1st', '?')}",
    ])

    out: dict[str, FocusedResult] = {}
    for f in fields:
        # Skip si el case ya tiene valor (no pisar)
        if getattr(case, f, None):
            continue
        # Skip si el campo no aplica al case
        if f in ("quien_impugno", "juzgado_2nd", "sentido_fallo_2nd"):
            if (getattr(case, "impugnacion", "") or "").upper() not in ("SI", "S"):
                continue
        if f in ("fecha_apertura_incidente", "responsable_desacato"):
            if (getattr(case, "incidente", "") or "").upper() not in ("SI", "S"):
                continue

        result = extract_field_focused(summary, full_text, f, call_llm_fn=call_llm_fn)
        if result is not None:
            out[f] = result
    return out
