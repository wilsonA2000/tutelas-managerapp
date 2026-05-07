"""Construye FAISS plano sobre historical_cases + cases.

Output (persistido en MooseFS, sobrevive reinicios del pod):
    backend/ml/embeddings/store/
        ├── index.faiss   IndexFlatIP + IDMap2, 1024 dim
        └── meta.sqlite   vector_id ↔ case_id, labels, source

Texto indexado:
  - historical: tema_raw + observaciones + observaciones_henser + accionante
  - current:    asunto + pretensiones + accionados + derecho_vulnerado

Uso:
    python -m backend.ml.embeddings.index_builder --rebuild
"""
from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

import faiss
import numpy as np

from backend.ml.embeddings.encoder import encode_texts

logger = logging.getLogger("tutelas.ml.embeddings.index_builder")

STORE_DIR = Path(__file__).resolve().parent / "store"
INDEX_PATH = STORE_DIR / "index.faiss"
META_PATH = STORE_DIR / "meta.sqlite"

DB_PATH = Path(os.environ.get(
    "TUTELAS_DB",
    "/workspace/tutelas-data/tutelas-app/data/tutelas.db",
))

DIM = 1024  # BGE-M3 output dim
MAX_TEXT_CHARS = 4000  # ~1000 tokens, holgado bajo límite 8192


def _build_text_historical(row) -> str:
    parts = [
        row["tema_raw"], row["observaciones"],
        row["observaciones_henser"], row["accionante"],
    ]
    return " | ".join(p for p in parts if p)[:MAX_TEXT_CHARS]


def _build_text_current(row) -> str:
    parts = [
        row["asunto"], row["pretensiones"],
        row["accionados"], row["derecho_vulnerado"],
    ]
    return " | ".join(p for p in parts if p)[:MAX_TEXT_CHARS]


def _init_meta_schema(meta: sqlite3.Connection) -> None:
    meta.executescript("""
    CREATE TABLE IF NOT EXISTS vectors (
      vector_id    INTEGER PRIMARY KEY,
      source       TEXT NOT NULL CHECK(source IN ('historical','current')),
      case_id      INTEGER NOT NULL,
      tema         TEXT,
      dependencia  TEXT,
      direccion    TEXT,
      tipo         TEXT,
      fallo        TEXT,
      text_preview TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_vec_source_case ON vectors(source, case_id);
    CREATE INDEX IF NOT EXISTS idx_vec_tema ON vectors(tema);
    CREATE INDEX IF NOT EXISTS idx_vec_dep  ON vectors(dependencia);
    """)
    meta.commit()


def build(force: bool = False) -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)

    if INDEX_PATH.exists() and not force:
        logger.warning(
            "Index ya existe en %s — usa --rebuild para reconstruir",
            INDEX_PATH,
        )
        return

    if force:
        for p in (INDEX_PATH, META_PATH):
            p.unlink(missing_ok=True)

    src = sqlite3.connect(str(DB_PATH))
    src.row_factory = sqlite3.Row

    rows: list[tuple[str, dict]] = []

    logger.info("Cargando historical_cases…")
    for r in src.execute("""
        SELECT id, tema_raw, observaciones, observaciones_henser, accionante,
               tema_normalized, dependencia_normalized, fallo_class, tipo
        FROM historical_cases
    """):
        text = _build_text_historical(r)
        if not text or len(text) < 20:
            continue
        rows.append((text, {
            "source": "historical",
            "case_id": r["id"],
            "tema": r["tema_normalized"],
            "dependencia": r["dependencia_normalized"],
            "direccion": None,
            "tipo": r["tipo"],
            "fallo": r["fallo_class"],
        }))

    logger.info("Cargando cases…")
    for r in src.execute("""
        SELECT id, asunto, pretensiones, accionados, derecho_vulnerado,
               oficina_responsable, sentido_fallo_1st
        FROM cases
        WHERE COALESCE(asunto,'') <> '' OR COALESCE(pretensiones,'') <> ''
    """):
        text = _build_text_current(r)
        if not text or len(text) < 20:
            continue
        rows.append((text, {
            "source": "current",
            "case_id": r["id"],
            "tema": None,
            "dependencia": r["oficina_responsable"],
            "direccion": None,
            "tipo": "TUTELA",
            "fallo": r["sentido_fallo_1st"],
        }))

    src.close()

    if not rows:
        logger.error("No hay textos para indexar.")
        sys.exit(2)

    n = len(rows)
    logger.info("Total docs a indexar: %d (historical=%d, current=%d)",
                n,
                sum(1 for _, m in rows if m["source"] == "historical"),
                sum(1 for _, m in rows if m["source"] == "current"))

    texts = [t for t, _ in rows]

    t0 = time.time()
    vecs = encode_texts(texts, batch_size=32, show_progress=True)
    dt = time.time() - t0
    logger.info("Encode completo en %.1fs (%.1f docs/s)", dt, n / max(dt, 1e-6))

    if vecs.shape != (n, DIM):
        raise RuntimeError(f"Bad shape {vecs.shape}, esperado ({n},{DIM})")

    logger.info("Construyendo FAISS IndexFlatIP + IDMap2…")
    base = faiss.IndexFlatIP(DIM)
    index = faiss.IndexIDMap2(base)
    ids = np.arange(n, dtype="int64")
    index.add_with_ids(vecs, ids)
    faiss.write_index(index, str(INDEX_PATH))

    logger.info("Persistiendo metadata SQLite…")
    meta = sqlite3.connect(str(META_PATH))
    _init_meta_schema(meta)
    meta.executemany("""
        INSERT OR REPLACE INTO vectors
        (vector_id, source, case_id, tema, dependencia, direccion, tipo,
         fallo, text_preview)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        (int(i), m["source"], int(m["case_id"]), m["tema"], m["dependencia"],
         m["direccion"], m["tipo"], m["fallo"], texts[i][:300])
        for i, (_, m) in enumerate(rows)
    ])
    meta.commit()
    meta.close()

    size_mb = INDEX_PATH.stat().st_size / 1e6
    logger.info("✓ FAISS persistido: %s (%.1f MB)", INDEX_PATH, size_mb)
    logger.info("✓ Metadata SQLite: %s", META_PATH)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    p = argparse.ArgumentParser()
    p.add_argument("--rebuild", action="store_true",
                   help="Reconstruir índice desde cero")
    args = p.parse_args()
    build(force=args.rebuild)


if __name__ == "__main__":
    main()
