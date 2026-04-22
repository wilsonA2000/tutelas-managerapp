"""Smart Router: selección inteligente de proveedor/modelo según tipo de tarea.

Estrategia multi-modelo (v5.1 — sin Gemini):
1. Extracción de campos → DeepSeek V3.2 (barato, rápido, sin límite RPD)
2. Razonamiento legal complejo → Qwen 3 235B (thinking mode, gratis en Cerebras)
3. Fallback pagado → Claude Haiku 4.5 (Anthropic)
4. Fallback gratis → Groq Llama 3.3 70B

El router verifica qué API keys están disponibles y selecciona la mejor opción.
"""

import os
import time
import logging
import threading
from dataclasses import dataclass

logger = logging.getLogger("tutelas.router")

# Rate limit tracking: provider → timestamp del ultimo 429
# Protegido por _rate_limit_lock porque en PARALLEL_AI_EXTRACTION dos threads
# pueden llamar report_rate_limit() / _is_rate_limited() simultaneamente.
_rate_limit_cooldown: dict[str, float] = {}
_rate_limit_lock = threading.Lock()
_RATE_LIMIT_COOLDOWN_SECS = 60  # Esperar 60s antes de reintentar provider con 429


def report_rate_limit(provider: str):
    """Reportar que un provider devolvio 429. Se llama desde ai_extractor."""
    with _rate_limit_lock:
        _rate_limit_cooldown[provider] = time.time()
    logger.warning("Rate limit reportado para %s (cooldown %ds)", provider, _RATE_LIMIT_COOLDOWN_SECS)


def _is_rate_limited(provider: str) -> bool:
    """Check si un provider esta en cooldown por rate limit (atomico)."""
    with _rate_limit_lock:
        last_429 = _rate_limit_cooldown.get(provider, 0)
        return (time.time() - last_429) < _RATE_LIMIT_COOLDOWN_SECS

# Tipos de tarea que el agente puede ejecutar
TASK_TYPES = {
    "pdf_multimodal": "Lectura directa de PDFs (requiere multimodal)",
    "extraction": "Extracción de campos de texto (28 campos de tutela)",
    "complex_reasoning": "Análisis legal complejo, predicción, razonamiento",
    "legal_analysis": "Análisis jurídico profundo (incidentes, impugnaciones)",
    "general": "Consultas generales, resúmenes, chat",
    "multilingual": "Contenido en múltiples idiomas o español jurídico",
}


@dataclass
class RouteDecision:
    provider: str
    model: str
    reason: str
    cost_per_1m_input: float
    cost_per_1m_output: float
    context_window: int
    fallback_provider: str | None = None
    fallback_model: str | None = None


# Cadena de prioridad por tipo de tarea
# Cada lista es [proveedor, modelo, env_key] en orden de preferencia
#
# NOTA v4.7: Gemini fue eliminado de todas las cadenas tras auditoria del
# 9 abril 2026. Razones:
# - 97% de los PDFs son nativos (pdfplumber extrae texto correctamente)
# - Gemini multimodal consumia 17x mas tokens input que DeepSeek
# - DeepSeek V3.2 produce igual o mejor calidad en campos semanticos
# - Claude Haiku 4.5 es ahora el fallback pagado (~$8/mes)
ROUTING_CHAINS = {
    "pdf_multimodal": [
        # Ya no hay ruta multimodal: el texto viene del normalizer local
        # (pdfplumber + PaddleOCR). La clave se deja por compat hacia atras.
        ("deepseek", "deepseek-chat", "DEEPSEEK_API_KEY"),
        ("anthropic", "claude-haiku-4-5-20251001", "ANTHROPIC_API_KEY"),
    ],
    "extraction": [
        ("deepseek", "deepseek-chat", "DEEPSEEK_API_KEY"),
        ("anthropic", "claude-haiku-4-5-20251001", "ANTHROPIC_API_KEY"),
        ("groq", "llama-3.3-70b-versatile", "GROQ_API_KEY"),
        ("huggingface", "meta-llama/Llama-3.3-70B-Instruct", "HF_TOKEN"),
        ("cerebras", "llama-3.3-70b", "CEREBRAS_API_KEY"),
    ],
    "complex_reasoning": [
        ("cerebras", "qwen-3-235b-a22b-instruct-2507", "CEREBRAS_API_KEY"),
        ("huggingface", "Qwen/Qwen3-235B-A22B-Instruct-2507", "HF_TOKEN"),
        ("deepseek", "deepseek-reasoner", "DEEPSEEK_API_KEY"),
        ("anthropic", "claude-haiku-4-5-20251001", "ANTHROPIC_API_KEY"),
        ("groq", "qwen-qwq-32b", "GROQ_API_KEY"),
    ],
    "legal_analysis": [
        ("cerebras", "qwen-3-235b-a22b-instruct-2507", "CEREBRAS_API_KEY"),
        ("huggingface", "Qwen/Qwen3-235B-A22B-Instruct-2507", "HF_TOKEN"),
        ("deepseek", "deepseek-reasoner", "DEEPSEEK_API_KEY"),
        ("anthropic", "claude-haiku-4-5-20251001", "ANTHROPIC_API_KEY"),
    ],
    "general": [
        ("deepseek", "deepseek-chat", "DEEPSEEK_API_KEY"),
        ("groq", "llama-3.3-70b-versatile", "GROQ_API_KEY"),
        ("cerebras", "llama-3.3-70b", "CEREBRAS_API_KEY"),
        ("anthropic", "claude-haiku-4-5-20251001", "ANTHROPIC_API_KEY"),
        ("huggingface", "meta-llama/Llama-3.3-70B-Instruct", "HF_TOKEN"),
    ],
    "multilingual": [
        ("cerebras", "qwen-3-235b-a22b-instruct-2507", "CEREBRAS_API_KEY"),
        ("huggingface", "Qwen/Qwen3-235B-A22B-Instruct-2507", "HF_TOKEN"),
        ("deepseek", "deepseek-chat", "DEEPSEEK_API_KEY"),
        ("anthropic", "claude-haiku-4-5-20251001", "ANTHROPIC_API_KEY"),
    ],
}


def _validate_api_key(env_key: str) -> bool:
    """Validar que una API key existe y no es placeholder."""
    key = os.getenv(env_key, "").strip()
    if not key or len(key) < 10:
        return False
    # Detectar placeholders comunes
    placeholders = {"xxx", "your-key-here", "CHANGE_ME", "sk-xxx", "test"}
    if key.lower() in placeholders:
        return False
    return True


def route(task_type: str = "general") -> RouteDecision:
    """Seleccionar el mejor proveedor disponible para un tipo de tarea.

    Itera la cadena de prioridad: el 1er provider disponible es el primary,
    el 2do es el fallback. Valida API keys antes de seleccionar.

    Args:
        task_type: Tipo de tarea (pdf_multimodal, extraction, complex_reasoning, etc.)

    Returns:
        RouteDecision con proveedor, modelo y razón.
    """
    from backend.extraction.ai_extractor import PROVIDERS

    chain = ROUTING_CHAINS.get(task_type, ROUTING_CHAINS["general"])

    # Recopilar todos los providers disponibles en orden (skip rate-limited)
    available = []
    for provider, model, env_key in chain:
        if not _validate_api_key(env_key):
            continue
        if _is_rate_limited(provider):
            logger.info("Skip %s/%s (rate limit cooldown)", provider, model)
            continue
        model_config = PROVIDERS.get(provider, {}).get("models", {}).get(model, {})
        available.append((provider, model, model_config))

    if not available:
        logger.error("No provider available for task '%s' — configure at least DEEPSEEK_API_KEY", task_type)
        return RouteDecision(
            provider="none",
            model="none",
            reason="ERROR: sin proveedores disponibles. Configure DEEPSEEK_API_KEY o ANTHROPIC_API_KEY en .env",
            cost_per_1m_input=0,
            cost_per_1m_output=0,
            context_window=0,
        )

    # Primary = 1ro disponible, Fallback = 2do disponible
    prov, mod, cfg = available[0]
    decision = RouteDecision(
        provider=prov,
        model=mod,
        reason=f"Mejor opción para '{task_type}': {PROVIDERS.get(prov, {}).get('name', prov)} / {cfg.get('label', mod)}",
        cost_per_1m_input=cfg.get("input_price", 0),
        cost_per_1m_output=cfg.get("output_price", 0),
        context_window=cfg.get("context_window", 128000),
    )

    if len(available) >= 2:
        fb_prov, fb_mod, _ = available[1]
        decision.fallback_provider = fb_prov
        decision.fallback_model = fb_mod
        logger.info("Route [%s] → %s/%s (fallback: %s/%s)", task_type, prov, mod, fb_prov, fb_mod)
    else:
        logger.info("Route [%s] → %s/%s (sin fallback)", task_type, prov, mod)

    return decision


def get_available_routes() -> dict[str, RouteDecision]:
    """Obtener la ruta que se usaría para cada tipo de tarea."""
    routes = {}
    for task_type in TASK_TYPES:
        routes[task_type] = route(task_type)
    return routes


def get_configured_providers() -> list[dict]:
    """Lista de proveedores con API key configurada."""
    from backend.extraction.ai_extractor import PROVIDERS
    configured = []
    for pid, pinfo in PROVIDERS.items():
        api_key = os.getenv(pinfo["env_key"], "")
        if api_key:
            configured.append({
                "provider": pid,
                "name": pinfo["name"],
                "models": list(pinfo["models"].keys()),
                "key_configured": True,
            })
        else:
            configured.append({
                "provider": pid,
                "name": pinfo["name"],
                "models": list(pinfo["models"].keys()),
                "key_configured": False,
            })
    return configured
