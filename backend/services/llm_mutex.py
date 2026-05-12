"""Mutex llama-server ↔ extraction batch.

Razón: con 8 GB WSL, 4 workers de extracción consumen ~9.2 GB pico (sin
contar buffers). El llama-server (Qwen3-4B Q4_K_M) consume ~2.5 GB. Si
ambos están activos durante batch, OOM. Solución: pausar llama-server
antes del batch, reiniciar lazy al primer chat post-batch.

Usage:
    from backend.services.llm_mutex import pause_llm_for_extraction, ensure_llm_up

    # Antes de batch
    paused = pause_llm_for_extraction()

    # ... ejecuta batch ...

    # Después: el primer call al chat re-arranca lazy via ensure_llm_up()

Diseño thread-safe con file lock (/tmp/iuris_llm_mutex.lock).
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import time
from pathlib import Path
from threading import Lock

import requests

logger = logging.getLogger("tutelas.llm_mutex")

LLM_PORT = int(os.getenv("LLM_LOCAL_PORT", "8765"))
LLM_URL = os.getenv("LLM_LOCAL_URL", f"http://127.0.0.1:{LLM_PORT}")
LLM_HEALTH = f"{LLM_URL}/v1/models"

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LLAMA_BIN = Path.home() / "llama.cpp" / "build" / "bin" / "llama-server"
GGUF_BASE = PROJECT_ROOT / "data" / "lora-models" / "Qwen3-4B-Q4_K_M.gguf"
GGUF_LORA = PROJECT_ROOT / "data" / "lora-models" / "iuris-lora-qwen3-4b.gguf"

PAUSE_FLAG = Path("/tmp/iuris_llm_paused.flag")
PID_FILE = Path("/tmp/iuris_llm_server.pid")
_lock = Lock()


def is_up(timeout: float = 1.5) -> bool:
    try:
        r = requests.get(LLM_HEALTH, timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def _kill_by_port(port: int) -> int:
    """Mata cualquier proceso escuchando en `port`. Retorna # killed."""
    killed = 0
    try:
        out = subprocess.run(
            ["fuser", "-k", f"{port}/tcp"],
            capture_output=True, text=True, timeout=10,
        )
        # fuser exit 0 = killed; 1 = nothing to kill
        if out.returncode == 0:
            killed = 1
    except Exception as e:
        logger.warning("fuser -k %d falló: %s", port, e)
    return killed


def pause_llm_for_extraction() -> bool:
    """Detiene llama-server para liberar RAM antes de batch.

    Retorna True si pausó algo, False si ya estaba abajo.
    Crea PAUSE_FLAG para señalar que debe relanzarse después.
    """
    with _lock:
        if not is_up(timeout=1.0):
            logger.info("LLM no está corriendo — nada que pausar")
            PAUSE_FLAG.touch(exist_ok=True)
            return False
        logger.info("Pausando llama-server :%d para extraction batch", LLM_PORT)
        killed = _kill_by_port(LLM_PORT)
        PAUSE_FLAG.touch(exist_ok=True)
        # Esperar a que el puerto se libere
        for _ in range(10):
            if not is_up(timeout=0.5):
                logger.info("llama-server bajó · liberada RAM")
                return True
            time.sleep(0.5)
        logger.warning("llama-server no respondió al kill (port %d sigue activo)", LLM_PORT)
        return killed > 0


def _spawn_llm() -> int:
    """Lanza llama-server en background. Retorna PID."""
    if not LLAMA_BIN.exists():
        raise RuntimeError(f"llama-server no encontrado: {LLAMA_BIN}")
    if not GGUF_BASE.exists():
        raise RuntimeError(f"GGUF base no encontrado: {GGUF_BASE}")

    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"llama_server_{int(time.time())}.log"

    # v8.3: LoRA opcional via env. A/B test 2026-05-08 mostró que el LoRA actual
    # (iuris-lora-qwen3-4b) baja la tasa de extraccion del 50% al 25% en CPU.
    # Default OFF; activar con LLM_LORA_ENABLED=true si se reentrena con dataset depurado.
    use_lora = os.getenv("LLM_LORA_ENABLED", "false").lower() == "true"
    cmd = [
        str(LLAMA_BIN),
        "-m", str(GGUF_BASE),
        "--port", str(LLM_PORT),
        "--ctx-size", "4096",
        "-t", "6",
        "--host", "127.0.0.1",
    ]
    if use_lora and GGUF_LORA.exists():
        cmd.insert(3, "--lora")
        cmd.insert(4, str(GGUF_LORA))
        logger.info("llama-server lanzado con LoRA: %s", GGUF_LORA.name)
    else:
        logger.info("llama-server lanzado SIN LoRA (base puro Qwen3-4B)")
    log_fp = open(log_path, "wb")
    proc = subprocess.Popen(cmd, stdout=log_fp, stderr=subprocess.STDOUT,
                            start_new_session=True)
    PID_FILE.write_text(str(proc.pid))
    logger.info("llama-server lanzado pid=%d log=%s", proc.pid, log_path.name)
    return proc.pid


def _is_loading() -> bool:
    """503 'Loading model' = proceso vivo cargando tensores."""
    try:
        r = requests.get(LLM_HEALTH, timeout=1.0)
        return r.status_code == 503
    except Exception:
        return False


def _process_alive() -> bool:
    """Hay un llama-server escuchando en :8765 aunque sea cargando."""
    return is_up(timeout=0.5) or _is_loading()


def ensure_llm_up(wait_s: int = 60) -> bool:
    """Garantiza que llama-server esté arriba (lazy start si no).

    Comportamiento:
    - Si UP (200): retorna True inmediato.
    - Si LOADING (503): espera hasta wait_s. Si listo, True. Si timeout, False.
    - Si DOWN: lanza spawn fire-and-forget y espera wait_s.
    """
    if is_up(timeout=1.5):
        return True

    with _lock:
        if is_up(timeout=1.5):
            return True
        # Si ya hay un proceso cargando, no spawn duplicado
        if _is_loading():
            logger.info("llama-server ya cargando — esperando...")
        else:
            # Verificar que tenemos los archivos necesarios
            if not GGUF_BASE.exists() or not LLAMA_BIN.exists():
                logger.warning("llama-server no instalado — chat operará solo en Tier 1")
                return False
            try:
                _spawn_llm()
            except Exception as e:
                logger.error("ensure_llm_up: spawn falló: %s", e)
                return False

    # Wait for ready
    for i in range(wait_s):
        if is_up(timeout=1.0):
            logger.info("llama-server listo tras %ds", i)
            try:
                PAUSE_FLAG.unlink(missing_ok=True)
            except Exception:
                pass
            return True
        time.sleep(1)
    logger.warning("llama-server no listo tras %ds (puede seguir cargando)", wait_s)
    return False


def is_warming() -> bool:
    """True si proceso vivo pero todavía cargando (UI puede mostrar spinner)."""
    return _is_loading()


def status() -> dict:
    """Reporte de estado para health check."""
    return {
        "llm_up": is_up(timeout=1.0),
        "paused_flag": PAUSE_FLAG.exists(),
        "pid_file": PID_FILE.read_text().strip() if PID_FILE.exists() else None,
        "gguf_base_exists": GGUF_BASE.exists(),
        "gguf_lora_exists": GGUF_LORA.exists(),
    }
