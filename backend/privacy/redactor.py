"""Orquestador de redacción (v5.3) — entry point de la capa PII."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Literal

from backend.core.settings import settings
from backend.privacy.detectors import (
    Span, blacklist_detect, merge_spans, presidio_detect, regex_detect,
)
from backend.privacy.policies import Mode, should_redact
from backend.privacy.tokens import TokenCatalog

_logger = logging.getLogger("tutelas.privacy.redactor")


@dataclass
class RedactionContext:
    case_id: int
    mode: Mode = "selective"
    known_entities: dict[str, list[str]] = field(default_factory=dict)  # kind → [values]
    forensic_hits: dict[str, list[str]] = field(default_factory=dict)    # idem, de forensic_analyzer
    # Entidades a preservar literal aunque el detector las encuentre (lista corta: "Secretaría de Educación", "Gobernación de Santander").
    whitelist: set[str] = field(default_factory=set)


@dataclass
class RedactedPayload:
    docs: list[dict]                                   # [{filename, text}]
    mapping: dict[str, dict]                           # token → {value, kind, meta, value_hash}
    stats: dict                                        # spans_detected, tokens_minted, redactor_ms, mode


_DEFAULT_WHITELIST_LOWER = frozenset({
    "gobernación de santander", "gobernacion de santander",
    "secretaría de educación", "secretaria de educacion",
    "secretaría de educación de santander", "secretaria de educacion de santander",
    "santander",
    "corte constitucional",
    "consejo superior de la judicatura",
    "ministerio de educación", "ministerio de educacion",
})


def _in_whitelist(value: str, extra: set[str]) -> bool:
    v = re.sub(r"\s+", " ", value.strip().lower())
    if v in _DEFAULT_WHITELIST_LOWER:
        return True
    for item in extra:
        if v == item.strip().lower():
            return True
    return False


def redact_payload(
    ia_doc_texts: list[dict],
    ctx: RedactionContext,
) -> RedactedPayload:
    """Redacta una lista de documentos según el modo (selective|aggressive).

    Args:
        ia_doc_texts: [{"filename": ..., "text": ...}, ...]
        ctx: RedactionContext con case_id, mode, known_entities, etc.

    Returns:
        RedactedPayload con docs redactados, mapping para rehidratar y stats.
    """
    if not settings.PII_REDACTION_ENABLED:
        return RedactedPayload(docs=ia_doc_texts, mapping={}, stats={"skipped": True})

    t0 = time.time()
    catalog = TokenCatalog(case_id=ctx.case_id)
    extra_whitelist = ctx.whitelist or set()

    # Merge known_entities + forensic_hits en un solo dict de blacklist determinística.
    blacklist: dict[str, list[str]] = {}
    for src in (ctx.known_entities, ctx.forensic_hits):
        for k, vs in src.items():
            blacklist.setdefault(k, []).extend(v for v in vs if v)

    redacted_docs = []
    total_spans = 0
    for doc in ia_doc_texts:
        text = doc.get("text") or ""
        if not text:
            redacted_docs.append(doc)
            continue

        spans = merge_spans(
            blacklist_detect(text, blacklist),
            regex_detect(text),
            presidio_detect(text),
        )
        # Filtrar por modo + whitelist
        spans = [s for s in spans if should_redact(s.kind, ctx.mode) and not _in_whitelist(s.value, extra_whitelist)]

        total_spans += len(spans)
        redacted_text = _apply_spans(text, spans, catalog, ctx)
        redacted_docs.append({**doc, "text": redacted_text})

    elapsed_ms = int((time.time() - t0) * 1000)
    _logger.info(
        "redact case=%s mode=%s spans=%d tokens=%d elapsed_ms=%d",
        ctx.case_id, ctx.mode, total_spans, len(catalog.mapping()), elapsed_ms,
    )

    return RedactedPayload(
        docs=redacted_docs,
        mapping=catalog.mapping(),
        stats={
            "mode": ctx.mode,
            "spans_detected": total_spans,
            "tokens_minted": len(catalog.mapping()),
            "redactor_ms": elapsed_ms,
        },
    )


def _apply_spans(text: str, spans: list[Span], catalog: TokenCatalog, ctx: RedactionContext) -> str:
    """Reemplaza spans de derecha a izquierda para preservar offsets."""
    if not spans:
        return text
    # Ordenar descendente por start para que los índices se mantengan estables tras el replace
    spans_sorted = sorted(spans, key=lambda s: s.start, reverse=True)
    result = text
    for span in spans_sorted:
        metadata = _metadata_for_span(span, ctx)
        token = catalog.mint(span.kind, span.value, metadata)
        result = result[:span.start] + token + result[span.end:]
    return result


def _metadata_for_span(span: Span, ctx: RedactionContext) -> dict:
    """Extrae metadata estructural mínima para el token (sin PII).

    Heurísticas conservadoras: la integración fina caso por caso puede
    enriquecerse desde `unified.py` pasando metadata en el context.
    """
    meta = {}
    if span.kind == "PERSON":
        # Heurística: primer PERSON detectado suele ser el accionante.
        # Las siguientes son accionadas/abogados — el operador puede
        # revisar si el token generado (ACCIONANTE_1 vs PERSONA_2) fue correcto.
        meta["role"] = "ACCIONANTE" if span.start < 500 else "PERSONA"
    return meta


def persist_mapping(db, case_id: int, mapping: dict) -> None:
    """Guarda el mapping en la tabla pii_mappings (idempotente — upsert por token)."""
    from backend.database.models import PiiMapping
    from backend.privacy.crypto import encrypt

    for token, info in mapping.items():
        existing = db.query(PiiMapping).filter_by(case_id=case_id, token=token).first()
        if existing:
            continue
        db.add(PiiMapping(
            case_id=case_id,
            token=token,
            kind=info["kind"],
            value_encrypted=encrypt(info["value"]),
            value_hash=info["value_hash"],
            meta_json=json.dumps(info.get("meta", {})),
        ))
    db.commit()
