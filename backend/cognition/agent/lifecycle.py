"""Lifecycle manager Qwen ↔ PaddleOCR — swap dinámico de modelos en GPU.

Diseño para usuario único en fase desarrollo + escalable hasta 10 concurrentes:

  ESTADO 'extraction' (default):
      vllm-paddleocr (8118) cargado → puede correr OCR/extracción
      vllm-qwen      (8120) apagado

  ESTADO 'chat':
      vllm-paddleocr apagado
      vllm-qwen cargado    → puede correr chat agente

Transición:
  wake_chat()  : stop paddleocr → start qwen     (~30-90s primera vez)
  sleep_chat() : stop qwen      → start paddleocr (~60s)
  Idle 10 min sin requests al chat → sleep_chat() automático

Locks: archivo /tmp/tutelas_lifecycle.lock evita races.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock, Thread
from typing import Optional

import requests

logger = logging.getLogger("tutelas.cognition.lifecycle")

# Detección de entorno: RunPod (pod con /workspace) vs WSL/local.
# Why: scripts /workspace/*.sh sólo existen en pod RunPod. En WSL delegamos a llm_mutex
# que ya conoce los binarios locales (~/llama.cpp/build/bin/llama-server).
_RUNPOD_MODE = Path("/workspace").exists() and Path("/workspace/start_qwen_server.sh").exists()

# Scripts que orquestan vLLM en el pod (sólo se invocan en RUNPOD_MODE)
START_PADDLEOCR = "/workspace/start_vllm_server.sh"
STOP_PADDLEOCR = "/workspace/stop_paddleocr_server.sh"
START_QWEN = "/workspace/start_qwen_server.sh"
STOP_QWEN = "/workspace/stop_qwen_server.sh"

PADDLEOCR_URL = "http://localhost:8118/v1/models"
QWEN_URL = "http://localhost:8120/v1/models" if _RUNPOD_MODE else os.getenv(
    "LLM_LOCAL_URL", "http://127.0.0.1:8765"
) + "/v1/models"

# Tiempos máximos esperados (s)
MAX_WAIT_QWEN_READY = 180   # primera carga puede ser lenta (cold cache MooseFS)
MAX_WAIT_PADDLEOCR_READY = 120
POLL_INTERVAL = 3

# Auto-sleep tras 10 min sin actividad de chat
IDLE_SLEEP_SECONDS = 600


@dataclass
class LifecycleStatus:
    state: str = "extraction"               # 'extraction' | 'chat' | 'transitioning'
    paddleocr_up: bool = False
    qwen_up: bool = False
    last_chat_activity: float = 0.0
    last_transition_at: float = 0.0
    last_transition_duration_s: Optional[float] = None
    transitioning_since: Optional[float] = None


class ModelLifecycle:
    """Singleton thread-safe que orquesta vLLM PaddleOCR ↔ Qwen."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._status = LifecycleStatus()
        self._idle_thread: Optional[Thread] = None
        self._idle_stop = False

    # ─── healthchecks ──────────────────────────────────────

    @staticmethod
    def _is_up(url: str, timeout: float = 1.5) -> bool:
        try:
            r = requests.get(url, timeout=timeout)
            return r.status_code == 200
        except Exception:
            return False

    def refresh_status(self) -> LifecycleStatus:
        with self._lock:
            self._status.paddleocr_up = self._is_up(PADDLEOCR_URL)
            self._status.qwen_up = self._is_up(QWEN_URL)
            if self._status.transitioning_since is None:
                if self._status.qwen_up and not self._status.paddleocr_up:
                    self._status.state = "chat"
                elif self._status.paddleocr_up and not self._status.qwen_up:
                    self._status.state = "extraction"
                elif self._status.paddleocr_up and self._status.qwen_up:
                    self._status.state = "extraction"  # raro, ambos arriba
                else:
                    self._status.state = "extraction"
            return self._status

    # ─── transiciones ────────────────────────────────────

    def _wait_ready(self, url: str, timeout_s: int) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self._is_up(url):
                return True
            time.sleep(POLL_INTERVAL)
        return False

    @staticmethod
    def _bash(script: str) -> None:
        subprocess.run(["bash", script], check=False, timeout=30)

    @staticmethod
    def _spawn_bash(script: str) -> None:
        subprocess.Popen(
            ["bash", script],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def wake_chat(self) -> LifecycleStatus:
        """Asegura que Qwen esté arriba. Si PaddleOCR está activo, lo apaga primero."""
        with self._lock:
            if self._status.transitioning_since is not None:
                logger.warning("Lifecycle ya en transición — espera")
                return self._status
            if self._is_up(QWEN_URL):
                self._status.state = "chat"
                self._status.qwen_up = True
                self._status.paddleocr_up = self._is_up(PADDLEOCR_URL)
                self._status.last_chat_activity = time.time()
                return self._status
            self._status.transitioning_since = time.time()
            self._status.state = "transitioning"

        t0 = time.time()
        try:
            if _RUNPOD_MODE:
                logger.info("[lifecycle] wake_chat: stopping paddleocr…")
                self._bash(STOP_PADDLEOCR)
                time.sleep(3)
                logger.info("[lifecycle] wake_chat: starting qwen…")
                self._spawn_bash(START_QWEN)
                ok = self._wait_ready(QWEN_URL, MAX_WAIT_QWEN_READY)
                if not ok:
                    logger.error("[lifecycle] qwen no respondió en %ds", MAX_WAIT_QWEN_READY)
            else:
                # WSL/local: delegar a llm_mutex (paths e infra del pod no existen).
                logger.info("[lifecycle] wake_chat (WSL): ensure_llm_up via llm_mutex")
                from backend.services.llm_mutex import ensure_llm_up
                ensure_llm_up(wait_s=MAX_WAIT_QWEN_READY)
        finally:
            with self._lock:
                self._status.transitioning_since = None
                self._status.last_transition_at = time.time()
                self._status.last_transition_duration_s = round(time.time() - t0, 1)
                self._status.qwen_up = self._is_up(QWEN_URL)
                self._status.paddleocr_up = self._is_up(PADDLEOCR_URL)
                self._status.state = "chat" if self._status.qwen_up else "extraction"
                self._status.last_chat_activity = time.time()

        self._ensure_idle_watcher()
        return self._status

    def sleep_chat(self) -> LifecycleStatus:
        """Apaga Qwen y restaura PaddleOCR."""
        with self._lock:
            if self._status.transitioning_since is not None:
                return self._status
            if not self._is_up(QWEN_URL) and self._is_up(PADDLEOCR_URL):
                self._status.state = "extraction"
                self._status.qwen_up = False
                self._status.paddleocr_up = True
                return self._status
            self._status.transitioning_since = time.time()
            self._status.state = "transitioning"

        t0 = time.time()
        try:
            if _RUNPOD_MODE:
                logger.info("[lifecycle] sleep_chat: stopping qwen…")
                self._bash(STOP_QWEN)
                time.sleep(3)
                logger.info("[lifecycle] sleep_chat: starting paddleocr…")
                self._spawn_bash(START_PADDLEOCR)
                self._wait_ready(PADDLEOCR_URL, MAX_WAIT_PADDLEOCR_READY)
            else:
                # WSL/local: pausa llama-server liberando RAM (no hay paddleocr que volver a arrancar).
                logger.info("[lifecycle] sleep_chat (WSL): pause_llm_for_extraction via llm_mutex")
                from backend.services.llm_mutex import pause_llm_for_extraction
                pause_llm_for_extraction()
        finally:
            with self._lock:
                self._status.transitioning_since = None
                self._status.last_transition_at = time.time()
                self._status.last_transition_duration_s = round(time.time() - t0, 1)
                self._status.qwen_up = self._is_up(QWEN_URL)
                self._status.paddleocr_up = self._is_up(PADDLEOCR_URL)
                self._status.state = "extraction" if self._status.paddleocr_up else "chat"
        return self._status

    # ─── activity tracking + auto-sleep ──────────────────

    def mark_chat_activity(self) -> None:
        with self._lock:
            self._status.last_chat_activity = time.time()

    def _ensure_idle_watcher(self) -> None:
        if self._idle_thread is not None and self._idle_thread.is_alive():
            return
        self._idle_stop = False
        self._idle_thread = Thread(target=self._idle_loop, daemon=True,
                                    name="lifecycle-idle-watcher")
        self._idle_thread.start()

    def _idle_loop(self) -> None:
        while not self._idle_stop:
            time.sleep(60)
            with self._lock:
                if self._status.state != "chat":
                    return
                idle = time.time() - self._status.last_chat_activity
            if idle >= IDLE_SLEEP_SECONDS:
                logger.info("[lifecycle] idle %ds — sleep_chat", int(idle))
                try:
                    self.sleep_chat()
                except Exception:
                    logger.exception("auto sleep falló")
                return


lifecycle = ModelLifecycle()
