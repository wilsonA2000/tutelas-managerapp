"""Contadores de fallbacks silenciosos (Fase 3 — confiabilidad).

Antes, varios `except: pass` se tragaban errores sin dejar rastro (un plazo de
desacato no detectado, un OCR que cayó a legacy, un índice KB que no se actualizó).
Esto los hace VISIBLES: cuenta cuántas veces se dispara cada fallback y deja un
WARNING en el log. El agregador `/api/health/appliance` (Fase 5) expone los conteos.

No cambia el comportamiento (el fallback sigue ocurriendo) — solo lo observa.
"""
from __future__ import annotations

import logging
from collections import Counter
from threading import Lock

logger = logging.getLogger("tutelas.fallbacks")

_counts: Counter = Counter()
_lock = Lock()


def record_fallback(name: str, detail: str = "") -> None:
    """Registra una ocurrencia de fallback silencioso y la loguea."""
    with _lock:
        _counts[name] += 1
        n = _counts[name]
    logger.warning("fallback[%s] (#%d) %s", name, n, str(detail)[:200])


def get_fallback_counts() -> dict[str, int]:
    """Conteos acumulados desde el arranque (para health/appliance)."""
    with _lock:
        return dict(_counts)


def reset_fallback_counts() -> None:
    with _lock:
        _counts.clear()
