#!/usr/bin/env python3
"""Construye un corpus aleatorio de 1000 docs para validación de v9.

Sample estratificado proporcional al inventario real (4122 docs):
    AUTO_ADMISORIO   200 (de 500)
    SENTENCIA        250 (de 774)
    RESPUESTA        150 (de 573)
    DEMANDA_TUTELA   150 (de 470)
    INCIDENTE        100 (de 231)
    IMPUGNACION       80 (de 172)
    EMAIL             50 (de 201)
    NOTIFICACION      20 (de 33)

Salida: /tmp/v9_corpus_1000.json
    [{case_id, filename, file_path, doc_type_db, ground_truth_rad23, text, pages, ms_extract}]

Uso:
    python3 scripts/build_corpus_1000.py
"""
from __future__ import annotations

import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal  # noqa: E402
from backend.database.models import Document, Case  # noqa: E402

random.seed(42)

PLAN = {
    'AUTO_ADMISORIO':   (['avoca', 'admis', 'admite'], 200),
    'SENTENCIA':        (['sentencia', 'fallo'], 250),
    'RESPUESTA':        (['respuesta', 'contesta', 'forest'], 150),
    'DEMANDA_TUTELA':   (['demanda', 'escritotutela', 'escrito_tutela', 'tutela'], 150),
    'INCIDENTE':        (['incidente', 'desacato'], 100),
    'IMPUGNACION':      (['impugna'], 80),
    'EMAIL':            (['email'], 50),
    'NOTIFICACION':     (['notif'], 20),
}


def select_random_docs():
    """Selecciona docs aleatoriamente respetando los conteos del PLAN.

    Para asegurar diversidad de casos, prioriza un doc por caso por tipo
    cuando es posible.
    """
    db = SessionLocal()
    try:
        selected = []
        seen_ids = set()

        for tipo, (kws, target) in PLAN.items():
            # Buscar todos los candidatos por keyword
            candidates = []
            for kw in kws:
                q = db.query(Document).filter(Document.filename.ilike(f'%{kw}%'))
                for d in q.all():
                    if d.id in seen_ids:
                        continue
                    p = Path(d.file_path) if d.file_path else None
                    if not p or not p.exists():
                        continue
                    if p.suffix.lower() not in ('.pdf', '.docx', '.doc', '.md'):
                        continue
                    candidates.append(d)

            # Dedup por id
            uniq = {d.id: d for d in candidates}
            candidates = list(uniq.values())

            # Si exceso, sampling aleatorio
            if len(candidates) > target:
                candidates = random.sample(candidates, target)
            elif len(candidates) < target:
                print(f"  ⚠ {tipo}: solo {len(candidates)} disponibles (pedidos {target})")

            for d in candidates:
                seen_ids.add(d.id)
                selected.append((tipo, d))

        return selected
    finally:
        db.close()


def extract_text(file_path: str) -> tuple[str, int, int]:
    """Devuelve (text, pages, ms)."""
    t0 = time.perf_counter()
    p = Path(file_path)
    ext = p.suffix.lower()
    text = ''
    pages = 0
    try:
        if ext == '.pdf':
            import pymupdf
            doc = pymupdf.open(str(p))
            pages = doc.page_count
            text = ''.join(doc[i].get_text() for i in range(pages))
            doc.close()
        elif ext == '.docx':
            from backend.extraction.docx_extractor import extract_docx
            r = extract_docx(str(p))
            text = getattr(r, 'text', '') if not isinstance(r, tuple) else r[0]
            pages = 1
        elif ext == '.doc':
            from backend.extraction.doc_extractor import extract_doc
            r = extract_doc(str(p))
            text = getattr(r, 'text', '') if not isinstance(r, tuple) else r[0]
            pages = 1
        elif ext == '.md':
            text = p.read_text(encoding='utf-8', errors='ignore')
            pages = 1
    except Exception as e:
        print(f"  ⚠ err {p.name[:50]}: {str(e)[:80]}")
    ms = int((time.perf_counter() - t0) * 1000)
    return text, pages, ms


def main():
    print("=== Selección aleatoria (seed=42) ===")
    selected = select_random_docs()
    print(f"\nTotal seleccionados: {len(selected)}\n")

    # Por cada doc, traer el rad23 conocido del case (ground truth)
    db = SessionLocal()
    try:
        case_rad23 = {c.id: c.radicado_23_digitos for c in db.query(Case).all()}
    finally:
        db.close()

    print("=== Extracción de texto ===")
    corpus = []
    by_type = defaultdict(int)
    total_ms = 0
    t_start = time.perf_counter()
    for i, (tipo, d) in enumerate(selected):
        if i % 100 == 0:
            print(f"  {i}/{len(selected)} ({i*100//len(selected)}%)")
        text, pages, ms = extract_text(d.file_path)
        if not text or len(text) < 100:
            continue
        corpus.append({
            'case_id': d.case_id,
            'doc_id': d.id,
            'filename': d.filename,
            'file_path': d.file_path,
            'sample_type': tipo,                  # tipo según PLAN (filename keyword)
            'doc_type_db': d.doc_type or '',      # tipo asignado en la DB actual
            'verificacion_db': d.verificacion or '',
            'pages': pages,
            'extract_ms': ms,
            'gt_rad23': case_rad23.get(d.case_id) or '',
            'text': text[:30000],                 # cap a 30K chars
        })
        by_type[tipo] += 1
        total_ms += ms

    elapsed = time.perf_counter() - t_start
    out = Path('/tmp/v9_corpus_1000.json')
    out.write_text(json.dumps(corpus, ensure_ascii=False))

    print(f"\n=== Resultado ===")
    print(f"Docs OK:        {len(corpus)}")
    print(f"Tamaño json:    {out.stat().st_size / 1024 / 1024:.1f} MB")
    print(f"Tiempo total:   {elapsed:.1f} s")
    print(f"Promedio extract: {total_ms/max(len(corpus),1):.0f} ms/doc")
    print()
    print(f"Distribución por tipo:")
    for t, n in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {t:<18} {n:>4}")


if __name__ == '__main__':
    main()
