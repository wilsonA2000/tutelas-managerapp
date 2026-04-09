"""Extractor multi-proveedor de campos usando IA (Groq/Claude/OpenAI/Gemini/DeepSeek/Cerebras/HF)."""

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

# Proveedor activo (se puede cambiar en runtime) — Gemini por defecto (gratis)
_active_provider = "google"
_active_model = "gemini-2.5-flash"

# Catalogo de proveedores y modelos con precios (USD por 1M tokens)
PROVIDERS = {
    "google": {
        "name": "Google Gemini",
        "models": {
            "gemini-2.5-flash": {
                "label": "Gemini 2.5 Flash (Gratis)",
                "input_price": 0,
                "output_price": 0,
                "max_tokens": 16384,
                "context_window": 1000000,
                "needs_chunking": False,
                "multimodal": True,
                "best_for": ["pdf_multimodal", "general"],
            },
            "gemini-2.5-pro": {
                "label": "Gemini 2.5 Pro",
                "input_price": 1.25,
                "output_price": 10.00,
                "max_tokens": 8192,
                "context_window": 1000000,
                "needs_chunking": False,
                "multimodal": True,
                "best_for": ["complex_reasoning"],
            },
        },
        "env_key": "GOOGLE_API_KEY",
    },
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
    "huggingface": {
        "name": "Hugging Face Router",
        "models": {
            "Qwen/Qwen3-235B-A22B-Instruct-2507": {
                "label": "Qwen 3 235B (Gratis via Cerebras)",
                "input_price": 0.60,
                "output_price": 1.20,
                "max_tokens": 8192,
                "context_window": 131072,
                "needs_chunking": False,
                "multimodal": False,
                "best_for": ["complex_reasoning", "multilingual", "legal_analysis"],
            },
            "deepseek-ai/DeepSeek-R1": {
                "label": "DeepSeek R1 (via HF Router)",
                "input_price": 0.55,
                "output_price": 2.19,
                "max_tokens": 16384,
                "context_window": 128000,
                "needs_chunking": False,
                "multimodal": False,
                "best_for": ["complex_reasoning"],
            },
            "meta-llama/Llama-3.3-70B-Instruct": {
                "label": "Llama 3.3 70B (via Groq/HF)",
                "input_price": 0.59,
                "output_price": 0.79,
                "max_tokens": 8192,
                "context_window": 128000,
                "needs_chunking": False,
                "multimodal": False,
                "best_for": ["general", "extraction"],
            },
        },
        "env_key": "HF_TOKEN",
    },
    "cerebras": {
        "name": "Cerebras (Ultra rapido)",
        "models": {
            "qwen-3-235b-a22b-instruct-2507": {
                "label": "Qwen 3 235B (1,400 t/s)",
                "input_price": 0.60,
                "output_price": 1.20,
                "max_tokens": 8192,
                "context_window": 131072,
                "needs_chunking": False,
                "multimodal": False,
                "best_for": ["complex_reasoning", "multilingual", "legal_analysis"],
            },
            "llama-3.3-70b": {
                "label": "Llama 3.3 70B (394 t/s)",
                "input_price": 0.59,
                "output_price": 0.79,
                "max_tokens": 8192,
                "context_window": 128000,
                "needs_chunking": False,
                "multimodal": False,
                "best_for": ["general", "extraction"],
            },
        },
        "env_key": "CEREBRAS_API_KEY",
    },
    "groq": {
        "name": "Groq (Ultra rapido)",
        "models": {
            "llama-3.3-70b-versatile": {
                "label": "Llama 3.3 70B (394 t/s)",
                "input_price": 0.59,
                "output_price": 0.79,
                "max_tokens": 8192,
                "context_window": 128000,
                "needs_chunking": False,
                "multimodal": False,
                "best_for": ["general", "extraction"],
            },
            "qwen-qwq-32b": {
                "label": "Qwen QwQ 32B (Reasoning)",
                "input_price": 0.29,
                "output_price": 0.39,
                "max_tokens": 16384,
                "context_window": 131072,
                "needs_chunking": False,
                "multimodal": False,
                "best_for": ["complex_reasoning"],
            },
        },
        "env_key": "GROQ_API_KEY",
    },
    "anthropic": {
        "name": "Claude (Anthropic)",
        "models": {
            "claude-3-haiku-20240307": {
                "label": "Claude Haiku 3 (Ultra barato)",
                "input_price": 0.25,
                "output_price": 1.25,
                "max_tokens": 4096,
                "context_window": 200000,
                "needs_chunking": False,
                "multimodal": False,
                "best_for": ["extraction", "general"],
            },
            "claude-haiku-4-5-20251001": {
                "label": "Claude Haiku 4.5",
                "input_price": 1.00,
                "output_price": 5.00,
                "max_tokens": 4096,
                "context_window": 200000,
                "needs_chunking": False,
                "multimodal": False,
                "best_for": ["general"],
            },
            "claude-sonnet-4-6-20260320": {
                "label": "Claude Sonnet 4.6",
                "input_price": 3.00,
                "output_price": 15.00,
                "max_tokens": 4096,
                "context_window": 200000,
                "needs_chunking": False,
                "multimodal": False,
                "best_for": ["complex_reasoning", "legal_analysis"],
            },
        },
        "env_key": "ANTHROPIC_API_KEY",
    },
    "openai": {
        "name": "OpenAI",
        "models": {
            "gpt-4o-mini": {
                "label": "GPT-4o Mini",
                "input_price": 0.15,
                "output_price": 0.60,
                "max_tokens": 4096,
                "context_window": 128000,
                "needs_chunking": False,
                "multimodal": False,
                "best_for": ["general"],
            },
            "gpt-4o": {
                "label": "GPT-4o",
                "input_price": 2.50,
                "output_price": 10.00,
                "max_tokens": 4096,
                "context_window": 128000,
                "needs_chunking": False,
                "multimodal": True,
                "best_for": ["complex_reasoning"],
            },
        },
        "env_key": "OPENAI_API_KEY",
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


def _call_openai(messages: list[dict], model: str, max_tokens: int = 4096) -> tuple[str, int, int]:
    """Llamar a OpenAI API."""
    from openai import OpenAI
    api_key = os.getenv("OPENAI_API_KEY", "")
    client = OpenAI(api_key=api_key)

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


def _call_google(messages: list[dict], model: str, max_tokens: int = 4096) -> tuple[str, int, int]:
    """Llamar a Google Gemini API (SDK nuevo: google-genai)."""
    from google import genai

    api_key = os.getenv("GOOGLE_API_KEY", "")
    client = genai.Client(api_key=api_key)

    # Convertir formato messages a Gemini format
    system_text = ""
    user_text = ""
    for m in messages:
        if m["role"] == "system":
            system_text = m["content"]
        else:
            user_text = m["content"]

    response = client.models.generate_content(
        model=model,
        contents=user_text,
        config=genai.types.GenerateContentConfig(
            system_instruction=system_text,
            response_mime_type="application/json",
            temperature=0.1,
            max_output_tokens=max_tokens,
            safety_settings=[
                genai.types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"),
                genai.types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="OFF"),
                genai.types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="OFF"),
                genai.types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="OFF"),
            ],
        ),
    )
    text = response.text
    inp = response.usage_metadata.prompt_token_count if response.usage_metadata else 0
    out = response.usage_metadata.candidates_token_count if response.usage_metadata else 0
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


def _call_huggingface(messages: list[dict], model: str, max_tokens: int = 4096) -> tuple[str, int, int]:
    """Llamar via Hugging Face Router (acceso a Qwen, DeepSeek, Llama via Cerebras/Groq/Together)."""
    from openai import OpenAI
    api_key = os.getenv("HF_TOKEN", "")
    client = OpenAI(api_key=api_key, base_url="https://router.huggingface.co/v1")

    # Append :fastest for auto provider selection
    model_with_policy = f"{model}:fastest" if ":" not in model else model

    response = client.chat.completions.create(
        model=model_with_policy,
        messages=messages,
        temperature=0.1,
        max_tokens=max_tokens,
    )
    text = response.choices[0].message.content
    inp = response.usage.prompt_tokens if response.usage else 0
    out = response.usage.completion_tokens if response.usage else 0
    return text, inp, out


def _call_cerebras(messages: list[dict], model: str, max_tokens: int = 4096) -> tuple[str, int, int]:
    """Llamar a Cerebras API (20x mas rapido, compatible OpenAI SDK)."""
    from openai import OpenAI
    api_key = os.getenv("CEREBRAS_API_KEY", "")
    client = OpenAI(api_key=api_key, base_url="https://api.cerebras.ai/v1")

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.1,
        max_tokens=max_tokens,
    )
    text = response.choices[0].message.content
    inp = response.usage.prompt_tokens if response.usage else 0
    out = response.usage.completion_tokens if response.usage else 0
    return text, inp, out


def _call_groq(messages: list[dict], model: str, max_tokens: int = 4096) -> tuple[str, int, int]:
    """Llamar a Groq API (ultra rapido)."""
    from groq import Groq
    api_key = os.getenv("GROQ_API_KEY", "")
    client = Groq(api_key=api_key)

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
    "openai": _call_openai,
    "google": _call_google,
    "deepseek": _call_deepseek,
    "huggingface": _call_huggingface,
    "cerebras": _call_cerebras,
    "groq": _call_groq,
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
# Gemini Multimodal: enviar PDFs como archivos binarios
# ============================================================

# Keywords para clasificar PDFs criticos (se envian como multimodal)
CRITICAL_KEYWORDS = {"auto", "admite", "avoca", "sentencia", "fallo", "impugn",
                     "incidente", "desacato", "forest", "respuesta", "rta", "escrito"}

MAX_MULTIMODAL_PDFS = 8  # Maximo PDFs a subir como multimodal por caso


def _is_critical_pdf(filename: str) -> bool:
    """Verificar si un PDF es critico (auto admisorio, sentencia, etc.)."""
    name = filename.lower()
    return any(kw in name for kw in CRITICAL_KEYWORDS)


def _extract_multimodal_google(
    documents: list[dict],
    pdf_file_paths: list[dict],
    folder_name: str,
    model: str,
    model_config: dict,
) -> AIExtractionResult:
    """Enviar PDFs como archivos multimodal a Gemini + texto de DOCX/emails.

    PDFs criticos (auto admisorio, sentencia) se suben como archivo binario.
    DOCX, emails y PDFs no criticos se envian como texto.
    """
    from google import genai
    from backend.extraction.pdf_splitter import prepare_pdf_for_upload

    provider = "google"
    api_key = os.getenv("GOOGLE_API_KEY", "")
    client = genai.Client(api_key=api_key)

    # Separar PDFs criticos (multimodal) vs resto (texto)
    pdf_names_set = {p["filename"] for p in pdf_file_paths}
    critical_pdfs = [p for p in pdf_file_paths if _is_critical_pdf(p["filename"])][:MAX_MULTIMODAL_PDFS]
    critical_names = {p["filename"] for p in critical_pdfs}

    # Texto de documentos no-PDF + PDFs no criticos
    text_parts = []
    for doc in documents:
        if doc["filename"] in critical_names:
            continue  # Este va como archivo multimodal
        text = doc.get("text", "").strip()
        if not text:
            continue
        if len(text) > 25000:
            text = text[:20000] + "\n[...CONTENIDO TRUNCADO...]\n" + text[-5000:]
        doc_type = doc.get("doc_type", "OTRO")
        text_parts.append(f"\n===ARCHIVO: {doc['filename']} [TIPO: {doc_type}]===\n{text}")

    # Si no hay PDFs criticos ni texto, no hay nada que procesar
    if not critical_pdfs and not text_parts:
        # Fallback: enviar todo como texto
        return None

    start_time = time.time()
    uploaded_files = []
    temp_files = []

    try:
        # Subir PDFs criticos a Gemini
        content_parts = []

        for pdf_info in critical_pdfs:
            try:
                # Validar que el PDF no este vacio/corrupto
                import fitz
                try:
                    check_doc = fitz.open(pdf_info["file_path"])
                    if len(check_doc) == 0:
                        check_doc.close()
                        raise ValueError("PDF sin paginas")
                    check_doc.close()
                except Exception:
                    # PDF corrupto/vacio — fallback a texto
                    for doc in documents:
                        if doc["filename"] == pdf_info["filename"] and doc.get("text"):
                            text_parts.append(f"\n===ARCHIVO: {doc['filename']}===\n{doc['text']}")
                    continue

                # Recortar si es muy grande
                upload_path, was_trimmed = prepare_pdf_for_upload(pdf_info["file_path"])
                if was_trimmed:
                    temp_files.append(upload_path)

                uploaded = client.files.upload(file=upload_path)
                uploaded_files.append(uploaded)
                content_parts.append(uploaded)
                time.sleep(1)  # Pausa entre uploads para rate limit
            except Exception:
                # Fallback: incluir texto extraido de este PDF
                for doc in documents:
                    if doc["filename"] == pdf_info["filename"] and doc.get("text"):
                        text_parts.append(f"\n===ARCHIVO: {doc['filename']}===\n{doc['text']}")
                        break

        # Agregar texto (DOCX, emails, PDFs no criticos)
        combined_text = "".join(text_parts)
        user_text = f"""CARPETA DEL CASO: {folder_name}

DOCUMENTOS ADICIONALES (texto):
{combined_text}

Analiza TODOS los documentos (PDFs adjuntos + texto) y extrae los 28 campos. Responde SOLO con JSON."""

        content_parts.append(user_text)

        # Llamar a Gemini con contenido mixto (archivos + texto)
        max_retries = 5
        raw = ""
        total_input = 0
        total_output = 0

        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=content_parts,
                    config=genai.types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        temperature=0.1,
                        max_output_tokens=model_config.get("max_tokens", 16384),
                        safety_settings=[
                            genai.types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"),
                            genai.types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="OFF"),
                            genai.types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="OFF"),
                            genai.types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="OFF"),
                        ],
                    ),
                )
                raw = response.text
                total_input = response.usage_metadata.prompt_token_count if response.usage_metadata else 0
                total_output = response.usage_metadata.candidates_token_count if response.usage_metadata else 0
                break
            except Exception as e:
                err = str(e).lower()
                if "429" in err or "rate" in err or "503" in err or "unavailable" in err or "service" in err:
                    time.sleep(10 * (attempt + 1))
                    continue
                raise

        duration_ms = int((time.time() - start_time) * 1000)

        # Parsear JSON
        all_fields = _parse_ai_json(raw)

        return AIExtractionResult(
            fields=all_fields,
            raw_response=raw,
            tokens_input=total_input,
            tokens_output=total_output,
            tokens_used=total_input + total_output,
            provider=provider,
            model=model,
            duration_ms=duration_ms,
            chunks_used=1,
        )

    except json.JSONDecodeError as e:
        _logger.warning("Multimodal JSON vacio/invalido (%d chars): %s. Fallback a ruta texto.",
                        len(raw) if raw else 0, e)
        return None  # extract_with_ai() hace fallback a ruta texto (DeepSeek/Groq)
    except Exception as e:
        _logger.warning("Error multimodal %s/%s: %s. Fallback a ruta texto.", provider, model, e)
        return None  # Misma estrategia: fallback a texto
    finally:
        # Limpiar archivos temporales y uploads de Gemini
        for tmp in temp_files:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        for uploaded in uploaded_files:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass


# ============================================================
# Funcion principal: extract_with_ai
# ============================================================

def extract_with_ai(
    documents: list[dict],
    folder_name: str,
    pdf_file_paths: list[dict] | None = None,
) -> AIExtractionResult:
    """Enviar documentos al proveedor de IA activo para extraer 28 campos.

    Args:
        documents: Lista de {"filename": str, "text": str}
        folder_name: Nombre de la carpeta del caso
        pdf_file_paths: Lista de {"filename": str, "file_path": str} para multimodal (solo Google)
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

    # NOTA v4.7: Ruta multimodal de Gemini deshabilitada. Ver smart_router.py
    # para el razonamiento de arquitectura. La funcion _extract_multimodal_google
    # permanece en el modulo por si se reactiva en el futuro, pero ya no se
    # invoca desde el flujo de extraccion normal. El texto de PDFs ahora viene
    # del normalizer local (pdfplumber + PaddleOCR).

    # RUTA TEXTO: Unica ruta activa para todos los proveedores
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
        user_message = f"""CARPETA DEL CASO: {folder_name}

RESTRICCION ANTI-CONTAMINACION: Este caso es EXCLUSIVAMENTE de la carpeta "{folder_name}".
Solo extrae datos de documentos que pertenezcan a este caso.
Si un documento menciona un radicado diferente al de esta carpeta, IGNORA ese documento.
El radicado extraido DEBE contener el numero de caso de la carpeta.

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


# ============================================================
# Extraccion IA PARALELA (Gemini + DeepSeek)
# ============================================================
#
# Contexto: La memoria del proyecto dice "Gemini+DeepSeek secuenciales" pero
# esto es impreciso. Antes de v4.7, extract_with_ai() solo corria UN provider
# (elegido por Smart Router), el otro quedaba como fallback casi nunca invocado.
#
# parallel_extract_with_ai() corre ambos en ThreadPoolExecutor. Beneficios:
# - Mejor cobertura por campo (Gemini visual, DeepSeek razonamiento textual)
# - Redundancia real: si uno falla (429/error), el otro ya entrego
# - Cross-validation gratis: campos donde coinciden → confidence boost +15
#
# Activado via settings.PARALLEL_AI_EXTRACTION (opt-in en v4.7, por default
# tras validacion de piloto).


# Campos donde Gemini tiene ventaja (datos visuales del PDF)
_GEMINI_PREFERRED = {
    "radicado_23_digitos", "fecha_ingreso", "fecha_fallo_1st",
    "fecha_fallo_2nd", "juzgado", "ciudad", "sentido_fallo_1st",
    "sentido_fallo_2nd", "accionante",
}

# Campos donde DeepSeek tiene ventaja (razonamiento textual denso)
_DEEPSEEK_PREFERRED = {
    "observaciones", "pretensiones", "derecho_vulnerado", "asunto",
    "accionados", "vinculados", "quien_impugno", "decision_incidente",
}

# Campos donde un conflicto ALTA vs ALTA es peligroso: demote a MEDIA
# para que el merge regex/IA en Fase 5 prefiera el regex (estan en
# REGEX_PREFERRED_FIELDS de registry.py).
_CRITICAL_CONFLICT_DEMOTE = {
    "radicado_23_digitos", "radicado_forest",
    "fecha_ingreso", "fecha_fallo_1st", "fecha_fallo_2nd",
}

_CONF_RANK = {"ALTA": 3, "MEDIA": 2, "BAJA": 1}


def _normalize_field_value(value: str) -> str:
    """Normalizar valor para comparar si dos IAs coinciden."""
    if not value:
        return ""
    # Quitar espacios, puntuacion basica, pasar a minusculas
    return " ".join(value.strip().lower().split())


def _run_single_provider(
    provider: str,
    model: str,
    documents: list[dict],
    folder_name: str,
    pdf_file_paths: list[dict] | None = None,
) -> AIExtractionResult:
    """Ejecutar UN solo provider IA sin pasar por Smart Router.

    Usado por parallel_extract_with_ai() para forzar providers especificos.
    NUNCA propaga excepciones: las captura y devuelve AIExtractionResult con
    error poblado, para que ThreadPoolExecutor.future.result() nunca bloquee
    el otro thread.
    """
    try:
        # Validar API key
        env_key = PROVIDERS.get(provider, {}).get("env_key", "")
        if not env_key or not os.getenv(env_key, ""):
            return AIExtractionResult(
                error=f"{env_key} no configurada", provider=provider, model=model,
            )

        model_config = PROVIDERS.get(provider, {}).get("models", {}).get(model, {})
        max_tokens = model_config.get("max_tokens", 4096)

        # NOTA v4.7: Ruta multimodal deshabilitada. Ver extract_with_ai.
        # Todos los providers usan ruta texto sobre el IR ya extraido.

        # Ruta texto: construir messages identico a extract_with_ai
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
            return AIExtractionResult(
                error="No hay texto para analizar", provider=provider, model=model,
            )

        all_text = "".join(doc_texts)
        user_message = f"""CARPETA DEL CASO: {folder_name}

RESTRICCION ANTI-CONTAMINACION: Este caso es EXCLUSIVAMENTE de la carpeta "{folder_name}".
Solo extrae datos de documentos que pertenezcan a este caso.
Si un documento menciona un radicado diferente al de esta carpeta, IGNORA ese documento.
El radicado extraido DEBE contener el numero de caso de la carpeta.

DOCUMENTOS DEL EXPEDIENTE:
{all_text}

Analiza TODOS los documentos y extrae los 28 campos. Responde SOLO con el JSON. RESPONDE EN ESPAÑOL."""

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        start_time = time.time()
        # En modo paralelo usamos menos retries: el otro provider ya es nuestra
        # redundancia real. 2 intentos cubren hiccups transitorios sin bloquear.
        raw, total_input, total_output = _call_with_retry(
            provider, messages, model, max_tokens, max_retries=2,
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
        _logger.warning(
            "_run_single_provider %s/%s fallo: %s", provider, model, str(e)[:120]
        )
        return AIExtractionResult(
            error=f"Error {provider}/{model}: {e}",
            provider=provider, model=model,
        )


def _merge_ai_results(
    gemini: AIExtractionResult,
    deepseek: AIExtractionResult,
    case_id: int = 0,
) -> AIExtractionResult:
    """Fusionar resultados de dos providers IA en uno solo.

    Reglas:
    1. Ambos coinciden (normalizado) → cross-validated, ALTA, source="..._cv"
    2. Conflicto ALTA vs ALTA en campo critico → ambos demoteados a MEDIA
       (regex ganara en Fase 5 por REGEX_PREFERRED_FIELDS)
    3. Conflicto con confidence distinta → mayor confidence gana
    4. Empate de confidence → preferencia por campo (GEMINI/DEEPSEEK_PREFERRED)
    5. Solo uno tiene el campo → ese gana

    Si ambos devuelven fields={} sin error, sintetiza error para marcar REVISION.
    """
    g_fields = gemini.fields if gemini and gemini.fields else {}
    d_fields = deepseek.fields if deepseek and deepseek.fields else {}

    merged: dict[str, AIFieldResult] = {}
    cv_count = 0

    all_field_names = set(g_fields) | set(d_fields)
    for field_name in all_field_names:
        g = g_fields.get(field_name)
        d = d_fields.get(field_name)

        if g and d:
            # 1) Cross-validation: ambos coinciden
            if _normalize_field_value(g.value) == _normalize_field_value(d.value):
                merged[field_name] = AIFieldResult(
                    value=g.value,
                    confidence="ALTA",
                    source=f"{g.source or 'gemini'}+{d.source or 'deepseek'}_cv",
                )
                cv_count += 1
                _logger.info(
                    "cv_field case=%d field=%s value=%s",
                    case_id, field_name, str(g.value)[:50],
                )
            # 2) Conflicto en campo critico ALTA vs ALTA → demote a MEDIA
            elif (
                field_name in _CRITICAL_CONFLICT_DEMOTE
                and g.confidence == "ALTA"
                and d.confidence == "ALTA"
            ):
                _logger.warning(
                    "CONFLICT case=%d field=%s gemini=%s deepseek=%s",
                    case_id, field_name, str(g.value)[:60], str(d.value)[:60],
                )
                merged[field_name] = AIFieldResult(
                    value=g.value,  # Preservar gemini (visual) pero MEDIA
                    confidence="MEDIA",
                    source="conflict_gemini_vs_deepseek",
                )
            # 3) Mayor confidence gana
            elif _CONF_RANK[g.confidence] > _CONF_RANK[d.confidence]:
                merged[field_name] = g
            elif _CONF_RANK[d.confidence] > _CONF_RANK[g.confidence]:
                merged[field_name] = d
            # 4) Empate → preferencia por campo
            else:
                if field_name in _GEMINI_PREFERRED:
                    merged[field_name] = g
                elif field_name in _DEEPSEEK_PREFERRED:
                    merged[field_name] = d
                else:
                    # Sin preferencia: gemini por default
                    merged[field_name] = g
        elif g:
            merged[field_name] = g
        elif d:
            merged[field_name] = d

    # Guard: ambos devolvieron fields={} sin error → sintetizar error
    if not merged and not gemini.error and not deepseek.error:
        return AIExtractionResult(
            error="parallel: both providers returned empty fields",
            provider="parallel(google+deepseek)",
            model=f"{gemini.model or '?'}+{deepseek.model or '?'}",
            tokens_input=gemini.tokens_input + deepseek.tokens_input,
            tokens_output=gemini.tokens_output + deepseek.tokens_output,
        )

    # Si ambos fallaron, propagar error combinado
    combined_error = None
    if gemini.error and deepseek.error:
        combined_error = f"gemini: {gemini.error[:80]} | deepseek: {deepseek.error[:80]}"

    return AIExtractionResult(
        fields=merged,
        tokens_input=gemini.tokens_input + deepseek.tokens_input,
        tokens_output=gemini.tokens_output + deepseek.tokens_output,
        tokens_used=(
            gemini.tokens_input + gemini.tokens_output
            + deepseek.tokens_input + deepseek.tokens_output
        ),
        provider="parallel(google+deepseek)",
        model=f"{gemini.model or '?'}+{deepseek.model or '?'}",
        duration_ms=max(gemini.duration_ms, deepseek.duration_ms),
        chunks_used=1,
        error=combined_error,
    )


def parallel_extract_with_ai(
    documents: list[dict],
    folder_name: str,
    pdf_file_paths: list[dict] | None = None,
    case_id: int = 0,
) -> tuple[AIExtractionResult, list[AIExtractionResult]]:
    """Ejecutar Gemini + DeepSeek en paralelo con ThreadPoolExecutor.

    Returns:
        (merged_result, raw_results)
        - merged_result: AIExtractionResult combinado, alimenta el merge de Fase 5
        - raw_results: lista con los 2 resultados individuales, uno por provider.
          El caller (unified.py) debe crear 1 TokenUsage por cada uno.

    Degradacion:
    - Si algun provider esta en rate-limit cooldown o sin API key → degradar
      a extract_with_ai() secuencial normal. Devuelve (result, [result]).
    - Si un provider falla mid-execution → devolver el otro + error del fallido.
    - Si ambos fallan → merged con error, raw_list con ambos errores.
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
    from backend.core.settings import settings as _settings
    from backend.agent.smart_router import _is_rate_limited

    providers = _settings.PARALLEL_AI_PROVIDERS
    if not providers or len(providers) < 2:
        _logger.warning(
            "parallel: PARALLEL_AI_PROVIDERS mal configurado, degradando a secuencial"
        )
        result = extract_with_ai(documents, folder_name, pdf_file_paths)
        return (result, [result])

    (p1, m1), (p2, m2) = providers[0], providers[1]

    # Check de viabilidad: cooldown o API key faltante
    reasons_to_degrade = []
    for prov, mod in ((p1, m1), (p2, m2)):
        env_key = PROVIDERS.get(prov, {}).get("env_key", "")
        if not env_key or not os.getenv(env_key, ""):
            reasons_to_degrade.append(f"{prov}: sin API key")
        elif _is_rate_limited(prov):
            reasons_to_degrade.append(f"{prov}: rate limit cooldown")

    if reasons_to_degrade:
        _logger.warning(
            "parallel: degraded to sequential (reason=%s)", "; ".join(reasons_to_degrade)
        )
        result = extract_with_ai(documents, folder_name, pdf_file_paths)
        return (result, [result])

    _logger.info(
        "parallel: launching %s/%s + %s/%s for case %d",
        p1, m1, p2, m2, case_id,
    )

    # Timeout total del paralelo (wall-clock). Si un provider se demora mucho
    # con retries internos, igualmente cortamos a los PARALLEL_TIMEOUT_SECS para
    # no dejar al otro esperando eternamente.
    PARALLEL_TIMEOUT_SECS = 150

    res1: AIExtractionResult | None = None
    res2: AIExtractionResult | None = None

    start_parallel = time.time()

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="parallel_ai") as executor:
        # Provider 1 (Gemini): ruta multimodal con PDFs
        future1 = executor.submit(
            _run_single_provider, p1, m1, documents, folder_name, pdf_file_paths,
        )
        # Provider 2 (DeepSeek): ruta texto, sin PDFs multimodal
        future2 = executor.submit(
            _run_single_provider, p2, m2, documents, folder_name, None,
        )

        # Timeout wall-clock: descontar el tiempo transcurrido para el segundo
        try:
            res1 = future1.result(timeout=PARALLEL_TIMEOUT_SECS)
        except FuturesTimeoutError:
            _logger.warning("parallel: %s/%s timeout tras %ds", p1, m1, PARALLEL_TIMEOUT_SECS)
            future1.cancel()
            res1 = AIExtractionResult(
                error=f"timeout after {PARALLEL_TIMEOUT_SECS}s", provider=p1, model=m1,
            )
        except Exception as e:
            _logger.warning("parallel: %s/%s error inesperado: %s", p1, m1, str(e)[:100])
            res1 = AIExtractionResult(error=str(e), provider=p1, model=m1)

        # Para el segundo: restar el tiempo ya usado para no bloquear eternamente
        elapsed_so_far = time.time() - start_parallel
        remaining = max(5, PARALLEL_TIMEOUT_SECS - elapsed_so_far)
        try:
            res2 = future2.result(timeout=remaining)
        except FuturesTimeoutError:
            _logger.warning("parallel: %s/%s timeout tras %.0fs", p2, m2, remaining)
            future2.cancel()
            res2 = AIExtractionResult(
                error=f"timeout after {int(remaining)}s", provider=p2, model=m2,
            )
        except Exception as e:
            _logger.warning("parallel: %s/%s error inesperado: %s", p2, m2, str(e)[:100])
            res2 = AIExtractionResult(error=str(e), provider=p2, model=m2)

    _logger.info(
        "parallel: %s=%dms %s=%dms case=%d",
        p1, res1.duration_ms, p2, res2.duration_ms, case_id,
    )

    merged = _merge_ai_results(res1, res2, case_id=case_id)
    return (merged, [res1, res2])
