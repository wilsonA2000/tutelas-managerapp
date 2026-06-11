"""Extractor de campos usando IA local (Qwen3-4B + LoRA-CoT v2).

Versión MINIMALISTA — solo provider local. Sin fallbacks externos.
LOCAL_ONLY=true is mandatory. Si llama-server cae, falla limpio (no enmascara).
"""

from __future__ import annotations

import json
import os
import re
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("tutelas.ai_extractor")
_logger = logger


# ============================================================
# Configuración
# ============================================================

_LOCAL_URL = os.getenv("LLM_LOCAL_URL", "http://127.0.0.1:8765")
_LOCAL_MODEL = os.getenv("LLM_LOCAL_MODEL_ID", "qwen3-4b-iuris")
_LOCAL_TIMEOUT = int(os.getenv("LLM_LOCAL_TIMEOUT", "180"))
_SYSTEM_PROMPT_PATH = os.getenv("LLM_LOCAL_SYSTEM_PROMPT_PATH", "docs/iuris/SYSTEM_PROMPT_COMPILER.md")
# Proveedor externo (DeepSeek) — DESCONECTADO por default. Requiere V9_ALLOW_DEEPSEEK=true
# (opt-in explícito) Y V9_LLM_API_KEY. Sin el flag, _call_local es SIEMPRE local puro
# aunque haya key (2026-05-25, decisión de Wilson). Si se setea, _call_local apunta a un
# proveedor OpenAI-compatible externo (agrega Authorization Bearer + `model`).
_ALLOW_DEEPSEEK = os.getenv("V9_ALLOW_DEEPSEEK", "false").lower() == "true"
_LLM_API_KEY = os.getenv("V9_LLM_API_KEY", "") if _ALLOW_DEEPSEEK else ""


def _load_system_prompt() -> str:
    """Carga prompt auditado desde disco; cae al hardcoded si no existe."""
    try:
        path = Path(_SYSTEM_PROMPT_PATH)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent.parent / _SYSTEM_PROMPT_PATH
        if path.exists():
            return path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("No pude cargar system prompt %s: %s", _SYSTEM_PROMPT_PATH, e)
    return SYSTEM_PROMPT


@dataclass
class AIFieldResult:
    value: str
    confidence: str = "MEDIA"  # ALTA / MEDIA / BAJA
    source: str = ""


@dataclass
class AIExtractionResult:
    fields: dict[str, AIFieldResult] = field(default_factory=dict)
    raw_response: str = ""
    tokens_input: int = 0
    tokens_output: int = 0
    tokens_used: int = 0
    provider: str = "local"
    model: str = _LOCAL_MODEL
    duration_ms: int = 0
    chunks_used: int = 1
    error: Optional[str] = None


# ============================================================
# System prompt cognitivo
# ============================================================

SYSTEM_PROMPT = """Eres un asistente jurídico especializado en derecho colombiano y procesos de tutela.
Tu tarea es leer expedientes y extraer información estructurada con precisión.

Reglas:
- Devuelves SOLO JSON válido. Nunca texto adicional fuera del JSON.
- Si un campo NO está claramente en el texto, devuelves null. NUNCA inventas.
- Fechas en formato DD/MM/YYYY.
- Fallos: usa exactamente "AMPARA", "NIEGA", "DECLARA HECHO SUPERADO" o "IMPROCEDENTE".
- forest_impugnacion: número FOREST de 7 dígitos.
- juzgado_2nd: nombre completo del juzgado de segunda instancia.
"""


# ============================================================
# Llamada al LLM local
# ============================================================

def _call_local(messages: list[dict], model: str = _LOCAL_MODEL,
                max_tokens: int = 1024) -> tuple[str, int, int]:
    """Llama al servidor llama-server local. NO tiene fallback.

    Si falla, levanta excepción — el caller debe manejar.
    """
    # Muestreo por env, mismas perillas que v9/llm_gap_fill (defaults = comportamiento
    # histórico greedy). Para Qwen3-*-Instruct-2507 el greedy DEGENERA (bucles 'ccc…',
    # sopa de inglés) — Qwen recomienda temp 0.7 / top_p 0.8 / top_k 20.
    payload = {
        "messages": messages,
        "temperature": float(os.getenv("V9_LLM_TEMPERATURE", "0.0")),
        "top_p": float(os.getenv("V9_LLM_TOP_P", "1.0")),
        "seed": 42,
        "max_tokens": max_tokens,
    }
    if os.getenv("V9_LLM_TOP_K"):
        payload["top_k"] = int(os.getenv("V9_LLM_TOP_K"))
    headers = {}
    if not _LLM_API_KEY:
        # Anti-degeneración: con greedy (temp=0) y sin penalización, el Qwen 4B local
        # cae en bucles repetitivos ("1 1 1 1...", "_ _ _ _...") que además alargan el
        # cómputo y disparan fence timeouts en la iGPU. repeat_penalty los corta.
        payload["repeat_penalty"] = float(os.getenv("V9_LLM_REPEAT_PENALTY", "1.15"))
    if _LLM_API_KEY:  # proveedor externo (DeepSeek): requiere model + auth.
        # Los callers pasan model local ("qwen3-4b-iuris") que el externo no conoce →
        # usar el modelo del env (_LOCAL_MODEL = LLM_LOCAL_MODEL_ID, ej. deepseek-chat).
        payload["model"] = _LOCAL_MODEL
        headers["Authorization"] = f"Bearer {_LLM_API_KEY}"
    try:
        response = requests.post(
            f"{_LOCAL_URL}/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=_LOCAL_TIMEOUT,
        )
    except requests.exceptions.ConnectionError:
        # M3 2026-06-11: server local caído (vk::DeviceLostError bajo carga sostenida)
        # → respawn + UN reintento, en vez de fallar el campo en silencio.
        if not _LLM_API_KEY and ("127.0.0.1" in _LOCAL_URL or "localhost" in _LOCAL_URL):
            from backend.services.llm_mutex import ensure_llm_up
            if ensure_llm_up(wait_s=120):
                response = requests.post(
                    f"{_LOCAL_URL}/v1/chat/completions",
                    json=payload, headers=headers, timeout=_LOCAL_TIMEOUT,
                )
            else:
                raise
        else:
            raise
    response.raise_for_status()
    data = response.json()
    text = data["choices"][0]["message"]["content"]
    # Filtrar bloque <think>...</think> que el LoRA-CoT genera
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    usage = data.get("usage", {}) or {}
    return text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


# ============================================================
# Helper: parsear JSON de IA
# ============================================================

def _parse_ai_json(raw: str) -> dict[str, AIFieldResult]:
    """Parsea JSON de respuesta IA, tolerando texto preludio/posludio."""
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        raw = m.group(0)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Intentar reparar JSON truncado
        fixed = raw.rstrip()
        open_braces = fixed.count("{") - fixed.count("}")
        last_comma = fixed.rfind(",")
        if last_comma > 0 and open_braces > 0:
            fixed = fixed[:last_comma]
        fixed += "}" * max(0, open_braces)
        data = json.loads(fixed)

    fields_data = data.get("fields", data)
    result = {}
    for field_name, info in fields_data.items():
        if isinstance(info, dict):
            value = str(info.get("value", "")).strip()
            confidence = info.get("confidence", "MEDIA")
            source = info.get("source", "")
        elif isinstance(info, str):
            value = info.strip()
            confidence = "MEDIA"
            source = ""
        else:
            continue
        if value and value.lower() not in ("null", "none", "n/a", "no aplica"):
            result[field_name] = AIFieldResult(value=value, confidence=confidence, source=source)
    return result


# ============================================================
# Heurística PDFs críticos
# ============================================================

CRITICAL_KEYWORDS = {"auto", "admite", "avoca", "sentencia", "fallo", "impugn",
                     "incidente", "desacato", "forest", "respuesta", "rta", "escrito"}


def _is_critical_pdf(filename: str) -> bool:
    fn = filename.lower()
    return any(k in fn for k in CRITICAL_KEYWORDS)


# ============================================================
# Anti-contaminación (folder name + radicado oficial)
# ============================================================

def _build_anti_contamination_block(folder_name: str, radicado_oficial: str) -> str:
    blocks = []
    if folder_name:
        blocks.append(f"NOMBRE DE CARPETA (referencia): {folder_name}")
    if radicado_oficial:
        blocks.append(f"RADICADO OFICIAL del caso: {radicado_oficial}\n"
                      f"NO uses radicados ajenos que aparezcan en docs anexos. "
                      f"Solo extrae info de ESTE caso.")
    return "\n".join(blocks)


# ============================================================
# Función principal: extract_with_ai
# ============================================================

def extract_with_ai(documents: list[dict], folder_name: str = "",
                    radicado_oficial: str = "",
                    pdf_file_paths: Optional[list[str]] = None) -> AIExtractionResult:
    """Extrae 28 campos del expediente vía LLM local.

    Args:
        documents: lista de {filename, text, doc_type}
        folder_name: nombre carpeta del caso (anti-contaminación)
        radicado_oficial: radicado oficial (anti-contaminación)
        pdf_file_paths: legacy compat — ignorado en versión minimalista

    Returns:
        AIExtractionResult con campos parseados o error si falla.
    """
    # Hard-fail si LOCAL_ONLY no está configurado correctamente
    if not _LOCAL_URL:
        return AIExtractionResult(error="LLM_LOCAL_URL no configurado en .env")

    # Priorizar docs críticos primero (admite, fallo, sentencia, impugn, incidente)
    KEY_PRIORITY = {
        "auto": 1, "admite": 1, "avoca": 1, "escrito": 1,
        "sentencia": 2, "fallo": 2,
        "forest": 3, "respuesta": 3, "rta": 3,
        "gmail": 4, "rv_": 4, "email": 4,
        "impugn": 5,
        "incidente": 6, "desacato": 6,
    }

    def _doc_priority(d):
        name = d.get("filename", "").lower()
        for keyword, pri in KEY_PRIORITY.items():
            if keyword in name:
                return pri
        return 9

    sorted_docs = sorted(documents, key=_doc_priority)

    doc_texts = []
    for doc in sorted_docs:
        text = doc.get("text", "").strip()
        if not text:
            continue
        if not _is_critical_pdf(doc.get("filename", "")) and len(text) > 25000:
            text = text[:20000] + "\n[...CONTENIDO TRUNCADO...]\n" + text[-5000:]
        elif len(text) > 15000:
            # cap también docs críticos para no inflar el prompt en CPU 4B
            text = text[:10000] + "\n[...CONTENIDO TRUNCADO...]\n" + text[-3000:]
        doc_type = doc.get("doc_type", "OTRO")
        doc_texts.append(f"\n===ARCHIVO: {doc['filename']} [TIPO: {doc_type}]===\n{text}")

    if not doc_texts:
        return AIExtractionResult(error="No hay texto para analizar")

    all_text = "".join(doc_texts)

    try:
        start_time = time.time()
        anti_cont = _build_anti_contamination_block(folder_name, radicado_oficial)
        user_message = (
            f"{anti_cont}\n\n"
            f"DOCUMENTOS DEL EXPEDIENTE:\n{all_text}\n\n"
            f"Analiza TODOS los documentos y extrae los 28 campos del protocolo. "
            f"Responde SOLO con el JSON. RESPONDE EN ESPAÑOL."
        )

        messages = [
            {"role": "system", "content": _load_system_prompt()},
            {"role": "user", "content": user_message},
        ]

        raw, in_tok, out_tok = _call_local(messages, _LOCAL_MODEL, max_tokens=1024)
        duration_ms = int((time.time() - start_time) * 1000)

        all_fields = _parse_ai_json(raw)

        return AIExtractionResult(
            fields=all_fields,
            raw_response=raw,
            tokens_input=in_tok,
            tokens_output=out_tok,
            tokens_used=in_tok + out_tok,
            provider="local",
            model=_LOCAL_MODEL,
            duration_ms=duration_ms,
        )

    except Exception as e:
        logger.error("Extract IA local falló: %s", str(e)[:200])
        return AIExtractionResult(
            error=f"LLM local error: {str(e)[:200]}",
            provider="local",
            model=_LOCAL_MODEL,
        )
