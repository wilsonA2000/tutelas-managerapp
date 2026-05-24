#!/usr/bin/env python3
"""Backfill OCR de los PDFs escaneados (extracted_text vacío) usando el
extract_pdf REAL de producción con ocr_scanned=True. Job de una sola vez,
paralelizado a nivel de documento. Persiste a DB solo donde sigue vacío
(idempotente). Documento completo (first/last=None) para capturar info valiosa.

Uso: venv/bin/python scripts/ocr_backfill.py --workers 6 --threads 2 [--apply]
     (sin --apply = dry-run, no escribe)
"""
import os, sys, time, argparse

_T = os.environ.get("OCR_BF_THREADS", "2")
for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(v, _T)

import sqlite3
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
DB = os.path.join(os.path.dirname(__file__), "..", "data", "tutelas.db")


def _init():
    os.environ.setdefault("OMP_NUM_THREADS", _T)


def _work(args):
    doc_id, path = args
    from backend.extraction.pdf_extractor import extract_pdf
    t0 = time.time()
    try:
        r = extract_pdf(path, first_pages=None, last_pages=None, ocr_scanned=True)
        return {"id": doc_id, "text": r.text or "", "ocr": r.ocr_pages,
                "method": r.method, "secs": time.time() - t0, "err": r.error}
    except Exception as e:
        return {"id": doc_id, "text": "", "ocr": 0, "method": "err",
                "secs": time.time() - t0, "err": str(e)[:160]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    os.environ["OCR_BF_THREADS"] = str(args.threads)

    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    q = """select id, file_path from documents
           where length(trim(coalesce(extracted_text,'')))=0
           and lower(file_path) like '%.pdf'"""
    if args.limit:
        q += f" limit {args.limit}"
    rows = con.execute(q).fetchall()
    jobs = [(r["id"], r["file_path"]) for r in rows
            if r["file_path"] and os.path.exists(r["file_path"])]
    print(f"OCR backfill · {len(jobs)} docs · {args.workers}w×{args.threads}t · "
          f"{'APPLY' if args.apply else 'DRY-RUN'}", flush=True)

    t0 = time.time(); done = 0; written = 0; ocr_total = 0; errs = 0
    with ProcessPoolExecutor(max_workers=args.workers, initializer=_init) as ex:
        futs = [ex.submit(_work, j) for j in jobs]
        for f in as_completed(futs):
            r = f.result(); done += 1; ocr_total += r["ocr"]
            if r["err"]:
                errs += 1
            txt = r["text"].strip()
            if args.apply and len(txt) >= 100:
                cur = con.execute("select length(trim(coalesce(extracted_text,'')))"
                                  " from documents where id=?", (r["id"],)).fetchone()[0]
                if cur == 0:
                    con.execute("update documents set extracted_text=?, extraction_method=?"
                                " where id=?", (r["text"], r["method"], r["id"]))
                    con.commit(); written += 1
            if done % 20 == 0:
                el = time.time() - t0
                print(f"  {done}/{len(jobs)} · {ocr_total} pág-OCR · {el:.0f}s · "
                      f"{ocr_total/max(el,1):.2f} pág/s · escritos={written} · err={errs}",
                      flush=True)
    el = time.time() - t0
    print(f"\n=== FIN: {done} docs · {ocr_total} pág-OCR · {el:.0f}s ({el/60:.1f} min) · "
          f"{ocr_total/max(el,1):.2f} pág/s · escritos={written} · err={errs} ===", flush=True)
    con.close()


if __name__ == "__main__":
    main()
