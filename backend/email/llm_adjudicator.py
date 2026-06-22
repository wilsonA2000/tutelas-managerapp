"""Adjudicador DeepSeek para los DEAD-ENDS deterministas de la ingesta.

El matcher determinista (matcher.py) resuelve el ~80% con HIGH confianza. Cuando NO está
seguro (rad_corto ambiguo, mismo rad_corto en varios juzgados, MEDIUM, filename genérico),
históricamente punteaba a revisión humana — y ahí nacían las conflaciones que se des-enredaban
a mano. Este módulo mete a DeepSeek SOLO en esos puntos: lee el correo + los casos candidatos
y decide con razón. Auto-resuelve si está seguro (confidence ≥ _AUTO_CONFIDENCE), si no deja
una recomendación razonada para revisión humana.

Principios (Regla #1 "local primero"):
- NO toca lo que el determinista ya resolvió HIGH.
- Gateado: con `V9_DISABLE_LLM` o sin DeepSeek configurado → Verdict("AMBIGUOUS") =
  comportamiento determinista de antes (fallback a revisión humana). Tests deterministas.
- Constraint: la decisión SOLO puede ser un id candidato, "NEW" o "AMBIGUOUS" — nunca texto libre.
- Auditable: el caller persiste {decision, confidence, reason, candidates} en match_signals_json.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional, Union

logger = logging.getLogger("tutelas.adjudicator")

# Umbral de auto-resolución: por encima, el caller aplica la decisión; por debajo, flag humano.
_AUTO_CONFIDENCE = float(os.getenv("ADJUDICATOR_AUTO_CONFIDENCE", "0.85"))

Decision = Union[int, str]  # un case_id, "NEW", o "AMBIGUOUS"


@dataclass
class Verdict:
    decision: Decision           # int (case_id) | "NEW" | "AMBIGUOUS"
    confidence: float            # 0.0 - 1.0
    reason: str                  # explicación legible (para auditoría y UI)
    candidates: list = field(default_factory=list)

    @property
    def is_confident(self) -> bool:
        """¿Aplicar automáticamente? Solo si decidió algo concreto con alta confianza."""
        return self.decision != "AMBIGUOUS" and self.confidence >= _AUTO_CONFIDENCE

    def as_dict(self) -> dict:
        return {
            "decision": self.decision,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "candidates": self.candidates,
        }


def llm_on() -> bool:
    """¿Hay DeepSeek disponible para adjudicar? (gating idéntico al de extracción)."""
    return (
        os.getenv("V9_ALLOW_DEEPSEEK", "false").lower() == "true"
        and bool(os.getenv("V9_LLM_API_KEY", ""))
        and os.getenv("V9_DISABLE_LLM", "false").lower() != "true"
    )


def _abstain(candidates: list, reason: str) -> Verdict:
    return Verdict("AMBIGUOUS", 0.0, reason, candidates)


def _adjudicate(system: str, prompt: str, *, valid: set, candidates: list, max_tokens: int = 220) -> Verdict:
    """Llama a DeepSeek, parsea JSON {decision, confidence, reason} y valida el constraint.

    `valid` = conjunto de decisiones aceptables (ids candidatos como str + "NEW"/"AMBIGUOUS").
    Cualquier desvío (no-JSON, decision fuera de `valid`, basura) → AMBIGUOUS (abstención segura).
    """
    if not llm_on():
        return _abstain(candidates, "LLM off (determinista)")
    try:
        from backend.extraction.ai_extractor import _call_local
    except ImportError as e:  # pragma: no cover
        logger.warning("adjudicador: import falló: %s", e)
        return _abstain(candidates, f"import error: {e}")

    msgs = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    try:
        raw, _, _ = _call_local(msgs, max_tokens=max_tokens)
    except Exception as e:
        logger.warning("adjudicador: DeepSeek falló: %s", str(e)[:200])
        return _abstain(candidates, f"LLM error: {str(e)[:80]}")
    if not raw:
        return _abstain(candidates, "respuesta vacía")

    # El guard es el parseo JSON + el constraint (decision ∈ valid), NO _is_garbage:
    # _is_garbage está calibrado para prosa de campos; un JSON con razón corta tiene mucha
    # puntuación y lo marcaría como basura falsamente.
    data = _parse_json(raw)
    if not data:
        return _abstain(candidates, "respuesta no-JSON")
    decision = data.get("decision")
    reason = str(data.get("reason", ""))[:400]
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    dec_str = str(decision).strip()
    if dec_str not in valid:
        logger.info("adjudicador: decision %r fuera de candidatos %s → AMBIGUOUS", dec_str, sorted(valid))
        return _abstain(candidates, f"decisión inválida ({dec_str!r})")
    # case_ids son numéricos (→ int); doc_types / NEW / AMBIGUOUS quedan como string.
    norm: Decision = int(dec_str) if dec_str.lstrip("-").isdigit() else dec_str
    return Verdict(norm, confidence, reason, candidates)


def _parse_json(raw: str) -> Optional[dict]:
    """Extrae el primer objeto JSON del texto (tolera fences ```json y prosa alrededor)."""
    raw = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


# ─────────────────────────────────────────────────────────────
# 1) Conflación / asignación
# ─────────────────────────────────────────────────────────────

def _case_brief(db, cache, cid: int) -> str:
    """Resumen de un caso candidato para el grounding (1 línea)."""
    from backend.database.models import Case
    c = db.query(Case).filter(Case.id == cid).first()
    if not c:
        return f"- ID {cid}: (no existe)"
    juz = ""
    try:
        juz = cache.juzgado_of(cid) or ""
    except Exception:
        pass
    return (
        f"- ID {cid}: carpeta={(c.folder_name or '')[:50]!r} | "
        f"accionante={(c.accionante or '')[:40]!r} | "
        f"rad23={(c.radicado_23_digitos or '')[:25]} | juzgado={juz or '?'} | "
        f"asunto={(c.asunto or '')[:40]!r}"
    )


# DeepSeek tiene ventana amplia → le damos TODO el contexto del correo (body completo +
# nombres de adjuntos), no un snippet. Cota generosa para acotar costo/latencia.
_ASSIGN_BODY_CAP = int(os.getenv("ADJUDICATOR_BODY_CAP", "12000"))


def adjudicate_assignment(
    db,
    signals,
    candidate_ids: list[int],
    *,
    cache=None,
    email_subject: str = "",
    email_body: str = "",
    attachment_names: Optional[list[str]] = None,
) -> Verdict:
    """Decide a qué caso candidato pertenece un correo ambiguo (o si es NUEVO/ambiguo).

    `signals` = EmailSignals (matcher). `candidate_ids` = casos plausibles que el determinista
    no pudo desempatar. `cache` = CaseLookupCache del caller (o se obtiene uno fresco).
    `email_body` = cuerpo COMPLETO del correo; `attachment_names` = nombres de adjuntos.
    DeepSeek analiza todo eso + el resumen de cada candidato para decidir.
    Devuelve Verdict con decision ∈ candidate_ids ∪ {"NEW","AMBIGUOUS"}.
    """
    cands = [int(c) for c in candidate_ids if c is not None]
    if not cands:
        return _abstain(cands, "sin candidatos")
    if not llm_on():
        return _abstain(cands, "LLM off (determinista)")

    if cache is None:
        from backend.email.case_lookup_cache import get_cache
        cache = get_cache()
    briefs = "\n".join(_case_brief(db, cache, cid) for cid in cands)
    adj_names = ", ".join(attachment_names or []) or "(ninguno)"
    valid = {str(c) for c in cands} | {"NEW", "AMBIGUOUS"}
    system = (
        "Eres un adjudicador jurídico experto en tutelas colombianas. Asignas un correo a su "
        "expediente correcto SIN conflar procesos distintos. Respondes ÚNICAMENTE con un objeto JSON."
    )
    prompt = (
        "Un correo de tutela podría pertenecer a uno de varios expedientes (mismo radicado corto "
        "pero quizá distinto juzgado/accionante = procesos DISTINTOS). Decide a cuál pertenece.\n\n"
        "CORREO:\n"
        f"  asunto: {email_subject[:300]!r}\n"
        f"  accionante detectado: {getattr(signals, 'accionante_name', '')[:50]!r}\n"
        f"  radicado corto: {getattr(signals, 'rad_corto', '')!r}\n"
        f"  radicado 23díg: {getattr(signals, 'rad23', '')!r}\n"
        f"  FOREST: {getattr(signals, 'forest', '')!r}\n"
        f"  remitente: {getattr(signals, 'sender', '')[:80]!r}\n"
        f"  adjuntos: {adj_names[:500]}\n"
        f"  cuerpo:\n{(email_body or '')[:_ASSIGN_BODY_CAP]}\n\n"
        "EXPEDIENTES CANDIDATOS:\n" + briefs + "\n\n"
        "REGLAS:\n"
        "- Si el accionante y el juzgado/rad23 coinciden claramente con UN expediente → ese ID.\n"
        "- Si NINGÚN candidato coincide (accionante y juzgado distintos) → 'NEW' (es otro proceso).\n"
        "- Si no puedes determinarlo con seguridad → 'AMBIGUOUS'.\n"
        'Responde SOLO: {"decision": <ID|"NEW"|"AMBIGUOUS">, "confidence": <0.0-1.0>, "reason": "<breve>"}'
    )
    verdict = _adjudicate(system, prompt, valid=valid, candidates=cands)
    logger.info(
        "adjudicate_assignment: cands=%s → %s (conf=%.2f) %s",
        cands, verdict.decision, verdict.confidence, verdict.reason[:80],
    )
    return verdict


# ─────────────────────────────────────────────────────────────
# 2) Clasificación de documentos por CONTENIDO
# ─────────────────────────────────────────────────────────────

# Vocabulario controlado para clasificar un documento por su contenido cuando el filename
# es genérico/desconocido. DEMANDA_TUTELA aporta lo que el filename casi nunca detecta.
DOC_TYPE_VOCAB = [
    "DEMANDA_TUTELA", "PDF_AUTO_ADMISORIO", "PDF_SENTENCIA", "PDF_IMPUGNACION",
    "PDF_INCIDENTE", "RESPUESTA", "OTRO",
]
_DOC_CONTENT_CAP = int(os.getenv("ADJUDICATOR_DOC_CAP", "6000"))


def classify_doc_by_content(text_head: str, filename: str = "") -> Verdict:
    """Clasifica el tipo de un documento por su contenido (cuando el filename no basta).

    Devuelve Verdict con decision ∈ DOC_TYPE_VOCAB. Gateado/validado/abstención-segura.
    El caller solo aplica el tipo si verdict.is_confident y decision != 'OTRO'.
    """
    text = (text_head or "").strip()
    if not llm_on():
        return _abstain(DOC_TYPE_VOCAB, "LLM off")
    if len(text) < 200:
        return _abstain(DOC_TYPE_VOCAB, "texto insuficiente")
    vocab = ", ".join(DOC_TYPE_VOCAB)
    system = (
        "Clasificas el tipo de un documento de un proceso de tutela colombiano leyendo su "
        "contenido. Respondes ÚNICAMENTE con un objeto JSON."
    )
    prompt = (
        f"Nombre de archivo: {filename[:80]!r}\n"
        f"Clasifica el documento en UNO de estos tipos: {vocab}.\n"
        "- DEMANDA_TUTELA: el escrito del accionante que interpone la tutela.\n"
        "- PDF_AUTO_ADMISORIO: auto que admite/avoca la tutela.\n"
        "- PDF_SENTENCIA: fallo (1ra o 2da instancia, 'administrando justicia').\n"
        "- PDF_IMPUGNACION: escrito que impugna el fallo.\n"
        "- PDF_INCIDENTE: incidente de desacato / sanción.\n"
        "- RESPUESTA: contestación/respuesta de la entidad accionada (SED).\n"
        "- OTRO: si no encaja claramente.\n\n"
        f"CONTENIDO (inicio):\n{text[:_DOC_CONTENT_CAP]}\n\n"
        'Responde SOLO: {"decision": "<TIPO>", "confidence": <0.0-1.0>, "reason": "<breve>"}'
    )
    verdict = _adjudicate(system, prompt, valid=set(DOC_TYPE_VOCAB),
                          candidates=list(DOC_TYPE_VOCAB), max_tokens=120)
    logger.info("classify_doc_by_content: %r → %s (conf=%.2f)", filename[:40], verdict.decision, verdict.confidence)
    return verdict
