#!/usr/bin/env python3
"""Extrae texto (head+tail) de los PDFs de los gaps de extracción.

Imprime para cada caso una sección legible que Claude lee manualmente y decide
el valor del campo (sentido fallo, fecha, decisión incidente, etc.).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "tutelas.db"

HEAD_PAGES = 3
TAIL_PAGES = 4
HEAD_CHARS = 4500
TAIL_CHARS = 6000


def extract_text_headtail(pdf_path: str) -> str:
    try:
        with pdfplumber.open(pdf_path) as pdf:
            n = len(pdf.pages)
            head_n = min(HEAD_PAGES, n)
            tail_n = min(TAIL_PAGES, max(0, n - head_n))
            head_pages = pdf.pages[:head_n]
            tail_pages = pdf.pages[n - tail_n:] if tail_n else []

            head_txt = "\n".join((p.extract_text() or "") for p in head_pages)
            tail_txt = "\n".join((p.extract_text() or "") for p in tail_pages) if tail_pages else ""
            txt = head_txt[:HEAD_CHARS]
            if tail_txt:
                txt += "\n\n[...TAIL...]\n\n" + tail_txt[-TAIL_CHARS:]
            return txt
    except Exception as e:
        return f"[ERROR leyendo {pdf_path}: {e}]"


def main():
    if len(sys.argv) < 2:
        print("uso: _dump_gap_pdfs.py <gap>   gap in {A,B,C,E}")
        return 1
    gap = sys.argv[1].upper()

    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    c = con.cursor()

    if gap == "A":
        sql = """SELECT c.id, c.radicado_23_digitos, c.folder_name, c.accionante,
                        c.sentido_fallo_1st, c.impugnacion,
                        d.file_path, d.filename
                 FROM cases c JOIN documents d ON d.case_id=c.id
                 WHERE d.doc_type='SENTENCIA_2DA'
                   AND (c.sentido_fallo_2nd IS NULL OR TRIM(c.sentido_fallo_2nd)='')
                   AND c.processing_status != 'DUPLICATE_MERGED'
                 ORDER BY c.id, d.id"""
    elif gap == "C":
        sql = """SELECT c.id, c.radicado_23_digitos, c.folder_name, c.accionante,
                        c.sentido_fallo_1st, c.incidente, c.decision_incidente,
                        d.doc_type, d.file_path, d.filename
                 FROM cases c JOIN documents d ON d.case_id=c.id
                 WHERE d.doc_type IN ('INCIDENTE_DESACATO','AUTO_INCIDENTE')
                   AND UPPER(COALESCE(c.incidente,'')) NOT IN ('SI','S','SÍ')
                   AND c.processing_status != 'DUPLICATE_MERGED'
                 ORDER BY c.id, d.id"""
    elif gap == "E":
        sql = """SELECT c.id, c.radicado_23_digitos, c.folder_name, c.accionante,
                        d.file_path, d.filename
                 FROM cases c JOIN documents d ON d.case_id=c.id
                 WHERE d.doc_type='SENTENCIA_1RA'
                   AND (c.sentido_fallo_1st IS NULL OR TRIM(c.sentido_fallo_1st)='')
                   AND c.processing_status != 'DUPLICATE_MERGED'
                 ORDER BY c.id, d.id"""
    elif gap == "B":
        sql = """SELECT c.id, c.radicado_23_digitos, c.folder_name, c.accionante,
                        c.impugnacion, d.file_path, d.filename
                 FROM cases c JOIN documents d ON d.case_id=c.id
                 WHERE d.doc_type='IMPUGNACION'
                   AND UPPER(COALESCE(c.impugnacion,'')) NOT IN ('SI','S','SÍ')
                   AND c.processing_status != 'DUPLICATE_MERGED'
                 ORDER BY c.id, d.id"""
    else:
        print(f"gap desconocido: {gap}")
        return 1

    rows = list(c.execute(sql))
    seen = set()
    for r in rows:
        # solo el primer PDF por caso (el más representativo)
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        print("=" * 80)
        print(f"CASE_ID={r['id']}  rad23={r['radicado_23_digitos'] or '-'}")
        print(f"folder={r['folder_name']}")
        print(f"accionante={r['accionante']}")
        if "sentido_fallo_1st" in r.keys():
            print(f"contexto: sentido_fallo_1st={r['sentido_fallo_1st']}")
        if "impugnacion" in r.keys():
            print(f"contexto: impugnacion_actual={r['impugnacion']}")
        if "incidente" in r.keys():
            print(f"contexto: incidente_actual={r['incidente']}  decision_actual={r.get('decision_incidente') if hasattr(r,'get') else r['decision_incidente'] if 'decision_incidente' in r.keys() else None}")
        print(f"PDF: {r['filename']}")
        print(f"PATH: {r['file_path']}")
        print("-" * 80)
        txt = extract_text_headtail(r["file_path"])
        print(txt)
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
