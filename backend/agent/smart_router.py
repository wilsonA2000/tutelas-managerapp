"""Smart Router minimalista — siempre retorna provider local.

Versión simplificada: sin fallback chain, sin priorización por tarea, sin
selección de proveedor según rate limits. La decisión es trivial:
LOCAL_ONLY=true (default) → siempre local.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class RouteDecision:
    provider: str
    model: str
    reason: str = ""
    fallback_provider: Optional[str] = None
    fallback_model: Optional[str] = None
    cost_per_1m_input: float = 0.0
    cost_per_1m_output: float = 0.0
    context_window: int = 32768


# Tipos de tarea soportados (legacy compat).
TASK_TYPES = [
    "extraction",
    "classification",
    "chat",
    "summary",
    "validation",
]


def route(task_type: str = "extraction") -> RouteDecision:
    """Selecciona LLM. Siempre retorna local en versión minimalista.

    Args:
        task_type: ignorado (legacy compat).

    Returns:
        RouteDecision apuntando a llama-server local.
    """
    model = os.getenv("LLM_LOCAL_MODEL_ID", "qwen3-4b-iuris")
    return RouteDecision(
        provider="local",
        model=model,
        reason="LOCAL_ONLY: solo proveedor local en producción",
        fallback_provider=None,
        fallback_model=None,
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
        context_window=int(os.getenv("LLM_LOCAL_CTX", "32768")),
    )


def get_available_routes() -> dict[str, RouteDecision]:
    """Devuelve un mapping task_type → RouteDecision (todos local en LOCAL_ONLY)."""
    return {t: route(t) for t in TASK_TYPES}


def get_configured_providers() -> dict[str, dict]:
    """Información de proveedores configurados. En LOCAL_ONLY solo el local."""
    local_url = os.getenv("LLM_LOCAL_URL", "http://127.0.0.1:8765")
    local_model = os.getenv("LLM_LOCAL_MODEL_ID", "qwen3-4b-iuris")
    return {
        "local": {
            "url": local_url,
            "model": local_model,
            "active": True,
            "cost_per_1m": 0.0,
            "note": "Qwen3 vía llama-server (LOCAL_ONLY)",
        },
    }
