"""Resolver canónico de abogados de tutelas SED Santander.

Toma cualquier variante (typo, abreviación, mezcla con rol) y devuelve el
nombre oficial de los 17 abogados de tutelas. Si no hay match suficiente,
devuelve None — el firmante es operativo (rector, contratista externo, etc.).
"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Optional

_DATA_DIR = Path(__file__).parent
_CANON_PATH = _DATA_DIR / "abogados_canonicos.json"

# Stop words que no cuentan para matching estructural
_STOPWORDS = {
    "DE", "DEL", "LA", "EL", "LOS", "LAS", "Y", "O",
    "CPS", "COORDINADOR", "COORDINADORA", "ABOGADO", "ABOGADA",
    "CONTRATISTA", "EXTERNA", "EXTERNO", "GRUPO", "APOYO", "JURIDICO",
    "JURÍDICO", "ELABORÓ", "ELABORO", "REVISÓ", "REVISO", "APROBÓ", "APROBO",
    "FIRMÓ", "FIRMO", "VER", "OBSERVACIONES",
}


def _norm(s: str) -> str:
    if not s:
        return ""
    s = str(s).strip().upper()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _significant_tokens(s: str) -> set[str]:
    return {t for t in _norm(s).split() if len(t) > 2 and t not in _STOPWORDS}


@lru_cache(maxsize=1)
def _load_catalog() -> list[dict]:
    with _CANON_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _index() -> dict:
    """Construye índice de matching:
    - exact_norm: normalizado exacto → canonical
    - alias_norm: alias normalizado → canonical
    - tokens: lista de (canonical, set_de_tokens_significativos_apellido_nombre)
    """
    cat = _load_catalog()
    exact = {}
    alias_norm = {}
    tokens = []
    for entry in cat:
        canon = entry["canonical"]
        n = _norm(canon)
        exact[n] = canon
        for a in entry.get("aliases", []):
            alias_norm[_norm(a)] = canon
        # Token set incluye nombres y apellidos significativos
        tokens.append((canon, _significant_tokens(canon)))
    return {"exact": exact, "alias": alias_norm, "tokens": tokens}


@lru_cache(maxsize=2048)
def normalize_abogado(input_str: Optional[str]) -> Optional[str]:
    """Devuelve el nombre canónico oficial del abogado, o None si no hay match.

    Algoritmo en 3 pasos:
      1. Match exacto contra nombre canonical (después de normalizar acentos)
      2. Match contra alias declarado
      3. Match estructural: ≥2 tokens significativos en común con un canonical,
         y al menos 1 apellido del canonical presente en input.

    Devuelve None cuando el input no parece ser un abogado oficial (ej. firmante
    operativo de área, contratista externo, rector, secretario).
    """
    if not input_str or not input_str.strip():
        return None
    n = _norm(input_str)
    if not n:
        return None
    idx = _index()

    if n in idx["exact"]:
        return idx["exact"][n]
    if n in idx["alias"]:
        return idx["alias"][n]

    in_tokens = _significant_tokens(input_str)
    if len(in_tokens) < 2:
        return None

    best_canon = None
    best_overlap = 0
    for canon, canon_tokens in idx["tokens"]:
        overlap = in_tokens & canon_tokens
        if len(overlap) >= 2 and len(overlap) > best_overlap:
            best_canon = canon
            best_overlap = len(overlap)

    return best_canon


def resolve_with_metadata(input_str: Optional[str]) -> dict:
    """Igual que normalize_abogado pero devuelve metadata: confianza y método."""
    if not input_str:
        return {"canonical": None, "method": "empty", "confidence": 0.0}
    n = _norm(input_str)
    idx = _index()

    if n in idx["exact"]:
        return {"canonical": idx["exact"][n], "method": "exact", "confidence": 1.0}
    if n in idx["alias"]:
        return {"canonical": idx["alias"][n], "method": "alias", "confidence": 0.95}

    in_tokens = _significant_tokens(input_str)
    if len(in_tokens) < 2:
        return {"canonical": None, "method": "insufficient_tokens", "confidence": 0.0}

    best_canon = None
    best_overlap = 0
    for canon, canon_tokens in idx["tokens"]:
        overlap = in_tokens & canon_tokens
        if len(overlap) >= 2 and len(overlap) > best_overlap:
            best_canon = canon
            best_overlap = len(overlap)

    if best_canon:
        # Confidence proporcional al overlap (2 tokens = 0.7, 3 = 0.85, 4+ = 0.92)
        conf = min(0.92, 0.5 + 0.15 * best_overlap)
        return {"canonical": best_canon, "method": "structural", "confidence": conf,
                "overlap": best_overlap}

    return {"canonical": None, "method": "no_match", "confidence": 0.0}


def all_canonical_names() -> list[str]:
    """Retorna los 17 nombres canónicos."""
    return [e["canonical"] for e in _load_catalog()]


def short_to_canonical(short: str) -> Optional[str]:
    """Resuelve solo nombre corto (lo que usa el Excel: VICTOR, ANGELICA, etc)."""
    n = _norm(short)
    for entry in _load_catalog():
        if _norm(entry.get("short", "")) == n:
            return entry["canonical"]
        if n in [_norm(a) for a in entry.get("aliases", [])]:
            return entry["canonical"]
    return None
