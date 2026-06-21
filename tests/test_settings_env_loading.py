"""Guard 2026-06-20: backend.core.settings debe cargar el .env EFECTIVO a os.environ
(no solo al objeto Pydantic), para que los flags leídos con os.getenv() (V9_LLM_*,
RAMA_JUDICIAL_*, LLM_GGUF/CTX/REASONING, LLM_LOCAL_PRIMARY en chat.py, …) reflejen el
.env y no su default. Sin esto quedaban INERTES. Ver project_env_flags_inertes."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import backend.core.settings as settings_mod  # su import dispara load_dotenv


def test_load_dotenv_mecanismo(tmp_path):
    """El mecanismo base: load_dotenv vuelca KEY=VALUE a os.environ (override=False)."""
    from dotenv import load_dotenv
    envf = tmp_path / ".env.probe"
    envf.write_text("FLAG_PRUEBA_ENV_XYZ=hola123\n")
    os.environ.pop("FLAG_PRUEBA_ENV_XYZ", None)
    load_dotenv(str(envf), override=False)
    assert os.getenv("FLAG_PRUEBA_ENV_XYZ") == "hola123"


def test_settings_volcó_el_env_real_a_os_environ():
    """En un entorno con .env real, importar settings deja sus flags simples visibles
    vía os.getenv. Se saltan los forzados por conftest y los secretos."""
    env_file = Path(settings_mod._EFFECTIVE_ENV_FILE)
    if not env_file.exists():
        pytest.skip("no hay .env en este entorno")
    forzados = {"RAMA_JUDICIAL_ENABLED", "RAMA_JUDICIAL_SYNC_CRON",
                "V9_DISABLE_LLM", "LLM_LOCAL_PRIMARY"}
    probados = 0
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.split("#")[0].strip().strip('"').strip("'")
        if (not v or k in forzados
                or any(s in k for s in ("KEY", "SECRET", "TOKEN", "PASSWORD"))
                or " " in v):
            continue
        assert os.getenv(k) == v, f"{k}: os.getenv={os.getenv(k)!r} != .env={v!r}"
        probados += 1
        if probados >= 3:
            break
    if probados == 0:
        pytest.skip("no hay flag simple no-forzado en el .env para verificar")
