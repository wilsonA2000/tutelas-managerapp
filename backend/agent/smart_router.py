"""Smart Router: selección inteligente de proveedor/modelo según tipo de tarea.

Estrategia multi-modelo:
1. PDFs multimodales → Gemini Flash (único con multimodal nativo)
2. Extracción de campos → DeepSeek V3.2 (barato, rápido, sin límite RPD)
3. Razonamiento legal complejo → Qwen 3 235B (thinking mode, gratis en Cerebras)
4. Fallback → Groq Llama 3.3 70B (gratis, rápido)

El router verifica qué API keys están disponibles y selecciona la mejor opción.
"""

import os
import logging
from dataclasses import dataclass

logger = logging.getLogger("tutelas.router")

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
ROUTING_CHAINS = {
    "pdf_multimodal": [
        ("google", "gemini-2.5-flash", "GOOGLE_API_KEY"),
        ("google", "gemini-2.5-pro", "GOOGLE_API_KEY"),
        ("openai", "gpt-4o", "OPENAI_API_KEY"),
    ],
    "extraction": [
        ("deepseek", "deepseek-chat", "DEEPSEEK_API_KEY"),
        ("groq", "llama-3.3-70b-versatile", "GROQ_API_KEY"),
        ("huggingface", "meta-llama/Llama-3.3-70B-Instruct", "HF_TOKEN"),
        ("cerebras", "llama-3.3-70b", "CEREBRAS_API_KEY"),
        ("google", "gemini-2.5-flash", "GOOGLE_API_KEY"),
    ],
    "complex_reasoning": [
        ("cerebras", "qwen-3-235b-a22b-instruct-2507", "CEREBRAS_API_KEY"),
        ("huggingface", "Qwen/Qwen3-235B-A22B-Instruct-2507", "HF_TOKEN"),
        ("deepseek", "deepseek-reasoner", "DEEPSEEK_API_KEY"),
        ("groq", "qwen-qwq-32b", "GROQ_API_KEY"),
        ("google", "gemini-2.5-flash", "GOOGLE_API_KEY"),
    ],
    "legal_analysis": [
        ("cerebras", "qwen-3-235b-a22b-instruct-2507", "CEREBRAS_API_KEY"),
        ("huggingface", "Qwen/Qwen3-235B-A22B-Instruct-2507", "HF_TOKEN"),
        ("deepseek", "deepseek-reasoner", "DEEPSEEK_API_KEY"),
        ("anthropic", "claude-sonnet-4-6-20260320", "ANTHROPIC_API_KEY"),
        ("google", "gemini-2.5-flash", "GOOGLE_API_KEY"),
    ],
    "general": [
        ("groq", "llama-3.3-70b-versatile", "GROQ_API_KEY"),
        ("deepseek", "deepseek-chat", "DEEPSEEK_API_KEY"),
        ("cerebras", "llama-3.3-70b", "CEREBRAS_API_KEY"),
        ("huggingface", "meta-llama/Llama-3.3-70B-Instruct", "HF_TOKEN"),
        ("google", "gemini-2.5-flash", "GOOGLE_API_KEY"),
    ],
    "multilingual": [
        ("cerebras", "qwen-3-235b-a22b-instruct-2507", "CEREBRAS_API_KEY"),
        ("huggingface", "Qwen/Qwen3-235B-A22B-Instruct-2507", "HF_TOKEN"),
        ("deepseek", "deepseek-chat", "DEEPSEEK_API_KEY"),
        ("google", "gemini-2.5-flash", "GOOGLE_API_KEY"),
    ],
}


def route(task_type: str = "general") -> RouteDecision:
    """Seleccionar el mejor proveedor disponible para un tipo de tarea.

    Args:
        task_type: Tipo de tarea (pdf_multimodal, extraction, complex_reasoning, etc.)

    Returns:
        RouteDecision con proveedor, modelo y razón.
    """
    from backend.extraction.ai_extractor import PROVIDERS

    chain = ROUTING_CHAINS.get(task_type, ROUTING_CHAINS["general"])
    fallback = None

    for provider, model, env_key in chain:
        api_key = os.getenv(env_key, "")
        if not api_key:
            continue

        model_config = PROVIDERS.get(provider, {}).get("models", {}).get(model, {})
        decision = RouteDecision(
            provider=provider,
            model=model,
            reason=f"Mejor opción para '{task_type}': {PROVIDERS.get(provider, {}).get('name', provider)} / {model_config.get('label', model)}",
            cost_per_1m_input=model_config.get("input_price", 0),
            cost_per_1m_output=model_config.get("output_price", 0),
            context_window=model_config.get("context_window", 128000),
        )

        # Find fallback (next available in chain)
        if not fallback:
            fallback = decision
        else:
            decision.fallback_provider = fallback.provider
            decision.fallback_model = fallback.model

        logger.info(f"Route [{task_type}] → {provider}/{model} ({decision.reason})")
        return decision

    # Ultimate fallback: Gemini Flash (always available if key exists)
    logger.warning(f"No provider available for task '{task_type}', using Gemini Flash")
    return RouteDecision(
        provider="google",
        model="gemini-2.5-flash",
        reason="Fallback: sin proveedores disponibles para esta tarea",
        cost_per_1m_input=0,
        cost_per_1m_output=0,
        context_window=1000000,
    )


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
