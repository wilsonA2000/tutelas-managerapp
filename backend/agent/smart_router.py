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
    )
