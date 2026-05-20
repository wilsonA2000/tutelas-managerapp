"""Retrieval ANCLADO por contenido para la llamada LLM (gap_fill).

Heurística jurídica determinista (validada contra el corpus, 2026-05-20): en vez de
confiar en `doc_type` (que a veces miente) o en cuotas de página fijas (que fallan
cuando la sección está en una página inesperada), BUSCA el marcador lingüístico de
la sección por CONTENIDO en cada página y envía esa página ± unas pocas (ventana).

  - sección "demanda" (asunto/pretensiones/hechos/derecho): ancla PRETENSIONES/
    HECHOS/SÚPLICA/"ruego a su despacho"/"agente oficioso" → primera ocurrencia.
  - sección "resuelve" (sentido/incidente/desistimiento): ancla "en mérito de lo
    expuesto"/"administrando justicia"/RESUELVE/FALLA/"acepta el desistimiento"
    → ÚLTIMA ocurrencia (la dispositiva va al final; evita falsos positivos a media
    frase como "la providencia que resuelve...").

`doc_type` se usa solo como PRIOR de orden (escanear primero los docs probables),
pero NO como filtro: si están mal clasificados, igual se encuentra por contenido.
"""
from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

from backend.database.models import Document

logger = logging.getLogger("tutelas.v9.field_ctx")

# Marcadores de sección (refinados con el corpus). 'which': first|last; ventana = before/after páginas.
SECTIONS = {
    "demanda": {
        "rx": re.compile(
            r"^\s*(?:[ivx0-9]+[.\-)]\s*)?(?:pretensi[oó]n(?:es)?|petici[oó]n(?:es)?|hechos|s[úu]plica)\b"
            r"|\b(?:ruego\s+a\s+su\s+despacho|se\s+sirva\s+(?:tutelar|amparar|ordenar|conceder)"
            r"|por\s+lo\s+(?:anterior|expuesto)[,\s]+solicit\w+|con\s+base\s+en\s+los\s+(?:siguientes\s+)?hechos"
            r"|actuando\s+(?:como|en\s+calidad)|en\s+(?:mi|su)\s+calidad\s+de|agente\s+oficios\w*)",
            re.I | re.M),
        "which": "first", "before": 1, "after": 3,
    },
    "resuelve": {
        "rx": re.compile(
            r"en\s+m[ée]rito\s+de\s+lo\s+expuesto|administrando\s+justicia\s+en\s+nombre"
            r"|^\s*r\s*e\s*s\s*u\s*e\s*l\s*v\s*e\b|^\s*falla\s*:?\s*$"
            r"|acepta\w*\s+(?:el\s+)?desistimiento|tener\s+por\s+desistid\w*",
            re.I | re.M),
        "which": "last", "before": 2, "after": 3,
    },
}

FIELD_SECTION = {
    "asunto": "demanda", "pretensiones": "demanda", "derecho_vulnerado": "demanda",
    "accionados": "demanda", "vinculados": "demanda",
    "decision_incidente": "resuelve", "decision_incidente_2": "resuelve", "decision_incidente_3": "resuelve",
    "responsable_desacato": "resuelve", "responsable_desacato_2": "resuelve", "responsable_desacato_3": "resuelve",
    "quien_impugno": "resuelve",
}

# Prior de orden (NO filtro): escanear primero los docs probables de cada sección.
DOC_PRIOR = {
    "demanda": ["DEMANDA_TUTELA", "ANEXO_DEMANDA", "AUTO_ADMISORIO"],
    "resuelve": ["SENTENCIA_2DA", "SENTENCIA_1RA", "AUTO_INCIDENTE", "INCIDENTE_DESACATO", "AUTO_ADMISORIO"],
}


def _pages(file_path: str) -> list[str]:
    import pymupdf
    try:
        d = pymupdf.open(file_path)
        out = [d[i].get_text() or "" for i in range(d.page_count)]
        d.close()
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("field_context: no se pudo leer %s: %s", file_path, str(e)[:100])
        return []


def _window(pages: list[str], section: str):
    """Devuelve (lo, hi) índices de página de la ventana alrededor del ancla, o None."""
    spec = SECTIONS[section]
    matches = [i for i, t in enumerate(pages) if spec["rx"].search(t)]
    if not matches:
        return None
    p = matches[0] if spec["which"] == "first" else matches[-1]
    lo = max(0, p - spec["before"])
    hi = min(len(pages), p + spec["after"] + 1)
    return lo, hi


def build_field_context(db: Session, case, missing: list[str], budget: int = 5000) -> str:
    """Arma el texto LLM con SOLO la(s) ventana(s) ancladas a las secciones que
    necesitan los campos faltantes. "" si no encuentra nada (caller no llama al LLM)."""
    if not missing:
        return ""
    sections = []
    for f in missing:
        s = FIELD_SECTION.get(f)
        if s and s not in sections:
            sections.append(s)
    if not sections:
        return ""

    docs = [d for d in db.query(Document).filter(Document.case_id == case.id).all()
            if d.file_path and d.file_path.lower().endswith(".pdf")]
    if not docs:
        return ""

    cache: dict[str, list[str]] = {}
    blocks: list[str] = []
    used = 0
    seen_windows: set[tuple[str, int, int]] = set()

    for section in sections:
        prior = DOC_PRIOR.get(section, [])
        cands = sorted(docs, key=lambda d: prior.index((d.doc_type or "").upper())
                       if (d.doc_type or "").upper() in prior else 99)
        for d in cands:
            pages = cache.get(d.file_path)
            if pages is None:
                pages = _pages(d.file_path)
                cache[d.file_path] = pages
            if not pages:
                continue
            win = _window(pages, section)
            if not win:
                continue
            key = (d.file_path, win[0], win[1])
            if key in seen_windows:
                break
            seen_windows.add(key)
            seg = "\n".join(pages[win[0]:win[1]])
            block = f"=== {d.filename or ''} (pp {win[0]+1}-{win[1]}) ===\n{seg}"
            if used + len(block) > budget:
                block = block[: max(0, budget - used)]
            if block:
                blocks.append(block)
                used += len(block)
            break  # un doc por sección
        if used >= budget:
            break

    return "\n\n".join(blocks)[:budget]
