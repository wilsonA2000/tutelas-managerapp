"""Index alternativo TF-IDF para search_similar_cases sin GPU/BGE-M3.

Ligero (<5MB), rápido (<1s para indexar 217 cases), funciona en CPU sin
sentence-transformers ni descargas. Suficiente para encontrar cases con
texto similar (accionante, asunto, pretensiones, derecho).

API compatible con la tool original: misma forma de búsqueda por case_id
o texto libre, devuelve top-k vecinos con similitud cosine.
"""
from __future__ import annotations

import logging
import os
import pickle
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Optional

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger("tutelas.tfidf_index")

_REPO_ROOT = Path(__file__).resolve().parents[3]
STORE_DIR = _REPO_ROOT / "backend" / "ml" / "embeddings" / "store"
INDEX_PATH = STORE_DIR / "tfidf_index.pkl"
DB_PATH = os.environ.get(
    "TUTELAS_DB",
    str(_REPO_ROOT / "data" / "tutelas.db"),
)


def _norm(s: str) -> str:
    if not s:
        return ""
    s = str(s).strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^\w\s]", " ", s)


def _build_text_current(row: dict) -> str:
    parts = [
        row.get("accionante", ""),
        row.get("derecho_vulnerado", ""),
        row.get("asunto", ""),
        row.get("pretensiones", ""),
        row.get("accionados", ""),
        row.get("categoria_tematica", ""),
        row.get("oficina_responsable", ""),
        row.get("dependencia_canonical", ""),
    ]
    return _norm(" | ".join(p for p in parts if p))[:5000]


def _build_text_historical(row: dict) -> str:
    parts = [
        row.get("tema_raw", ""),
        row.get("observaciones", ""),
        row.get("observaciones_henser", ""),
        row.get("accionante", ""),
    ]
    return _norm(" | ".join(p for p in parts if p))[:5000]


def build(force: bool = False) -> dict:
    """Construye el índice TF-IDF y lo persiste."""
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    if INDEX_PATH.exists() and not force:
        logger.info("Index ya existe en %s (use force=True para reconstruir)", INDEX_PATH)
        return {"status": "exists", "path": str(INDEX_PATH)}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Cases actuales
    current_rows = list(conn.execute(
        """SELECT id, accionante, derecho_vulnerado, asunto, pretensiones,
                  accionados, categoria_tematica, oficina_responsable, dependencia_canonical,
                  folder_name, abogado_canonical, sentido_fallo_1st
           FROM cases WHERE processing_status='COMPLETO'"""
    ).fetchall())

    # Históricos (si existe la tabla)
    historical_rows = []
    try:
        historical_rows = list(conn.execute(
            "SELECT id, tema_raw, observaciones, observaciones_henser, accionante FROM historical_cases"
        ).fetchall())
    except sqlite3.OperationalError:
        logger.info("Tabla historical_cases no existe, indexando solo cases actuales")
    conn.close()

    docs = []
    meta = []
    for r in current_rows:
        d = dict(r)
        text = _build_text_current(d)
        if not text or len(text) < 10:
            continue
        docs.append(text)
        meta.append({"source": "current", "case_id": d["id"], "folder": d.get("folder_name"),
                     "abogado": d.get("abogado_canonical"),
                     "sentido_fallo": d.get("sentido_fallo_1st")})
    for r in historical_rows:
        d = dict(r)
        text = _build_text_historical(d)
        if not text or len(text) < 10:
            continue
        docs.append(text)
        meta.append({"source": "historical", "case_id": d["id"]})

    logger.info("Indexando %d documentos (current=%d, historical=%d)",
                len(docs), len(current_rows), len(historical_rows))

    vectorizer = TfidfVectorizer(
        max_features=20000, ngram_range=(1, 2), min_df=1, max_df=0.95,
        sublinear_tf=True,
    )
    matrix = vectorizer.fit_transform(docs).astype(np.float32)

    payload = {"vectorizer": vectorizer, "matrix": matrix, "meta": meta,
               "n_docs": len(docs), "version": "v1"}
    with INDEX_PATH.open("wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    size_mb = INDEX_PATH.stat().st_size / 1e6
    logger.info("✓ TF-IDF index persistido: %s (%.2f MB, %d docs, %d features)",
                INDEX_PATH, size_mb, len(docs), len(vectorizer.vocabulary_))
    return {"status": "built", "path": str(INDEX_PATH), "size_mb": round(size_mb, 2),
            "docs": len(docs), "features": len(vectorizer.vocabulary_)}


_index_cache = None


def _load() -> Optional[dict]:
    global _index_cache
    if _index_cache is not None:
        return _index_cache
    if not INDEX_PATH.exists():
        return None
    with INDEX_PATH.open("rb") as f:
        _index_cache = pickle.load(f)
    return _index_cache


def search_by_text(query: str, k: int = 5, source: Optional[str] = None) -> list[dict]:
    """Busca top-k vecinos por texto libre. source: 'current' | 'historical' | None (todos)."""
    idx = _load()
    if not idx:
        return []
    qvec = idx["vectorizer"].transform([_norm(query)]).astype(np.float32)
    sims = cosine_similarity(qvec, idx["matrix"])[0]
    order = np.argsort(-sims)
    hits = []
    for pos in order:
        m = idx["meta"][int(pos)]
        if source and m["source"] != source:
            continue
        hits.append({**m, "similarity": float(sims[pos])})
        if len(hits) >= k:
            break
    return hits


def search_by_case_id(case_id: int, k: int = 5, source: Optional[str] = None) -> list[dict]:
    """Busca vecinos de un case_id específico."""
    idx = _load()
    if not idx:
        return []
    target_pos = None
    for i, m in enumerate(idx["meta"]):
        if m["source"] == "current" and m["case_id"] == case_id:
            target_pos = i
            break
    if target_pos is None:
        return []
    qvec = idx["matrix"][target_pos]
    sims = cosine_similarity(qvec, idx["matrix"])[0]
    sims[target_pos] = -1  # excluir el case mismo
    order = np.argsort(-sims)
    hits = []
    for pos in order:
        m = idx["meta"][int(pos)]
        if source and m["source"] != source:
            continue
        hits.append({**m, "similarity": float(sims[pos])})
        if len(hits) >= k:
            break
    return hits


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--rebuild", action="store_true")
    p.add_argument("--query", type=str, default=None, help="texto de prueba")
    args = p.parse_args()
    result = build(force=args.rebuild)
    print(result)
    if args.query:
        hits = search_by_text(args.query, k=5)
        print(f"\nTop 5 para '{args.query}':")
        for h in hits:
            print(f"  sim={h['similarity']:.3f} {h.get('source'):10s} #{h.get('case_id')} {h.get('folder', '-')[:60] if h.get('folder') else '-'}")
