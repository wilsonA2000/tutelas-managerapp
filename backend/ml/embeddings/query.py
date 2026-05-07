"""kNN sobre FAISS + consensus voting (fallback de predict_field).

Carga lazy del índice y metadata. Thread-safe para uso multi-usuario.
"""
from __future__ import annotations

import logging
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Optional

import faiss
import numpy as np

from backend.ml.embeddings.encoder import encode_texts

logger = logging.getLogger("tutelas.ml.embeddings.query")

STORE_DIR = Path(__file__).resolve().parent / "store"
INDEX_PATH = STORE_DIR / "index.faiss"
META_PATH = STORE_DIR / "meta.sqlite"

VALID_TARGETS = {"tema", "dependencia", "direccion", "tipo", "fallo"}

_index = None
_meta: Optional[sqlite3.Connection] = None
_lock = Lock()


@dataclass
class Neighbor:
    vector_id: int
    score: float                 # cosine (inner product, vecs L2-norm)
    source: str                  # 'historical' | 'current'
    case_id: int
    tema: Optional[str]
    dependencia: Optional[str]
    direccion: Optional[str]
    tipo: Optional[str]
    fallo: Optional[str]
    text_preview: str


@dataclass
class ConsensusPrediction:
    target: str
    value: str
    confidence: float            # n_voto / n_validos
    n_neighbors: int
    n_valid: int


def _load():
    global _index, _meta
    if _index is not None and _meta is not None:
        return _index, _meta
    with _lock:
        if _index is None:
            if not INDEX_PATH.exists():
                raise FileNotFoundError(
                    f"FAISS index ausente en {INDEX_PATH}. "
                    "Corre: python -m backend.ml.embeddings.index_builder --rebuild"
                )
            _index = faiss.read_index(str(INDEX_PATH))
            logger.info("FAISS cargado: %d vectores, dim=%d",
                        _index.ntotal, _index.d)
        if _meta is None:
            _meta = sqlite3.connect(str(META_PATH), check_same_thread=False)
            _meta.row_factory = sqlite3.Row
        return _index, _meta


def search_similar(
    text: str,
    k: int = 5,
    source_filter: Optional[str] = None,
    exclude_case_id: Optional[int] = None,
) -> list[Neighbor]:
    """Busca k vecinos más similares por cosine.

    Args:
      text: query
      k: cantidad final deseada
      source_filter: 'historical' | 'current' | None
      exclude_case_id: excluye el caso (sólo aplica a source='current')
    """
    if not text or len(text.strip()) < 5:
        return []

    index, meta = _load()
    needs_filter = bool(source_filter) or exclude_case_id is not None
    if needs_filter:
        fetch_k = min(max(k * 50, k + 256), index.ntotal)
    else:
        fetch_k = min(k, index.ntotal)

    qv = encode_texts([text], batch_size=1)
    scores, ids = index.search(qv, fetch_k)
    scores = scores[0]
    ids = ids[0]

    valid_ids = [int(i) for i in ids if int(i) >= 0]
    if not valid_ids:
        return []

    placeholders = ",".join("?" * len(valid_ids))
    rows = {
        r["vector_id"]: r
        for r in meta.execute(
            f"SELECT * FROM vectors WHERE vector_id IN ({placeholders})",
            valid_ids,
        )
    }

    out: list[Neighbor] = []
    for vid, sc in zip(ids, scores):
        if int(vid) < 0:
            continue
        m = rows.get(int(vid))
        if not m:
            continue
        if source_filter and m["source"] != source_filter:
            continue
        if (exclude_case_id is not None and m["source"] == "current"
                and m["case_id"] == exclude_case_id):
            continue
        out.append(Neighbor(
            vector_id=int(vid),
            score=float(sc),
            source=m["source"],
            case_id=int(m["case_id"]),
            tema=m["tema"],
            dependencia=m["dependencia"],
            direccion=m["direccion"],
            tipo=m["tipo"],
            fallo=m["fallo"],
            text_preview=m["text_preview"] or "",
        ))
        if len(out) >= k:
            break
    return out


def knn_consensus(
    text: str,
    target: str,
    k: int = 5,
    min_agreement: float = 0.6,
    source: str = "historical",
) -> Optional[ConsensusPrediction]:
    """Consensus voting sobre k vecinos para el target dado.

    Retorna None si:
      - menos de 3 vecinos con label no-nulo
      - mejor agreement < min_agreement
    """
    if target not in VALID_TARGETS:
        raise ValueError(f"target inválido {target!r}; válidos: {VALID_TARGETS}")

    neigh = search_similar(text, k=k, source_filter=source)
    if not neigh:
        return None

    labels = [getattr(n, target) for n in neigh if getattr(n, target)]
    if len(labels) < 3:
        return None

    counter = Counter(labels)
    best, n_voto = counter.most_common(1)[0]
    agreement = n_voto / len(labels)
    if agreement < min_agreement:
        return None

    return ConsensusPrediction(
        target=target,
        value=str(best),
        confidence=float(agreement),
        n_neighbors=len(neigh),
        n_valid=len(labels),
    )
