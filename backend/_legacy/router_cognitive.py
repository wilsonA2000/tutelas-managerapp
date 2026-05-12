"""Router cognitive v9.0 — agente jurídico Qwen 7B + tools + RAG BGE-M3."""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.cognition.agent.lifecycle import lifecycle, LifecycleStatus
from backend.cognition.agent.orchestrator import chat as run_chat, ChatTurn
from backend.cognition.agent.semantic_enricher import (
    enrich_case as run_enrich, TARGETS as ENRICH_TARGETS, EnrichmentResult,
    enrich_deterministic_only,
)

logger = logging.getLogger("tutelas.api.cognitive")

router = APIRouter(prefix="/api/cognitive", tags=["cognitive"])


class StatusOut(BaseModel):
    state: str
    paddleocr_up: bool
    qwen_up: bool
    last_chat_activity: float
    last_transition_at: float
    last_transition_duration_s: float | None
    transitioning: bool


def _to_out(s: LifecycleStatus) -> StatusOut:
    return StatusOut(
        state=s.state,
        paddleocr_up=s.paddleocr_up,
        qwen_up=s.qwen_up,
        last_chat_activity=s.last_chat_activity,
        last_transition_at=s.last_transition_at,
        last_transition_duration_s=s.last_transition_duration_s,
        transitioning=s.transitioning_since is not None,
    )


@router.get("/status", response_model=StatusOut)
def cognitive_status():
    """Estado actual del lifecycle de modelos."""
    return _to_out(lifecycle.refresh_status())


@router.post("/wake", response_model=StatusOut)
def cognitive_wake():
    """Asegura que Qwen esté arriba. Si PaddleOCR está activo, lo apaga.

    Bloquea hasta que el modelo esté listo (cold start ~90s primera vez).
    """
    s = lifecycle.wake_chat()
    if not s.qwen_up:
        raise HTTPException(503, "Qwen no logró arrancar — revisa /workspace/qwen_server.log")
    return _to_out(s)


@router.post("/sleep", response_model=StatusOut)
def cognitive_sleep():
    """Apaga Qwen y restaura PaddleOCR (libera GPU para extracción)."""
    s = lifecycle.sleep_chat()
    return _to_out(s)


# ─── Chat agente ─────────────────────────────────────────────

class ChatContext(BaseModel):
    current_case_id: int | None = None
    current_view: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    history: list[dict] | None = None
    context: ChatContext | None = None


class ToolTraceOut(BaseModel):
    name: str
    args: dict
    result_summary: str
    duration_ms: float


class ChatResponse(BaseModel):
    answer: str
    tools_used: list[ToolTraceOut]
    total_ms: float
    qwen_tokens_in: int
    qwen_tokens_out: int


# ─── Enriquecimiento semántico (Capa 4.6) ────────────────────

class EnrichRequest(BaseModel):
    targets: list[str] | None = None
    overwrite: bool = False


class EnrichResponse(BaseModel):
    case_id: int
    targets_attempted: list[str]
    fields_filled: dict[str, str]
    fields_skipped: dict[str, str]
    qwen_calls: int
    total_ms: float
    tokens_in: int
    tokens_out: int
    error: str | None = None


@router.post("/enrich/{case_id}", response_model=EnrichResponse)
def cognitive_enrich(case_id: int, req: EnrichRequest | None = None):
    """Llama a Qwen para rellenar campos vacíos del caso con análisis semántico.

    Targets disponibles: responsable_desacato, decision_incidente, quien_impugno,
                         juzgado_2nd, categoria_tematica.
    """
    body = req or EnrichRequest()
    result: EnrichmentResult = run_enrich(case_id,
        targets=body.targets, overwrite=body.overwrite)
    return EnrichResponse(
        case_id=result.case_id,
        targets_attempted=result.targets_attempted,
        fields_filled=result.fields_filled,
        fields_skipped=result.fields_skipped,
        qwen_calls=result.qwen_calls,
        total_ms=result.total_ms,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        error=result.error,
    )


@router.post("/enrich-deterministic/{case_id}", response_model=EnrichResponse)
def cognitive_enrich_deterministic(case_id: int):
    """Enriquecimiento solo con reglas jurídicas deterministas (sin Qwen).

    Aplica derivación juzgado_2nd vía mapa judicial Santander + clasificación
    SED por keyword matching. Cero tokens, ~5ms/caso.
    """
    result = enrich_deterministic_only(case_id)
    return EnrichResponse(
        case_id=result.case_id,
        targets_attempted=result.targets_attempted,
        fields_filled=result.fields_filled,
        fields_skipped=result.fields_skipped,
        qwen_calls=0,
        total_ms=result.total_ms,
        tokens_in=0,
        tokens_out=0,
        error=result.error,
    )


@router.post("/enrich-deterministic-batch")
def cognitive_enrich_deterministic_batch():
    """Aplica reglas deterministas a TODOS los casos en DB. Sin Qwen.

    Retorna estadísticas de cobertura antes/después por columna.
    """
    import sqlite3
    from backend.cognition.agent.semantic_enricher import DB_PATH

    cols_target = ("juzgado_2nd", "direccion", "grupo", "equipo", "categoria_tematica")
    conn = sqlite3.connect(DB_PATH)
    before = {}
    for col in cols_target:
        try:
            before[col] = conn.execute(
                f"SELECT COUNT(*) FROM cases WHERE {col} IS NOT NULL"
            ).fetchone()[0]
        except Exception:
            before[col] = None
    total = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    case_ids = [r[0] for r in conn.execute("SELECT id FROM cases").fetchall()]
    conn.close()

    results = []
    total_ms = 0.0
    cases_modified = 0
    for cid in case_ids:
        r = enrich_deterministic_only(cid)
        total_ms += r.total_ms
        if r.fields_filled:
            cases_modified += 1
            results.append({"case_id": cid, "filled": list(r.fields_filled.keys())})

    conn = sqlite3.connect(DB_PATH)
    after = {}
    for col in cols_target:
        try:
            after[col] = conn.execute(
                f"SELECT COUNT(*) FROM cases WHERE {col} IS NOT NULL"
            ).fetchone()[0]
        except Exception:
            after[col] = None
    conn.close()

    coverage = {
        col: {
            "before": before[col],
            "after": after[col],
            "delta": (after[col] or 0) - (before[col] or 0),
            "before_pct": round((before[col] or 0) / total * 100, 1),
            "after_pct": round((after[col] or 0) / total * 100, 1),
        }
        for col in cols_target
    }

    return {
        "total_cases": total,
        "cases_modified": cases_modified,
        "total_ms": round(total_ms, 1),
        "ms_per_case": round(total_ms / max(total, 1), 2),
        "coverage": coverage,
        "first_20_modified": results[:20],
    }


@router.get("/enrich/targets")
def cognitive_enrich_targets():
    """Lista los targets disponibles para enriquecimiento semántico."""
    return {
        name: {
            "column": t.column,
            "description": t.description,
            "enum_values": t.enum_values,
            "only_if_field": t.only_if_field,
            "only_if_value": t.only_if_value,
        }
        for name, t in ENRICH_TARGETS.items()
    }


@router.post("/chat", response_model=ChatResponse)
def cognitive_chat(req: ChatRequest):
    """Chat single-turn con el agente jurídico.

    Estrategia híbrida v8.2:
      1. Intentar Tier 1 (templates determinísticos en /api/chat) — instantáneo
      2. Si Tier 1 no matchea (intent=unknown) → usar LLM Qwen
      3. Si LLM falla → devolver guía Tier 1
    """
    import time
    from backend.routers.chat import INTENTS as TIER1_INTENTS, ChatResponse as Tier1Resp
    from backend.database.database import SessionLocal

    t0 = time.time()
    msg = req.message or ""

    # v8.2: las preguntas conceptuales/abiertas saltan Tier 1 directo a LLM.
    # Tier 1 es para "cuántos X" / "casos en Y", no para "explica/recomenda/diferencia".
    CONCEPTUAL_RX = re.compile(
        r"(?:explica|expl[ií]ca|c[oó]mo\s+(?:debo|deber[ií]a|puedo|hago|funciona|prevenir|evitar|priorizar|asignar|redistribuir)|"
        r"qu[eé]\s+(?:opinas|piensas|recomiend|hacer|sugieres|consejo|patr[oó]n|protocolo|estrategia)|"
        r"recomi[eé]nd|recomenda|sug[ie]r|"
        r"diferencia|raz[oó]n|por\s+qu[eé]|por que|"
        r"plan\b|protocolo|estrategia|deber[ií]amos|hay que|recomiendo|recomendable|"
        r"si\s+un|si\s+una|qu[eé]\s+pasa\s+si|qu[eé]\s+consecuencia|"
        r"hola|buenos\s+d[ií]as|saludos|dame\s+un|aydame|ay[uú]dame|"
        r"para\s+evitar|prevenir|para\s+que\s+no)",
        re.IGNORECASE,
    )
    is_conceptual = bool(CONCEPTUAL_RX.search(msg))

    # === TIER 1: matching determinístico (rápido, no requiere LLM) ===
    if not is_conceptual:
        db = SessionLocal()
        try:
            for intent_def in TIER1_INTENTS:
                for pattern in intent_def["patterns"]:
                    if pattern.search(msg):
                        try:
                            t1_resp: Tier1Resp = intent_def["fn"](db, msg)
                            if t1_resp.intent != "unknown" and t1_resp.confidence >= 0.6:
                                elapsed = int((time.time() - t0) * 1000)
                                return ChatResponse(
                                    answer=t1_resp.answer,
                                    tools_used=[],
                                    total_ms=elapsed,
                                    qwen_tokens_in=0, qwen_tokens_out=0,
                                )
                        except Exception as e:
                            logger.warning("Tier 1 intent %s falló: %s", intent_def["name"], e)
                        break
        finally:
            db.close()

    # === TIER 2: LLM Qwen (orchestrator con tools) ===
    try:
        ctx = req.context.model_dump() if req.context else None
        turn: ChatTurn = run_chat(req.message, history=req.history, context=ctx)
        return ChatResponse(
            answer=turn.answer,
            tools_used=[ToolTraceOut(name=t.name, args=t.args,
                result_summary=t.result_summary, duration_ms=t.duration_ms)
                for t in turn.tools_used],
            total_ms=turn.total_ms,
            qwen_tokens_in=turn.qwen_tokens_in,
            qwen_tokens_out=turn.qwen_tokens_out,
        )
    except Exception as e:
        logger.warning("LLM cognitive falló (%s), retornando guía Tier 1", str(e)[:80])
        guide = (
            "🤖 El asistente IA local no está disponible en este momento.\n\n"
            "Mientras tanto, puedes usar estas preguntas (yo respondo al instante):\n\n"
            "📊 *Estadísticas:* `cuántos casos hay`, `resumen general`\n"
            "🚨 *Alertas:* `cuántos casos rojos`, `casos en sanción`, `incidentes activos`, `plazos por vencer`\n"
            "👥 *Por abogado:* `casos por abogado`, `qué tiene Victor / Angelica / Otilia / Juan Diego`\n"
            "🏢 *Por dependencia:* `casos de talento humano`, `casos de financiera`\n"
            "⚖️ *Fallos:* `cuántos fallos concede`, `distribución de fallos`\n"
            "🏷️ *Temas:* `top temas`\n"
            "📅 *Tendencia:* `tendencia mensual`\n"
            "🔍 *Caso:* `caso 142`\n\n"
            "Escribe `ayuda` para ver todas las opciones."
        )
        return ChatResponse(answer=guide, tools_used=[], total_ms=int((time.time() - t0) * 1000),
                            qwen_tokens_in=0, qwen_tokens_out=0)
