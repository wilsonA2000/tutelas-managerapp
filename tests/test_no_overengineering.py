"""Guardrails anti-sobrepensadera (de-sobreingeniería Fase 5 — pilar prevención).

Institucionaliza la detección de over-engineering para que NO se vuelva a acumular:
- Todo flag de settings.py debe leerse en algún lado (si no, es muerto → borrar).

Esto convierte "53% de flags inertes" (estado pre-de-sobreingeniería) en un invariante:
un flag nuevo sin consumidor rompe el build, forzando a borrarlo o cablearlo.
"""
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent

# Flags accedidos de forma dinámica (no por nombre literal) — allowlist explícita.
# Vacía a propósito: hoy todos los flags se leen por nombre. Agregar aquí SOLO con
# justificación documentada, nunca para silenciar un flag realmente muerto.
_DYNAMIC_ALLOWLIST: set[str] = set()


def _settings_flag_names() -> list[str]:
    from backend.core.settings import Settings
    return list(Settings.model_fields.keys())


def _is_referenced(flag: str) -> bool:
    """¿El flag se lee en backend/ (settings.X / getattr(settings,"X") / getenv("X"))?"""
    pattern = rf"(settings\.{flag}\b|getattr\(settings,\s*['\"]{flag}['\"]|getenv\(['\"]{flag}['\"]|environ\[?['\"]{flag}['\"])"
    res = subprocess.run(
        ["grep", "-rEl", pattern, "backend"],
        capture_output=True, text=True, cwd=ROOT,
    )
    hits = [l for l in res.stdout.splitlines() if not l.endswith("core/settings.py")]
    return bool(hits)


def test_every_settings_flag_is_read():
    """Cada flag de settings.py se referencia ≥1 vez fuera de su definición.

    Si este test falla con un flag nuevo: o lo cableas (úsalo) o lo borras. No se
    permite acumular flags inertes (causa raíz del 53% de flags muertos en 2026-06).
    """
    dead = [
        f for f in _settings_flag_names()
        if f not in _DYNAMIC_ALLOWLIST and not _is_referenced(f)
    ]
    assert not dead, (
        "Flags de settings.py sin consumidor (muertos → borrar o cablear): "
        + ", ".join(sorted(dead))
    )
