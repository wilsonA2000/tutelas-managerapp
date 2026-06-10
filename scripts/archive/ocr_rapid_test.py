#!/usr/bin/env python3
"""Harness OCR paralelo con RapidOCR (backend ONNXRUNTIME u OPENVINO) — mismos
modelos PP-OCR que PaddleOCR pero runtime más liviano. DRY-RUN, no toca DB.
Compara contra el baseline PaddleOCR (134s / 150 págs).

Uso:
  venv/bin/python scripts/ocr_rapid_test.py --engine openvino --workers 4 --threads 3 --limit 20
  venv/bin/python scripts/ocr_rapid_test.py --engine onnxruntime --workers 6 --threads 2 --limit 20
"""
from __future__ import annotations
import os, sys, time, argparse

_THREADS = os.environ.get("OCR_WORKER_THREADS", "2")
for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(v, _THREADS)

import sqlite3
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import defaultdict

DB = os.path.join(os.path.dirname(__file__), "..", "data", "tutelas.db")
DPI = int(os.environ.get("OCR_DPI", "200"))
ENGINE = os.environ.get("OCR_ENGINE", "openvino")

_OCR = None


def _init_worker():
    global _OCR
    os.environ.setdefault("OMP_NUM_THREADS", _THREADS)
    from rapidocr import RapidOCR, EngineType, LangRec
    et = EngineType.OPENVINO if ENGINE == "openvino" else EngineType.ONNXRUNTIME
    params = {
        "Det.engine_type": et, "Rec.engine_type": et, "Cls.engine_type": et,
        "Rec.lang_type": LangRec.LATIN,   # español = script latino
        "Global.use_cls": False,
    }
    if ENGINE == "onnxruntime":
        params["EngineConfig.onnxruntime.intra_op_num_threads"] = int(_THREADS)
    else:
        params["EngineConfig.openvino.inference_num_threads"] = int(_THREADS)
    try:
        _OCR = RapidOCR(params=params)
    except Exception:
        _OCR = RapidOCR()  # fallback config por defecto


def _ocr_page(args) -> dict:
    doc_id, path, page_idx = args
    import fitz, numpy as np
    t0 = time.time()
    try:
        doc = fitz.open(path)
        pix = doc[page_idx].get_pixmap(dpi=DPI)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            img = img[:, :, :3]
        elif pix.n == 1:
            img = np.repeat(img, 3, axis=2)
        doc.close()
        res = _OCR(img)
        txts = getattr(res, "txts", None)
        text = " ".join(t for t in txts if t) if txts else ""
        return {"doc_id": doc_id, "page": page_idx, "text": text, "secs": time.time() - t0, "err": None}
    except Exception as e:
        return {"doc_id": doc_id, "page": page_idx, "text": "", "secs": time.time() - t0, "err": str(e)[:160]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["openvino", "onnxruntime"], default="openvino")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--threads", type=int, default=3)
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()
    global ENGINE
    ENGINE = args.engine
    os.environ["OCR_ENGINE"] = args.engine
    os.environ["OCR_WORKER_THREADS"] = str(args.threads)

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    rows = con.execute(
        """select id, file_path, filename from documents
           where doc_type='DESCONOCIDO' and length(trim(coalesce(extracted_text,'')))=0
           and lower(file_path) like '%.pdf' order by id limit ?""", (args.limit,)
    ).fetchall()
    names = {r["id"]: r["filename"] for r in rows}
    import fitz
    jobs = []
    for r in rows:
        p = r["file_path"]
        if not p or not os.path.exists(p):
            continue
        try:
            d = fitz.open(p); n = d.page_count; d.close()
        except Exception:
            continue
        for i in range(n):
            jobs.append((r["id"], p, i))
    print(f"[{args.engine}] {len(names)} docs · {len(jobs)} pags · "
          f"{args.workers}w × {args.threads}t · DPI {DPI}")

    page_results = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers, initializer=_init_worker) as ex:
        futs = [ex.submit(_ocr_page, j) for j in jobs]
        for f in as_completed(futs):
            page_results.append(f.result())
    wall = time.time() - t0

    pages_by_doc = defaultdict(list)
    for pr in page_results:
        pages_by_doc[pr["doc_id"]].append(pr)
    ok_pages = sum(1 for pr in page_results if not pr["err"])
    errs = [pr for pr in page_results if pr["err"]]
    print(f"\n=== [{args.engine}] WALL: {wall:.1f}s · {ok_pages}/{len(jobs)} pags · "
          f"{ok_pages/wall:.2f} pags/s ===")
    if errs:
        print("  errores:", errs[0]["err"])
    # muestra de texto de 3 docs para chequear calidad
    print("--- muestra calidad (3 docs) ---")
    shown = 0
    for did in sorted(pages_by_doc):
        prs = sorted(pages_by_doc[did], key=lambda x: x["page"])
        text = " ".join(p["text"] for p in prs)
        print(f"  doc {did} {names.get(did,'?')[:38]} [{len(text)}c]: {text[:160]}")
        shown += 1
        if shown >= 3:
            break
    con.close()


if __name__ == "__main__":
    main()
