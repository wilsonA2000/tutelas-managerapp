#!/usr/bin/env python3
"""Harness OCR paralelo (PaddleOCR CPU) — test sobre muestra de DESCONOCIDO.

DRY-RUN: NO escribe a la DB. Mide throughput, calidad del texto y qué extrae el
regex. Paralelismo a nivel de proceso (workers persistentes que cargan PaddleOCR
una vez); hilos intra-worker acotados para no sobre-suscribir los 12 cores.

Uso:
  venv/bin/python scripts/ocr_parallel_test.py --workers 6 --threads 2 --limit 20
"""
from __future__ import annotations
import os
import sys
import time
import argparse

# IMPORTANTE: acotar hilos ANTES de importar paddle/numpy en los workers.
# Con spawn, el hijo re-ejecuta este top-level → hereda estos límites.
_THREADS = os.environ.get("OCR_WORKER_THREADS", "2")
os.environ.setdefault("OMP_NUM_THREADS", _THREADS)
os.environ.setdefault("OPENBLAS_NUM_THREADS", _THREADS)
os.environ.setdefault("MKL_NUM_THREADS", _THREADS)
os.environ.setdefault("FLAGS_use_mkldnn", "1")

import sqlite3
from concurrent.futures import ProcessPoolExecutor, as_completed

DB = os.path.join(os.path.dirname(__file__), "..", "data", "tutelas.db")
DPI = int(os.environ.get("OCR_DPI", "200"))

_OCR = None  # PaddleOCR por-worker (global, cargado en el initializer)


def _init_worker():
    global _OCR
    os.environ.setdefault("OMP_NUM_THREADS", _THREADS)
    from paddleocr import PaddleOCR
    try:
        _OCR = PaddleOCR(lang="es", use_angle_cls=False, show_log=False)
    except TypeError:
        # PaddleOCR 3.x cambió la firma (sin show_log/use_angle_cls)
        _OCR = PaddleOCR(lang="es")


def _texts_from_result(res) -> str:
    """Extrae texto tolerando formato viejo [[box,(txt,conf)],...] y 3.x (dict/obj)."""
    out = []
    if not res:
        return ""
    for page in res:
        if page is None:
            continue
        # 3.x: dict con 'rec_texts'
        if isinstance(page, dict) and "rec_texts" in page:
            out.extend(page["rec_texts"])
            continue
        # 3.x: objeto con atributo
        rec = getattr(page, "rec_texts", None)
        if rec:
            out.extend(rec)
            continue
        # viejo: lista de líneas [box, (txt, conf)]
        try:
            for ln in page:
                if ln and len(ln) >= 2 and ln[1]:
                    out.append(ln[1][0])
        except TypeError:
            pass
    return " ".join(t for t in out if t)


def _ocr_page(args) -> dict:
    """OCR de UNA página (granularidad fina → balanceo perfecto entre workers).
    Reabrir el PDF por página cuesta ~ms; vale la pena para no dejar workers
    ociosos detrás de un bundle de 90 páginas."""
    doc_id, path, page_idx = args
    import fitz
    import numpy as np
    t0 = time.time()
    try:
        doc = fitz.open(path)
        page = doc[page_idx]
        pix = page.get_pixmap(dpi=DPI)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            img = img[:, :, :3]
        try:
            res = _OCR.ocr(img)
        except Exception:
            res = _OCR.predict(img)
        doc.close()
        return {"doc_id": doc_id, "page": page_idx, "text": _texts_from_result(res),
                "secs": time.time() - t0, "err": None}
    except Exception as e:
        return {"doc_id": doc_id, "page": page_idx, "text": "",
                "secs": time.time() - t0, "err": str(e)[:160]}


def _run_regex(text: str) -> dict:
    """Qué saca el regex_library sobre el texto OCR (radicados, FOREST, CC, tipo)."""
    from backend.agent import regex_library as RL

    def find(pat_name):
        p = getattr(RL, pat_name, None)
        if p is None:
            return []
        rx = getattr(p, "pattern", p)
        return list(dict.fromkeys(m if isinstance(m, str) else m[0]
                                  for m in rx.findall(text)))[:3]

    hits = {
        "rad23": find("RAD_23_WITH_SEPARATORS") + find("RAD_23_CONTINUOUS"),
        "rad_corto": find("RAD_LABEL") + find("RAD_GENERIC"),
        "forest": find("FOREST_SPECIFIC") + find("FOREST_KEYWORD"),
        "cc": find("CC_ACCIONANTE"),
        "accionante": find("ACCIONANTE_EXPLICIT") + find("ACCIONANTE_DEMANDANTE"),
    }
    # tipo de doc por keywords sobre el texto (no por filename)
    guess = []
    for label, pat in (("AUTO_ADMISORIO", RL.DOC_AUTO_ADMISORIO), ("SENTENCIA", RL.DOC_SENTENCIA),
                       ("IMPUGNACION", RL.DOC_IMPUGNACION), ("INCIDENTE", RL.DOC_INCIDENTE)):
        if pat.search(text[:3000]):
            guess.append(label)
    hits["doc_type_guess"] = guess or ["?"]
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()
    os.environ["OCR_WORKER_THREADS"] = str(args.threads)

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """select id, file_path, filename, page_count from documents
           where doc_type='DESCONOCIDO' and length(trim(coalesce(extracted_text,'')))=0
           and lower(file_path) like '%.pdf'
           order by id limit ?""", (args.limit,)
    ).fetchall()
    names = {r["id"]: r["filename"] for r in rows}
    import fitz
    # Expandir a jobs por-página
    jobs = []
    npages_by_doc = {}
    for r in rows:
        p = r["file_path"]
        if not p or not os.path.exists(p):
            continue
        try:
            d = fitz.open(p); n = d.page_count; d.close()
        except Exception:
            continue
        npages_by_doc[r["id"]] = n
        for i in range(n):
            jobs.append((r["id"], p, i))
    total_pages = len(jobs)
    print(f"Muestra: {len(npages_by_doc)} docs · {total_pages} pags · "
          f"{args.workers} workers × {args.threads} hilos · DPI {DPI} · granularidad PÁGINA")

    page_results = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers, initializer=_init_worker) as ex:
        futs = [ex.submit(_ocr_page, j) for j in jobs]
        for f in as_completed(futs):
            page_results.append(f.result())
    wall = time.time() - t0

    # Reensamblar por doc (ordenar por page_idx)
    from collections import defaultdict
    pages_by_doc = defaultdict(list)
    for pr in page_results:
        pages_by_doc[pr["doc_id"]].append(pr)
    docs = {}
    for did, prs in pages_by_doc.items():
        prs.sort(key=lambda x: x["page"])
        text = "\n".join(p["text"] for p in prs)
        docs[did] = {"npages": len(prs), "chars": len(text), "text": text,
                     "secs": sum(p["secs"] for p in prs),
                     "err": next((p["err"] for p in prs if p["err"]), None)}
    ok_pages = sum(1 for pr in page_results if not pr["err"])
    print(f"\n=== WALL: {wall:.1f}s · {ok_pages}/{total_pages} pags OCR · "
          f"{ok_pages/wall:.2f} pags/s · {wall/max(len(docs),1):.1f}s/doc efectivo ===")

    print("\n=== texto + regex por doc ===")
    for did in sorted(docs):
        d = docs[did]
        nm = names.get(did, "?")[:42]
        hits = _run_regex(d["text"])
        rad = hits.get("rad23") or []
        forest = hits.get("forest") or []
        dtype = hits.get("doc_type_guess")
        print(f"  doc {did:5} {nm:44} {d['npages']:2}p {d['chars']:6}c "
              f"| rad={rad} forest={forest} -> {dtype}")

    con.close()


if __name__ == "__main__":
    main()
