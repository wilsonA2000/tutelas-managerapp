"""Cliente DeepSeek para el pipeline experimental."""
from __future__ import annotations
import json
import logging
import os
import urllib.request
from typing import Optional

log = logging.getLogger("tutelas.deepseek_pipeline.client")

# Lee desde settings o env directamente. Misma política que v9/llm_gap_fill:
# DeepSeek requiere V9_ALLOW_DEEPSEEK=true ADEMÁS de la key (la key sola no
# basta — decisión de Wilson 2026-05-25, local-first).
def _allow_deepseek() -> bool:
    return os.getenv("V9_ALLOW_DEEPSEEK", "false").lower() == "true"


def _get_key() -> str:
    if not _allow_deepseek():
        return ""
    key = os.getenv("V9_LLM_API_KEY", "") or os.getenv("DEEPSEEK_API_KEY", "")
    return key

def _get_url() -> str:
    return os.getenv("LLM_LOCAL_URL", "https://api.deepseek.com")

def _get_model() -> str:
    return os.getenv("LLM_LOCAL_MODEL_ID", "deepseek-chat")


def call_deepseek(
    system_prompt: str,
    user_message: str,
    *,
    max_tokens: int = 1500,
    temperature: float = 0,
    json_mode: bool = True,
) -> Optional[str]:
    """
    Llama a DeepSeek y devuelve el contenido del mensaje.
    Retorna None si falla.
    """
    key = _get_key()
    if not key:
        raise ValueError("DEEPSEEK_API_KEY / V9_LLM_API_KEY no configurada")

    body: dict = {
        "model": _get_model(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }
    req = urllib.request.Request(
        _get_url() + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers=headers,
    )
    try:
        raw = urllib.request.urlopen(req, timeout=120).read().decode()
        return json.loads(raw)["choices"][0]["message"]["content"] or ""
    except Exception as exc:
        log.warning("DeepSeek call falló: %s", str(exc)[:200])
        raise


def call_deepseek_json(system_prompt: str, user_message: str, **kwargs) -> dict:
    """Llama a DeepSeek y parsea la respuesta como JSON. Lanza si falla."""
    raw = call_deepseek(system_prompt, user_message, json_mode=True, **kwargs)
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        # Intentar extraer el primer bloque JSON
        import re
        m = re.search(r"\{[\s\S]*\}", raw or "")
        if m:
            return json.loads(m.group(0))
        raise ValueError(f"Respuesta no es JSON válido: {str(raw)[:200]}") from exc


def is_available() -> bool:
    """DeepSeek disponible = opt-in explícito (V9_ALLOW_DEEPSEEK=true) + key."""
    return bool(_get_key())
