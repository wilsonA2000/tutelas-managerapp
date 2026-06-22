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


def _is_garbage(v: str) -> bool:
    """True si el valor parece salida degenerada del LLM (bucle repetitivo / Unicode
    basura) que NO debe persistirse. Backstop por si el repeat_penalty no alcanza.
    Ej. reales: '1 1 1 1 1...', '_._  _ _ _ _', '].(  1  1  1...'."""
    s = (v or "").strip()
    if len(s) < 4:
        return False  # valores cortos (enums tipo "SI", "NO") son válidos
    compact = re.sub(r"\s+", "", s)
    if not compact:
        return True
    if re.search(r"(.)\1{5,}", compact):           # mismo char 6+ veces seguido
        return True
    if re.search(r"(.{2,8})\1{2,}", compact):      # subcadena/palabra repetida (CONTCONTCONT)
        return True
    from collections import Counter
    most = Counter(compact).most_common(1)[0][1]
    if most / len(compact) > 0.6:                  # dominado por un solo char
        return True
    alnum = sum(c.isalnum() for c in compact)
    if alnum / len(compact) < 0.3:                 # casi sin letras/dígitos
        return True
    # Sopa de símbolos: mucha puntuación/símbolos intercalados entre fragmentos cortos,
    # aunque queden letras sueltas (degeneración tipo '.AND__U1.IG_DE#._JCONT.J_IN' o
    # '¿ ** _ _ _ ¿ para ¿ ** ¿ donde'). El texto jurídico legítimo es casi todo letras +
    # separadores escasos (coma, punto, guion); >35% de no-alfanuméricos = basura.
    # Sopa de símbolos ('¿ ** _ _ _ ¿', '.AND__U1.IG_DE#', ',,,,,'): el texto jurídico real
    # tiene ≤10% de no-alfanuméricos (medido en c23/c415/c499-obs); la degeneración tiene
    # ≥35%. Umbral 0.30 con margen amplio. NO marca abreviaturas 'E.P.S./S.A.S.' (~20%),
    # ni elipsis, ni separadores '------', ni notas con '#'.
    nonalnum = sum(1 for ch in compact if not ch.isalnum())
    if nonalnum / len(compact) > 0.30:
        return True
    # Script no latino (CJK/cirílico/griego) → el '垒' de c499 (lo que el usuario vio "cirílico").
    if re.search(r"[Ͱ-ϿЀ-ӿ　-鿿가-힯]", s):
        return True
    return False


import urllib.request
LLM_URL = os.getenv("LLM_LOCAL_URL", "https://api.deepseek.com")  # DeepSeek API
# Proveedor externo (DeepSeek) — DESCONECTADO por default. Requiere DOS cosas a la vez:
# V9_ALLOW_DEEPSEEK=true (opt-in explícito del operador) Y V9_LLM_API_KEY seteada.
# Sin el flag, jamás se usa DeepSeek aunque haya key (2026-05-25, decisión de Wilson).
_ALLOW_DEEPSEEK = os.getenv("V9_ALLOW_DEEPSEEK", "false").lower() == "true"
_LLM_API_KEY = os.getenv("V9_LLM_API_KEY", "") if _ALLOW_DEEPSEEK else ""
_LLM_MODEL = os.getenv("LLM_LOCAL_MODEL_ID", "qwen3-4b-iuris")

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
_MAXLEN = {"asunto": 140, "accionados": 200, "vinculados": 200,
           "responsable_desacato": 120, "responsable_desacato_2": 120, "responsable_desacato_3": 120}

# Vocab SED de `asunto`: cuando gap_fill llena asunto (modo V9_LLM_SINGLE_CALL, el regex
# no clasificó), lo acota al mismo vocabulario controlado que usa el extractor por-campo
# → preserva el valor canónico (TRASLADO, REINTEGRO, …) en vez de texto libre.
try:
    from backend.cognition.legal_schema import SED_TEMA_MAPPING as _SED_TM
    _ASUNTO_VOCAB = []
    for _row in _SED_TM:
        _cat = _row[-1]
        if _cat and _cat not in _ASUNTO_VOCAB:
            _ASUNTO_VOCAB.append(_cat)
    if _ASUNTO_VOCAB:
        _ENUMS["asunto"] = _ASUNTO_VOCAB + ["SIN_DETERMINAR", ""]
except Exception:  # noqa: BLE001
    pass


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
#
# `pretensiones` se EXCLUYE a propósito (2026-06-01): es texto jurídico con valor
# probatorio que el jurado/abogados necesitan VERBATIM. Su extracción vive en
# field_extractor.extract_pretensiones_for_case (regex verbatim → localizador LLM
# verbatim). Si ambas rutas fallan, el campo queda VACÍO (ausencia honesta), NUNCA
# una paráfrasis del gap_fill. Ver field_extractor_pass.py (usa use_llm real, no fe_llm).
_LLM_FILLABLE = (
    "quien_impugno",
    "responsable_desacato",
    "decision_incidente",
    "responsable_desacato_2",
    "decision_incidente_2",
    "responsable_desacato_3",
    "decision_incidente_3",
    "asunto",
    "derecho_vulnerado",
    "accionados",
    "vinculados",
    "abogado_responsable",
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


# Instrucciones específicas por campo para el prompt enriquecido (3A).
# Cada entrada: una o dos líneas que guían al modelo para ese campo.
_FIELD_INSTRUCTIONS: dict[str, str] = {
    "accionante":        "Nombre completo. Si actúa personero → 'PERSONERÍA MUNICIPAL DE [MUNICIPIO]'. NUNCA incluir 'VS', 'Y OTROS', correos ni cédulas.",
    "accionados":        "Entidades/personas demandadas, separadas por coma. Casi siempre Secretaría de Educación de Santander.",
    "vinculados":        "Entidades vinculadas al proceso pero no accionadas directamente.",
    "derecho_vulnerado": "Derecho fundamental. En esta Secretaría casi siempre EDUCACION.",
    "asunto":            "1 línea ≤120 chars. Qué pide el accionante (ej. REINTEGRO DOCENTE, NOMBRAMIENTO).",
    "responsable_desacato": "Nombre completo del funcionario contra quien va el incidente de desacato.",
    "responsable_desacato_2": "Nombre del responsable del segundo incidente de desacato.",
    "responsable_desacato_3": "Nombre del responsable del tercer incidente de desacato.",
    "decision_incidente":   "SI (sancionado) / NO (archivado) / EN_TRAMITE (abierto).",
    "decision_incidente_2": "SI / NO / EN_TRAMITE para el segundo incidente.",
    "decision_incidente_3": "SI / NO / EN_TRAMITE para el tercer incidente.",
    "quien_impugno":     "ACCIONANTE / ACCIONADO / MINISTERIO_PUBLICO / AMBOS. La parte que interpuso el recurso de impugnación.",
    "abogado_responsable": "Nombre del abogado de la SED que firmó la respuesta (solo si hay RESPUESTA SED en el expediente).",
}

_PROMPT_TEMPLATE = """/no_think
Eres un extractor jurídico de tutelas colombianas (Gobernación de Santander).
Devuelve SOLO un JSON válido con los campos pedidos. Si no encuentras un valor → "".

{field_block}

REGLAS CRÍTICAS:
- Si el municipio del juzgado es Bucaramanga, Floridablanca, Girón, Barrancabermeja o Piedecuesta
  Y el accionado principal es la Secretaría de Educación de Santander → puede haber falta de legitimación pasiva.
- pretensiones: transcribir verbatim del escrito de tutela; NO tomar defensas ni respuestas de la SED.
- Si no encuentras el valor con certeza → devuelve cadena vacía.

Texto del expediente:
{text}

Responde SOLO JSON: {{"campo": "valor"}}"""


# --- Prompt V2 (KV-reuse): prefijo ESTABLE primero (idéntico entre casos → el server
# cachea su KV una vez), parte VARIABLE (qué campos + contexto) al final. El catálogo de
# instrucciones va completo y ordenado para que el prefijo sea byte-idéntico siempre. ---
_STABLE_PREFIX_V2 = (
    "/no_think\n"
    "Eres un extractor jurídico de tutelas colombianas (Gobernación de Santander).\n"
    "Devuelve SOLO un JSON válido con los campos pedidos. Si no encuentras un valor → \"\".\n\n"
    "REGLAS CRÍTICAS:\n"
    "- Si el municipio del juzgado es Bucaramanga, Floridablanca, Girón, Barrancabermeja o Piedecuesta\n"
    "  Y el accionado principal es la Secretaría de Educación de Santander → puede haber falta de legitimación pasiva.\n"
    "- pretensiones: transcribir verbatim del escrito de tutela; NO tomar defensas ni respuestas de la SED.\n"
    "- El contexto trae cada fragmento rotulado con [doc_type] y su sección; usa esa pista para ubicar el campo.\n"
    "- Si no encuentras el valor con certeza → devuelve cadena vacía.\n\n"
    "INSTRUCCIONES POR CAMPO (referencia):\n"
    + "\n".join(f"- {f}: {instr}" for f, instr in sorted(_FIELD_INSTRUCTIONS.items()))
)


def _build_prompt(missing: list[str], text: str) -> str:
    """Construye el prompt. V2 (env V9_PROMPT_V2=true): prefijo estable→KV-reuse, variable
    al final, contexto rotulado por doc_type/sección. V1 (default): comportamiento actual."""
    if os.getenv("V9_PROMPT_V2", "false").lower() == "true":
        miss = sorted(missing)  # orden determinista (no rompe el prefijo cacheado)
        return (
            _STABLE_PREFIX_V2
            + "\n\n=== EXTRAER AHORA solo estos campos ===\n" + ", ".join(miss)
            + "\n\n=== CONTEXTO (fragmentos relevantes del expediente) ===\n"
            + (text or "")[:_CONTEXT_CAP]
            + "\n\nResponde SOLO JSON con esos campos: {\"campo\": \"valor\"}"
        )
    # V1 (default): instrucciones solo de los campos faltantes, en medio del prompt.
    lines = [f"- {f}: {_FIELD_INSTRUCTIONS.get(f, 'extraer del texto')}" for f in missing]
    field_block = "Campos a extraer:\n" + "\n".join(lines)
    t = (text or "")[:_CONTEXT_CAP]
    return _PROMPT_TEMPLATE.format(field_block=field_block, text=t)


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
        # Sampling por env (default = greedy temp=0, comportamiento de producción).
        # Permite A/B del muestreo OFICIAL por modelo (Qwen recomienda temp 0.7/top_p 0.8/
        # top_k 20 y desaconseja greedy) sin redeploy.
        "max_tokens": int(os.getenv("V9_LLM_MAX_TOKENS", "400")),
        "temperature": float(os.getenv("V9_LLM_TEMPERATURE", "0")),
    }
    # Muestreo opcional adicional (solo si la env está presente → no altera el default).
    for _key, _env, _cast in (("top_p", "V9_LLM_TOP_P", float), ("top_k", "V9_LLM_TOP_K", int),
                              ("min_p", "V9_LLM_MIN_P", float),
                              ("presence_penalty", "V9_LLM_PRESENCE_PENALTY", float)):
        _v = os.getenv(_env)
        if _v is not None:
            body[_key] = _cast(_v)
    # cache_prompt: el server local (llama.cpp) reusa el KV del prompt entre la llamada
    # con schema y el reintento sin schema (mismo prompt) → no re-evalúa el contexto.
    # Solo en local; los proveedores externos rechazan params desconocidos.
    if not _LLM_API_KEY:
        body["cache_prompt"] = True
        # Anti-degeneración del 4B local: sin esto, al forzar campos `required` que no
        # están en el doc, el modelo emite basura repetitiva (Unicode/dígitos en bucle)
        # que además dispara fence timeouts en la iGPU. repeat_penalty corta el bucle.
        body["repeat_penalty"] = float(os.getenv("V9_LLM_REPEAT_PENALTY", "1.15"))
    # Constrained decoding. strict json_schema acota duro (enum+maxLength) y es la
    # config de producción para el 4B. Pero el 30B-A3B (MoE) degenera con strict
    # cuando se le fuerza a llenar campos `required` sin respuesta (emite Unicode
    # basura). `V9_LLM_SOFT_JSON=true` usa json_object suave → parseo con
    # _parse_json_loose. Ver bake-off 2026-05-21.
    if os.getenv("V9_LLM_SOFT_JSON", "false").lower() == "true":
        body["response_format"] = {"type": "json_object"}
    else:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "gap_fill", "schema": _build_schema(missing), "strict": True}}

    def _post(payload: dict) -> str:
        headers = {"Content-Type": "application/json"}
        if _LLM_API_KEY:  # proveedor externo (DeepSeek): requiere model + auth
            payload = {**payload, "model": _LLM_MODEL}
            headers["Authorization"] = f"Bearer {_LLM_API_KEY}"
        req = urllib.request.Request(LLM_URL + "/v1/chat/completions",
                                     data=json.dumps(payload).encode(),
                                     headers=headers)
        raw = urllib.request.urlopen(req, timeout=120).read().decode()
        return json.loads(raw)["choices"][0]["message"]["content"] or ""

    def _respawn_if_local_down(exc: Exception) -> bool:
        """Motor = DeepSeek API (nube): no hay server local que relanzar."""
        return False

    try:
        return _post(body)
    except Exception as e:
        if _respawn_if_local_down(e):
            try:
                return _post(body)
            except Exception as e_r:  # noqa: BLE001
                logger.warning("LLM tras respawn falló (%s); reintento sin schema", str(e_r)[:120])
        else:
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


# 3B: Afinidad campo → tipos de doc más relevantes para buscarlo.
# Para cada campo faltante se incluye texto de esos doc_types prioritariamente.
_FIELD_DOC_AFFINITY: dict[str, list[str]] = {
    "accionados":             ["DEMANDA_TUTELA", "ESCRITO_TUTELA", "PDF_AUTO_ADMISORIO", "AUTO_ADMISORIO"],
    "vinculados":             ["DEMANDA_TUTELA", "ESCRITO_TUTELA", "AUTO_VINCULA"],
    "derecho_vulnerado":      ["DEMANDA_TUTELA", "ESCRITO_TUTELA"],
    "asunto":                 ["DEMANDA_TUTELA", "ESCRITO_TUTELA", "RESPUESTA", "DOCX_RESPUESTA", "RESPUESTA_SED"],
    "responsable_desacato":   ["PDF_INCIDENTE", "AUTO_INCIDENTE", "INCIDENTE_DESACATO"],
    "responsable_desacato_2": ["PDF_INCIDENTE", "AUTO_INCIDENTE"],
    "responsable_desacato_3": ["PDF_INCIDENTE", "AUTO_INCIDENTE"],
    "decision_incidente":     ["AUTO_INCIDENTE", "PDF_INCIDENTE"],
    "decision_incidente_2":   ["AUTO_INCIDENTE", "PDF_INCIDENTE"],
    "decision_incidente_3":   ["AUTO_INCIDENTE", "PDF_INCIDENTE"],
    "quien_impugno":          ["PDF_IMPUGNACION", "PDF_SENTENCIA_2DA", "DOCX_IMPUGNACION"],
    "abogado_responsable":    ["RESPUESTA", "DOCX_RESPUESTA", "RESPUESTA_SED"],
}

# Chars máx del contexto LLM por caso. DeepSeek = 64K tokens ≈ ~200K chars; reservando ~8K
# tokens de salida + scaffolding quedan ~50K tokens de entrada ≈ ~170K chars. Ponemos 150K
# para aprovechar la ventana al máximo dejando margen (antes 8k=4B, luego 40k tímido).
# env-tunable V9_LLM_CONTEXT_CAP. (Para >1M tokens habría que cambiar a Gemini, otro proveedor.)
_CONTEXT_CAP = int(os.getenv("V9_LLM_CONTEXT_CAP", "150000"))


def build_context_for_fields(missing: list[str], doc_texts: dict[str, str]) -> str:
    """Construye texto de contexto para el LLM seleccionando docs por afinidad.

    `doc_texts`: dict {doc_type: texto_cabeza_cola}. Puede haber varios docs del
    mismo tipo — se separan con '---'.

    Para cada campo faltante se incluyen los tipos de doc con mayor afinidad primero.
    Se llena el presupuesto de `_CONTEXT_CAP` chars sin repetir texto ya incluido.
    """
    if not doc_texts:
        return ""

    # Ordenar tipos de doc por relevancia para los campos faltantes
    type_relevance: dict[str, int] = {}
    for field in missing:
        for rank, dtype in enumerate(_FIELD_DOC_AFFINITY.get(field, [])):
            type_relevance[dtype] = max(type_relevance.get(dtype, 0), len(missing) - rank)

    # Ordenar por relevancia desc, luego alpha para determinismo
    ordered = sorted(doc_texts.keys(),
                     key=lambda dt: (-type_relevance.get(dt, 0), dt))

    parts: list[str] = []
    used = 0
    for dtype in ordered:
        snippet = (doc_texts[dtype] or "").strip()
        if not snippet:
            continue
        remaining = _CONTEXT_CAP - used
        if remaining <= 200:
            break
        chunk = snippet[:remaining]
        parts.append(chunk)
        used += len(chunk) + 5  # +5 for separator

    return "\n---\n".join(parts)


def run(fields: ExtractedFields, full_text: str,
        doc_texts: Optional[dict[str, str]] = None) -> tuple[ExtractedFields, int]:
    """Llena campos faltantes con UNA llamada multi-campo. Retorna (fields, llm_calls).

    `full_text`: texto de fallback si `doc_texts` no se provee.
    `doc_texts`: dict {doc_type: texto} para selección por afinidad (3B).
    """
    if _llm_disabled():
        return fields, 0

    missing_all = fields.missing_fields()
    missing_llm = [f for f in missing_all if f in _LLM_FILLABLE]
    # Aplicar consistencia: no rellenar hijos de flags=NO
    missing_llm = _filter_by_consistency(fields, missing_llm)
    if not missing_llm:
        return fields, 0

    # 3B: usar texto con afinidad por campo si está disponible; fallback a full_text
    if doc_texts:
        context_text = build_context_for_fields(missing_llm, doc_texts)
    else:
        context_text = full_text or ""

    if not context_text or len(context_text.strip()) < 100:
        logger.info("LLM skip: texto insuficiente (%d chars)", len(context_text))
        return fields, 0

    prompt = _build_prompt(missing_llm, context_text)
    raw = _call_llm(prompt, missing_llm)
    if not raw:
        return fields, 0  # falló silencioso, no hay llm_call exitoso

    parsed = _parse_json_loose(raw)
    if not parsed:
        logger.warning("LLM devolvió respuesta no parseable: %r", raw[:200])
        return fields, 1

    for k, v in parsed.items():
        if k in missing_llm and isinstance(v, str) and v.strip():
            if _is_garbage(v):
                logger.warning("LLM campo %s descartado por basura: %r", k, v[:60])
                continue
            fields.set(k, v, FieldSource.LLM)

    return fields, 1
