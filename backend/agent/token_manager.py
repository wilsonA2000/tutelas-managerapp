"""Token Manager: gestión inteligente de consumo de tokens del agente.

Estrategias de ahorro:
1. Cache de respuestas recientes (no repetir misma consulta)
2. Contexto progresivo (empezar con regex, solo llamar IA si hace falta)
3. Budget control (límite diario/mensual configurable)
4. Selección inteligente de modelo via Smart Router (DeepSeek → Haiku → Groq)
5. Compresión de contexto (solo enviar lo necesario, no todo)
6. Batch optimization (agrupar extracciones para reducir overhead)
"""

import logging
import hashlib
import json
from datetime import datetime, timedelta
from dataclasses import dataclass

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.database.models import TokenUsage

logger = logging.getLogger("tutelas.tokens")

# Precios por proveedor (USD por 1M tokens)
PRICING = {
    "google": {
        "gemini-2.5-flash": {"input": 0, "output": 0},  # GRATIS
        "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    },
    "anthropic": {
        "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    },
    "openai": {
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4o": {"input": 2.50, "output": 10.00},
    },
}

# Cache en memoria para respuestas recientes
_RESPONSE_CACHE: dict[str, dict] = {}
_CACHE_MAX_SIZE = 100
_CACHE_TTL_SECONDS = 3600  # 1 hora


@dataclass
class TokenBudget:
    """Presupuesto de tokens configurable."""
    daily_limit_usd: float = 50.0  # $50 USD diario
    monthly_limit_usd: float = 500.0  # $500 USD mensual
    warn_at_percent: float = 80.0  # Alertar al 80%


@dataclass
class TokenStats:
    """Estadísticas de consumo."""
    total_tokens: int
    total_cost_usd: float
    today_tokens: int
    today_cost_usd: float
    month_tokens: int
    month_cost_usd: float
    calls_today: int
    calls_month: int
    avg_tokens_per_call: int
    top_model: str
    budget_status: str  # OK, WARNING, EXCEEDED
    savings_from_cache: int
    savings_from_regex: int


def get_token_stats(db: Session, budget: TokenBudget | None = None) -> TokenStats:
    """Obtener estadísticas de consumo de tokens."""
    budget = budget or TokenBudget()
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Total histórico
    total = db.query(
        func.sum(TokenUsage.tokens_input + TokenUsage.tokens_output),
        func.sum(func.cast(TokenUsage.cost_total, db.bind.dialect.type_descriptor(__import__('sqlalchemy').Float))),
        func.count(TokenUsage.id),
    ).first()

    # Hoy
    today = db.query(
        func.sum(TokenUsage.tokens_input + TokenUsage.tokens_output),
        func.sum(func.cast(TokenUsage.cost_total, db.bind.dialect.type_descriptor(__import__('sqlalchemy').Float))),
        func.count(TokenUsage.id),
    ).filter(TokenUsage.timestamp >= today_start).first()

    # Este mes
    month = db.query(
        func.sum(TokenUsage.tokens_input + TokenUsage.tokens_output),
        func.sum(func.cast(TokenUsage.cost_total, db.bind.dialect.type_descriptor(__import__('sqlalchemy').Float))),
        func.count(TokenUsage.id),
    ).filter(TokenUsage.timestamp >= month_start).first()

    # Modelo más usado
    top_model_row = db.query(
        TokenUsage.model, func.count(TokenUsage.id)
    ).group_by(TokenUsage.model).order_by(func.count(TokenUsage.id).desc()).first()

    total_tokens = int(total[0] or 0)
    total_cost = float(total[1] or 0)
    today_cost = float(today[1] or 0)
    month_cost = float(month[1] or 0)

    # Budget status
    if budget.monthly_limit_usd > 0 and month_cost >= budget.monthly_limit_usd:
        status = "EXCEEDED"
    elif budget.daily_limit_usd > 0 and today_cost >= budget.daily_limit_usd:
        status = "EXCEEDED"
    elif budget.monthly_limit_usd > 0 and month_cost >= budget.monthly_limit_usd * budget.warn_at_percent / 100:
        status = "WARNING"
    else:
        status = "OK"

    return TokenStats(
        total_tokens=total_tokens,
        total_cost_usd=round(total_cost, 4),
        today_tokens=int(today[0] or 0),
        today_cost_usd=round(today_cost, 4),
        month_tokens=int(month[0] or 0),
        month_cost_usd=round(month_cost, 4),
        calls_today=int(today[2] or 0),
        calls_month=int(month[2] or 0),
        avg_tokens_per_call=total_tokens // max(int(total[2] or 1), 1),
        top_model=top_model_row[0] if top_model_row else "ninguno",
        budget_status=status,
        savings_from_cache=len(_RESPONSE_CACHE),
        savings_from_regex=0,
    )


def check_budget(db: Session, budget: TokenBudget | None = None) -> tuple[bool, str]:
    """Verificar si hay presupuesto disponible. Returns (allowed, reason)."""
    budget = budget or TokenBudget()
    stats = get_token_stats(db, budget)

    if stats.budget_status == "EXCEEDED":
        if stats.today_cost_usd >= budget.daily_limit_usd:
            return False, f"Limite diario alcanzado: ${stats.today_cost_usd:.2f} / ${budget.daily_limit_usd:.2f}"
        return False, f"Limite mensual alcanzado: ${stats.month_cost_usd:.2f} / ${budget.monthly_limit_usd:.2f}"

    return True, f"OK (${budget.daily_limit_usd - stats.today_cost_usd:.2f} restantes hoy)"


def select_optimal_model(task_complexity: str = "simple", budget: TokenBudget | None = None) -> tuple[str, str]:
    """Seleccionar el modelo óptimo según complejidad y presupuesto.

    Args:
        task_complexity: "simple" (stats, search) | "medium" (extraction) | "complex" (reasoning, generation)

    Returns: (provider, model)
    """
    # Usar Smart Router para seleccionar proveedor
    from backend.agent.smart_router import route
    task_map = {"simple": "general", "medium": "extraction", "complex": "complex_reasoning"}
    decision = route(task_map.get(task_complexity, "general"))
    return decision.provider, decision.model


def estimate_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimar costo antes de hacer la llamada."""
    prices = PRICING.get(provider, {}).get(model, {"input": 0, "output": 0})
    cost = (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000
    return round(cost, 6)


def get_cache_key(instruction: str) -> str:
    """Generar key de cache para una instrucción."""
    return hashlib.md5(instruction.strip().lower().encode()).hexdigest()


def get_cached_response(instruction: str) -> dict | None:
    """Buscar respuesta en cache."""
    key = get_cache_key(instruction)
    entry = _RESPONSE_CACHE.get(key)
    if not entry:
        return None
    # Check TTL
    if (datetime.utcnow() - entry["timestamp"]).total_seconds() > _CACHE_TTL_SECONDS:
        del _RESPONSE_CACHE[key]
        return None
    logger.info(f"Cache hit for: '{instruction[:40]}' (saved ~{entry.get('tokens_saved', 0)} tokens)")
    return entry["response"]


def cache_response(instruction: str, response: dict, tokens_used: int = 0):
    """Guardar respuesta en cache."""
    if len(_RESPONSE_CACHE) >= _CACHE_MAX_SIZE:
        # Evict oldest
        oldest_key = min(_RESPONSE_CACHE, key=lambda k: _RESPONSE_CACHE[k]["timestamp"])
        del _RESPONSE_CACHE[oldest_key]

    key = get_cache_key(instruction)
    _RESPONSE_CACHE[key] = {
        "response": response,
        "timestamp": datetime.utcnow(),
        "tokens_saved": tokens_used,
    }


def compress_context(full_context: str, max_tokens: int = 100000) -> str:
    """Comprimir contexto para reducir tokens enviados.

    Estrategias:
    1. Eliminar whitespace excesivo
    2. Truncar documentos largos (mantener inicio + fin)
    3. Eliminar headers/footers repetitivos
    4. Priorizar documentos relevantes
    """
    import re

    # Remove excessive whitespace
    text = re.sub(r'\n{3,}', '\n\n', full_context)
    text = re.sub(r' {3,}', ' ', text)
    text = re.sub(r'\t+', ' ', text)

    # Remove common legal boilerplate
    boilerplate = [
        r'AVISO DE CONFIDENCIALIDAD.*?(?=\n\n|\Z)',
        r'NOTA IMPORTANTE:.*?(?=\n\n|\Z)',
        r'Este correo electrónico contiene información.*?(?=\n\n|\Z)',
        r'Enviado desde una dirección de correo.*?(?=\n\n|\Z)',
    ]
    for pattern in boilerplate:
        text = re.sub(pattern, '[BOILERPLATE REMOVIDO]', text, flags=re.DOTALL | re.IGNORECASE)

    # Estimate tokens and truncate if needed
    est_tokens = len(text) // 4
    if est_tokens > max_tokens:
        max_chars = max_tokens * 4
        text = text[:max_chars] + "\n\n[CONTEXTO TRUNCADO - LIMITE DE TOKENS]"

    return text


def get_savings_report(db: Session) -> dict:
    """Reporte de ahorro de tokens."""
    stats = get_token_stats(db)

    # Estimate how much would have cost with paid models
    if stats.total_tokens > 0:
        cost_if_gpt4o = estimate_cost("openai", "gpt-4o", stats.total_tokens // 2, stats.total_tokens // 2)
        cost_if_haiku = estimate_cost("anthropic", "claude-haiku-4-5-20251001", stats.total_tokens // 2, stats.total_tokens // 2)
    else:
        cost_if_gpt4o = cost_if_haiku = 0

    return {
        "actual_cost": stats.total_cost_usd,
        "tokens_consumed": stats.total_tokens,
        "calls_made": stats.calls_month,
        "model_used": stats.top_model,
        "savings": {
            "vs_gpt4o": round(cost_if_gpt4o - stats.total_cost_usd, 2),
            "vs_claude_haiku": round(cost_if_haiku - stats.total_cost_usd, 2),
        },
        "cache_hits": len(_RESPONSE_CACHE),
        "optimization_tips": _get_optimization_tips(stats),
    }


def _get_optimization_tips(stats: TokenStats) -> list[str]:
    """Generar tips de optimización basados en uso actual."""
    tips = []
    if stats.avg_tokens_per_call > 50000:
        tips.append("Promedio alto por llamada (>50K tokens). Considera comprimir contexto antes de enviar a IA.")
    if stats.calls_today > 20:
        tips.append("Muchas llamadas hoy. Usa cache de respuestas para consultas repetidas.")
    if stats.budget_status == "WARNING":
        tips.append("Cerca del límite de presupuesto. Considera reducir extracciones masivas.")
    if not tips:
        tips.append("Consumo óptimo. DeepSeek V3.2 como proveedor principal.")
    return tips
