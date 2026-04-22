"""Extractor multi-proveedor de campos usando IA (DeepSeek primary, Anthropic Claude fallback).

Providers legacy eliminados en v5.4 (Gemini, OpenAI, HuggingFace, Cerebras, Groq).
Histórico de llamadas Gemini (297) preservado en tabla token_usage como audit trail.
"""

import json
import time
import os
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from dotenv import load_dotenv

# Cargar .env para que os.getenv() funcione en todos los contextos
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

import logging
_logger = logging.getLogger("tutelas.extraction")


# ============================================================
# Configuracion de proveedores
# ============================================================

# Proveedor activo (se puede cambiar en runtime) — DeepSeek por defecto
_active_provider = "deepseek"
_active_model = "deepseek-chat"

# Catalogo de proveedores y modelos con precios (USD por 1M tokens)
PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek",
        "models": {
            "deepseek-chat": {
                "label": "DeepSeek V3.2 (Ultra barato)",
                "input_price": 0.28,
                "output_price": 0.42,
                "max_tokens": 8192,
                "context_window": 128000,
                "needs_chunking": False,
                "multimodal": False,
                "best_for": ["extraction", "general"],
            },
            "deepseek-reasoner": {
                "label": "DeepSeek Reasoner (Thinking)",
                "input_price": 0.28,
                "output_price": 0.42,
                "max_tokens": 64000,
                "context_window": 128000,
                "needs_chunking": False,
                "multimodal": False,
                "best_for": ["complex_reasoning", "legal_analysis"],
            },
        },
        "env_key": "DEEPSEEK_API_KEY",
    },
    "anthropic": {
        "name": "Claude (Anthropic)",
        "models": {
            "claude-haiku-4-5-20251001": {
                "label": "Claude Haiku 4.5",
                "input_price": 1.00,
                "output_price": 5.00,
                "max_tokens": 4096,
                "context_window": 200000,
                "needs_chunking": False,
                "multimodal": False,
                "best_for": ["extraction", "general", "complex_reasoning", "legal_analysis"],
            },
        },
        "env_key": "ANTHROPIC_API_KEY",
    },
}


def get_active_provider() -> tuple[str, str]:
    """Retorna (provider_id, model_id) activo."""
    return _active_provider, _active_model


def set_active_provider(provider: str, model: str):
    """Cambiar proveedor y modelo activo."""
    global _active_provider, _active_model
    if provider not in PROVIDERS:
        raise ValueError(f"Proveedor '{provider}' no soportado. Opciones: {list(PROVIDERS.keys())}")
    if model not in PROVIDERS[provider]["models"]:
        raise ValueError(f"Modelo '{model}' no disponible para {provider}. Opciones: {list(PROVIDERS[provider]['models'].keys())}")
    _active_provider = provider
    _active_model = model


def get_available_providers() -> list[dict]:
    """Lista de proveedores disponibles con sus modelos y estado de configuracion."""
    result = []
    for pid, pinfo in PROVIDERS.items():
        api_key = os.getenv(pinfo["env_key"], "")
        models = []
        for mid, minfo in pinfo["models"].items():
            models.append({
                "id": mid,
                "label": minfo["label"],
                "input_price": minfo["input_price"],
                "output_price": minfo["output_price"],
                "context_window": minfo["context_window"],
            })
        result.append({
            "id": pid,
            "name": pinfo["name"],
            "configured": bool(api_key),
            "active": pid == _active_provider,
            "models": models,
        })
    return result


def get_model_config() -> dict:
    """Config del modelo activo."""
    return PROVIDERS[_active_provider]["models"][_active_model]


# ============================================================
# System Prompt (compartido por todos los proveedores)
# ============================================================

def _load_prompt(filename: str) -> str:
    """Cargar prompt desde archivo externo en backend/prompts/."""
    prompt_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")
    path = os.path.join(prompt_dir, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


SYSTEM_PROMPT = _load_prompt("extraction.txt")


# ============================================================
# Dataclasses de resultado
# ============================================================

@dataclass
class AIFieldResult:
    value: str
    confidence: str  # ALTA / MEDIA / BAJA
    source: str  # nombre del archivo fuente


@dataclass
class AIExtractionResult:
    fields: dict[str, AIFieldResult] = field(default_factory=dict)
    raw_response: str = ""
    error: str | None = None
    tokens_input: int = 0
    tokens_output: int = 0
    tokens_used: int = 0  # total (input + output)
    provider: str = ""
    model: str = ""
    duration_ms: int = 0
    chunks_used: int = 1


# ============================================================
# Llamadas a cada proveedor
# ============================================================

def _call_anthropic(messages: list[dict], model: str, max_tokens: int = 4096) -> tuple[str, int, int]:
    """Llamar a Anthropic Claude API."""
    import anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    client = anthropic.Anthropic(api_key=api_key)

    # Anthropic usa system como parametro separado
    system_msg = ""
    user_msgs = []
    for m in messages:
        if m["role"] == "system":
            system_msg = m["content"]
        else:
            user_msgs.append(m)

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_msg,
        messages=user_msgs,
    )
    text = response.content[0].text
    inp = response.usage.input_tokens
    out = response.usage.output_tokens
    return text, inp, out


def _call_deepseek(messages: list[dict], model: str, max_tokens: int = 4096) -> tuple[str, int, int]:
    """Llamar a DeepSeek API (compatible con OpenAI SDK)."""
    from openai import OpenAI
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.1,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    text = response.choices[0].message.content
    inp = response.usage.prompt_tokens if response.usage else 0
    out = response.usage.completion_tokens if response.usage else 0
    return text, inp, out


# Dispatch table
_CALLERS = {
    "anthropic": _call_anthropic,
    "deepseek": _call_deepseek,
}


def _call_with_retry(provider: str, messages: list[dict], model: str,
                     max_tokens: int = 4096, max_retries: int = 5,
                     fallback_provider: str = None, fallback_model: str = None) -> tuple[str, int, int]:
    """Llamar al proveedor con retry exponencial + jitter.

    Retry strategy:
    - Exponential backoff: 5s, 10s, 20s, 40s, 60s (capped)
    - Jitter: +0-30% random para evitar thundering herd
    - Retriable: rate limit (429), server errors (5xx), connection errors
    - Non-retriable: payload too large (413), context overflow
    - On final retry exhaustion: try fallback provider once before failing
    """
    import random

    caller = _CALLERS.get(provider)
    if not caller:
        raise ValueError(f"Proveedor '{provider}' no implementado")

    # Errores que NO se deben reintentar
    NON_RETRIABLE = ("413", "payload", "too large", "context_length", "too long", "invalid_api_key", "authentication")
    # Errores retriable (rate limit, server errors, conexion)
    RETRIABLE_STRINGS = ("429", "rate", "overloaded", "503", "502", "500", "unavailable", "service", "server_error")
    RETRIABLE_TYPES = (ConnectionError, TimeoutError, OSError)

    last_error = None
    for attempt in range(max_retries):
        try:
            return caller(messages, model, max_tokens)
        except RETRIABLE_TYPES as e:
            last_error = e
            base_wait = min(60, 5 * (2 ** attempt))
            jitter = random.uniform(0, base_wait * 0.3)
            wait = base_wait + jitter
            _logger.warning("Retry %d/%d %s/%s: %s (esperando %.1fs)", attempt + 1, max_retries, provider, model, type(e).__name__, wait)
            time.sleep(wait)
            continue
        except Exception as e:
            error_str = str(e).lower()
            # No reintentar errores permanentes
            if any(s in error_str for s in NON_RETRIABLE):
                raise
            # Reintentar errores temporales
            if any(s in error_str for s in RETRIABLE_STRINGS):
                # Reportar rate limit al Smart Router
                if "429" in error_str or "rate" in error_str:
                    try:
                        from backend.agent.smart_router import report_rate_limit
                        report_rate_limit(provider)
                    except Exception:
                        pass
                last_error = e
                base_wait = min(60, 5 * (2 ** attempt))
                jitter = random.uniform(0, base_wait * 0.3)
                wait = base_wait + jitter
                _logger.warning("Retry %d/%d %s/%s: %s (esperando %.1fs)", attempt + 1, max_retries, provider, model, str(e)[:80], wait)
                time.sleep(wait)
                continue
            raise

    # Reintentos agotados — intentar fallback provider si existe
    if fallback_provider and fallback_model:
        fb_caller = _CALLERS.get(fallback_provider)
        if fb_caller:
            _logger.warning("Retries agotados en %s, intentando fallback %s/%s", provider, fallback_provider, fallback_model)
            try:
                return fb_caller(messages, fallback_model, max_tokens)
            except Exception as fb_e:
                _logger.error("Fallback %s tambien fallo: %s", fallback_provider, str(fb_e)[:100])

    raise Exception(f"Rate limit de {provider}: reintentos agotados tras {max_retries} intentos. Ultimo error: {str(last_error)[:100]}")


# ============================================================
# Helper: parsear JSON de IA (reutilizable)
# ============================================================

def _parse_ai_json(raw: str) -> dict[str, AIFieldResult]:
    """Parsear JSON de respuesta de IA. Intenta reparar JSON truncado."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Intentar reparar JSON truncado
        fixed = raw.rstrip()
        open_braces = fixed.count('{') - fixed.count('}')
        last_comma = fixed.rfind(',')
        if last_comma > 0 and open_braces > 0:
            fixed = fixed[:last_comma]
        fixed += '}' * max(0, open_braces)
        data = json.loads(fixed)  # Si falla aqui, propaga la excepcion

    fields_data = data.get("fields", data)
    result = {}
    for field_name, info in fields_data.items():
        if isinstance(info, dict):
            value = str(info.get("value", "")).strip()
            confidence = info.get("confidence", "MEDIA")
            source = info.get("source", "")
        elif isinstance(info, str):
            value = info.strip()
            confidence = "MEDIA"
            source = ""
        else:
            continue
        if value:
            result[field_name] = AIFieldResult(value=value, confidence=confidence, source=source)
    return result


# ============================================================
# Heuristica: PDFs criticos reciben trato preferente en el prompt
# (no se truncan aunque excedan el limite textual habitual)
# ============================================================

CRITICAL_KEYWORDS = {"auto", "admite", "avoca", "sentencia", "fallo", "impugn",
                     "incidente", "desacato", "forest", "respuesta", "rta", "escrito"}


def _is_critical_pdf(filename: str) -> bool:
    """Verificar si un PDF es critico (auto admisorio, sentencia, etc.)."""
    name = filename.lower()
    return any(kw in name for kw in CRITICAL_KEYWORDS)


def _rad_corto_from_23(rad23: str | None) -> str:
    """F3: derivar rad_corto (YYYY-NNNNN) del rad23 oficial. Devuelve '' si no valida."""
    if not rad23:
        return ""
    import re as _re
    digits = _re.sub(r"\D", "", rad23)
    m = _re.search(r"(20\d{2})(\d{5})(\d{2})$", digits)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return ""


def _build_anti_contamination_block(folder_name: str, radicado_oficial: str = "") -> str:
    """F3 (v5.0): construir bloque de restriccion con radicado oficial cuando exista.
    Cuando hay rad23 valido, instruye a la IA a usar el RADICADO OFICIAL en campos
    narrativos (observaciones, asunto) en lugar del folder_name literal — que puede
    contener el FOREST o "[PENDIENTE REVISION]".
    """
    rc = _rad_corto_from_23(radicado_oficial)
    if rc and radicado_oficial:
        return (
            f"CARPETA FISICA: {folder_name}\n"
            f"RADICADO OFICIAL DEL CASO: {radicado_oficial} (rad. corto = {rc})\n\n"
            f"RESTRICCION ANTI-CONTAMINACION: Este caso se identifica UNICAMENTE por su RADICADO OFICIAL '{radicado_oficial}' "
            f"(equivalente corto: {rc}). La CARPETA FISICA es solo una ruta del sistema de archivos y PUEDE contener "
            f"numeros temporales, FOREST u otros identificadores — IGNORALOS para identificar el caso.\n"
            f"Cuando redactes OBSERVACIONES, ASUNTO o cualquier campo narrativo que mencione el numero del caso, "
            f"USA SIEMPRE el RADICADO OFICIAL ({rc}), NUNCA el nombre de la carpeta si son distintos.\n"
            f"Si un documento menciona un radicado diferente a {rc} o {radicado_oficial}, IGNORA ese documento."
        )
    # Fallback: sin rad23 disponible, usar folder_name como antes
    return (
        f"CARPETA DEL CASO: {folder_name}\n\n"
        f"RESTRICCION ANTI-CONTAMINACION: Este caso es EXCLUSIVAMENTE de la carpeta \"{folder_name}\".\n"
        f"Solo extrae datos de documentos que pertenezcan a este caso.\n"
        f"Si un documento menciona un radicado diferente al de esta carpeta, IGNORA ese documento.\n"
        f"El radicado extraido DEBE contener el numero de caso de la carpeta."
    )



# ============================================================
# Funcion principal: extract_with_ai
# ============================================================

def extract_with_ai(
    documents: list[dict],
    folder_name: str,
    pdf_file_paths: list[dict] | None = None,
    radicado_oficial: str = "",
) -> AIExtractionResult:
    """Enviar documentos al proveedor de IA activo para extraer 28 campos.

    Args:
        documents: Lista de {"filename": str, "text": str}
        folder_name: Nombre de la carpeta del caso
        pdf_file_paths: Lista de {"filename": str, "file_path": str} para multimodal (solo Google)
        radicado_oficial: F3 (v5.0) — radicado 23d oficial del caso, usado para anti-contaminacion.
                          Si se provee, la IA recibe instruccion de usar este radicado en campos
                          narrativos (obs/asunto) en lugar del folder_name, evitando contaminacion
                          cuando el folder esta malformado (ej. derivado de FOREST).
    """
    # Seleccion inteligente de proveedor: SIEMPRE consultar Smart Router
    provider = _active_provider
    model = _active_model
    _fallback_provider = None
    _fallback_model = None

    try:
        from backend.agent.smart_router import route
        task = "pdf_multimodal" if pdf_file_paths else "extraction"
        decision = route(task)
        if decision and decision.provider:
            provider = decision.provider
            model = decision.model
            _fallback_provider = getattr(decision, "fallback_provider", None)
            _fallback_model = getattr(decision, "fallback_model", None)
    except Exception:
        pass  # Si Smart Router falla, usar proveedor por defecto

    model_config = get_model_config() if (provider == _active_provider and model == _active_model) else PROVIDERS.get(provider, {}).get("models", {}).get(model, {})

    # Verificar API key
    env_key = PROVIDERS.get(provider, {}).get("env_key", "")
    api_key = os.getenv(env_key, "") if env_key else ""
    if not api_key:
        return AIExtractionResult(
            error=f"{env_key} no configurada en .env",
            provider=provider, model=model,
        )

    # Ruta unica (v5.4): texto normalizado local (pdfplumber + PaddleOCR) +
    # extraccion semantica IA via DeepSeek / Claude Haiku 4.5.
    KEY_PATTERNS = {
        "auto": 1, "admite": 1, "avoca": 1, "escrito": 1,
        "sentencia": 2, "fallo": 2,
        "forest": 3, "respuesta": 3, "rta": 3,
        "gmail": 4, "rv_": 4, "email": 4,
        "impugn": 5,
        "incidente": 6, "desacato": 6,
    }

    def doc_priority(d):
        name = d.get("filename", "").lower()
        for keyword, pri in KEY_PATTERNS.items():
            if keyword in name:
                return pri
        return 9

    sorted_docs = sorted(documents, key=doc_priority)

    doc_texts = []
    for doc in sorted_docs:
        text = doc.get("text", "").strip()
        if not text:
            continue
        if not _is_critical_pdf(doc.get("filename", "")) and len(text) > 25000:
            text = text[:20000] + "\n[...CONTENIDO TRUNCADO...]\n" + text[-5000:]
        doc_type = doc.get("doc_type", "OTRO")
        doc_texts.append(f"\n===ARCHIVO: {doc['filename']} [TIPO: {doc_type}]===\n{text}")

    if not doc_texts:
        return AIExtractionResult(error="No hay texto para analizar", provider=provider, model=model)

    all_text = "".join(doc_texts)

    try:
        start_time = time.time()
        anti_cont = _build_anti_contamination_block(folder_name, radicado_oficial)
        user_message = f"""{anti_cont}

DOCUMENTOS DEL EXPEDIENTE:
{all_text}

Analiza TODOS los documentos y extrae los 28 campos. Responde SOLO con el JSON. RESPONDE EN ESPAÑOL."""

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        raw, total_input, total_output = _call_with_retry(
            provider, messages, model, model_config.get("max_tokens", 4096),
            fallback_provider=_fallback_provider, fallback_model=_fallback_model,
        )
        duration_ms = int((time.time() - start_time) * 1000)

        all_fields = _parse_ai_json(raw)

        return AIExtractionResult(
            fields=all_fields, raw_response=raw,
            tokens_input=total_input, tokens_output=total_output,
            tokens_used=total_input + total_output,
            provider=provider, model=model,
            duration_ms=duration_ms, chunks_used=1,
        )

    except Exception as e:
        # Fallback: usar proveedor alternativo (primero el del Smart Router, luego re-rutar)
        _logger.warning("Extraccion texto fallo con %s/%s: %s. Intentando fallback...", provider, model, str(e)[:100])
        try:
            fb_prov = _fallback_provider
            fb_mod = _fallback_model
            if not fb_prov:
                from backend.agent.smart_router import route
                _fb_decision = route("extraction")
                fb_prov = _fb_decision.provider
                fb_mod = _fb_decision.model
            if fb_prov and fb_prov != provider:
                _logger.warning("Fallback: %s/%s → %s/%s", provider, model, fb_prov, fb_mod)
                fb_caller = _CALLERS.get(fb_prov)
                if fb_caller:
                    start_fb = time.time()
                    fb_config = PROVIDERS.get(fb_prov, {}).get("models", {}).get(fb_mod, {})
                    fb_max_tokens = fb_config.get("max_tokens", 4096)
                    raw_fb, inp_fb, out_fb = _call_with_retry(fb_prov, messages, fb_mod, fb_max_tokens)
                    dur_fb = int((time.time() - start_fb) * 1000)
                    fb_fields = _parse_ai_json(raw_fb)
                    return AIExtractionResult(
                        fields=fb_fields, raw_response=raw_fb,
                        tokens_input=inp_fb, tokens_output=out_fb,
                        tokens_used=inp_fb + out_fb,
                        provider=fb_prov, model=fb_mod,
                        duration_ms=dur_fb, chunks_used=1,
                    )
        except Exception:
            pass  # Si el fallback tambien falla, devolver error original
        return AIExtractionResult(
            error=f"Error {provider}/{model}: {e}",
            provider=provider, model=model,
        )


