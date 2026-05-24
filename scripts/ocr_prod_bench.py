#!/usr/bin/env python3
"""Benchmark PRODUCCIÓN-FIEL: mide el extract_pdf REAL (backend.extraction.
pdf_extractor) con ocr_scanned, llamándolo secuencialmente un doc a la vez —
exactamente como lo invoca el pipeline. NO reimplementa nada. DRY-RUN.

Uso: venv/bin/python scripts/ocr_prod_bench.py --limit 8 --mode full|headtail
"""
import os, sys, time, argparse, sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ap = argparse.ArgumentParser()
ap.add_argument("--limit", type=int, default=8)
ap.add_argument("--mode", choices=["full", "headtail"], default="full")
ap.add_argument("--skip-huge", action="store_true", help="excluir docs >15 pags")
args = ap.parse_args()

from backend.extraction.pdf_extractor import extract_pdf
import fitz

DB = os.path.join(os.path.dirname(__file__), "..", "data", "tutelas.db")
con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
rows = con.execute(
    """select id, file_path, filename from documents
       where doc_type='DESCONOCIDO' and length(trim(coalesce(extracted_text,'')))=0
       and lower(file_path) like '%.pdf' order by id""").fetchall()

fp_arg = (None, None) if args.mode == "full" else (5, 3)
print(f"extract_pdf REAL · mode={args.mode} · OCR es · secuencial (1 doc/vez)")

done = 0; tot_secs = 0.0; tot_ocr_pages = 0; tot_chars = 0
for r in rows:
    if done >= args.limit:
        break
    p = r["file_path"]
    if not p or not os.path.exists(p):
        continue
    try:
        d = fitz.open(p); npg = d.page_count; d.close()
    except Exception:
        continue
    if args.skip_huge and npg > 15:
        continue
    t0 = time.time()
    res = extract_pdf(p, first_pages=fp_arg[0], last_pages=fp_arg[1], ocr_scanned=True)
    dt = time.time() - t0
    done += 1; tot_secs += dt; tot_ocr_pages += res.ocr_pages; tot_chars += len(res.text)
    print(f"  doc {r['id']:5} {r['filename'][:40]:42} {npg:3}p ocr={res.ocr_pages:2} "
          f"{len(res.text):6}c {dt:6.1f}s [{res.method}]")

print(f"\n=== {done} docs · {tot_ocr_pages} págs OCR · {tot_secs:.1f}s · "
      f"{tot_ocr_pages/max(tot_secs,1):.2f} págs-OCR/s · {tot_chars} chars ===")
if tot_ocr_pages:
    print(f"  ritmo real: {tot_secs/tot_ocr_pages:.2f}s/pág-OCR (single-instance, prod)")
con.close()
