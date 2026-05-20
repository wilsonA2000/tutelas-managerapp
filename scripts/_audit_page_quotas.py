#!/usr/bin/env python3
"""Auditoría empírica: ¿en qué páginas vive cada sección por tipo de documento?

Para fijar cuotas de páginas a enviar al LLM por (doc_type, campo):
  - SENTENCIA/AUTO → ¿a cuántas páginas DEL FINAL está el RESUELVE/FALLA? (sentido)
  - DEMANDA/escrito tutela → ¿en qué página (desde el inicio) están PRETENSIONES/HECHOS?

Read-only (pymupdf). Reporta distribución (p50/p90/max) para decidir las cuotas.
"""
from __future__ import annotations
import re, sqlite3, sys
from pathlib import Path
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "tutelas.db"
SAMPLE = 50  # docs por categoría

RE_RESUELVE = re.compile(r"(?i)\b(?:r\s*e\s*s\s*u\s*e\s*l\s*v\s*e|falla\b|fallo\s+de\s+tutela|decide)\b")
RE_PRET = re.compile(r"(?i)\b(?:pretensi[oó]n(?:es)?|petici[oó]n(?:es)?|solicit\w+|s[uú]plic\w+|ruego\s+a)\b")
RE_HECHOS = re.compile(r"(?i)\b(?:hechos|fundamentos\s+f[aá]cticos|antecedentes\s+f[aá]cticos)\b")


def pages_text(fp):
    try:
        d = pymupdf.open(fp)
        out = [d[i].get_text() or "" for i in range(d.page_count)]
        d.close()
        return out
    except Exception:
        return []


def pctl(xs, p):
    if not xs:
        return None
    xs = sorted(xs); k = int(round((p/100)*(len(xs)-1)))
    return xs[k]


def main():
    con = sqlite3.connect(str(DB)); con.row_factory = sqlite3.Row; c = con.cursor()

    def docs(where):
        q = f"""SELECT d.id,d.filename,d.file_path FROM documents d JOIN cases ca ON ca.id=d.case_id
                WHERE {where} AND d.file_path LIKE '%.pdf' AND ca.processing_status!='DUPLICATE_MERGED'
                ORDER BY d.id LIMIT {SAMPLE}"""
        return list(c.execute(q))

    # 1) SENTENCIAS: ¿a cuántas páginas del FINAL está el RESUELVE?
    print("=== SENTENCIAS — RESUELVE (páginas desde el FINAL) ===")
    npags, from_end = [], []
    for d in docs("d.doc_type IN ('SENTENCIA_1RA','SENTENCIA_2DA')"):
        pgs = pages_text(d["file_path"])
        if not pgs:
            continue
        npags.append(len(pgs))
        last = None
        for i, t in enumerate(pgs):
            if RE_RESUELVE.search(t):
                last = i
        if last is not None:
            from_end.append(len(pgs) - last)  # 1 = última página
    print(f"  n={len(npags)} | páginas/doc: p50={pctl(npags,50)} p90={pctl(npags,90)} max={max(npags) if npags else 0}")
    print(f"  RESUELVE a páginas del final: p50={pctl(from_end,50)} p90={pctl(from_end,90)} max={max(from_end) if from_end else 0}")
    print(f"  → cuota sugerida 'últimas N': p90={pctl(from_end,90)}")

    # 2) DEMANDAS/escritos de tutela: ¿en qué página (desde inicio) PRETENSIONES y HECHOS?
    print("\n=== DEMANDAS/ESCRITO TUTELA — PRETENSIONES/HECHOS (páginas desde el INICIO) ===")
    npags2, pret_pg, hechos_pg = [], [], []
    for d in docs("(d.doc_type IN ('DEMANDA_TUTELA','ANEXO_DEMANDA') OR LOWER(d.filename) LIKE '%tutela%' OR LOWER(d.filename) LIKE '%demanda%')"):
        pgs = pages_text(d["file_path"])
        if not pgs or len(" ".join(pgs)) < 500:
            continue
        npags2.append(len(pgs))
        for i, t in enumerate(pgs):
            if RE_PRET.search(t):
                pret_pg.append(i+1); break
        for i, t in enumerate(pgs):
            if RE_HECHOS.search(t):
                hechos_pg.append(i+1); break
    print(f"  n={len(npags2)} | páginas/doc: p50={pctl(npags2,50)} p90={pctl(npags2,90)} max={max(npags2) if npags2 else 0}")
    print(f"  PRETENSIONES en página: p50={pctl(pret_pg,50)} p90={pctl(pret_pg,90)} max={max(pret_pg) if pret_pg else 0} (de {len(pret_pg)} docs)")
    print(f"  HECHOS en página:       p50={pctl(hechos_pg,50)} p90={pctl(hechos_pg,90)} max={max(hechos_pg) if hechos_pg else 0} (de {len(hechos_pg)} docs)")
    print(f"  → cuota sugerida 'primeras N': p90 pretensiones={pctl(pret_pg,90)}")

    # 3) Distribución de páginas global por doc_type (para el umbral 'completo si ≤ N')
    print("\n=== PÁGINAS por doc_type (umbral 'completo') ===")
    for dt in ('SENTENCIA_1RA', 'SENTENCIA_2DA', 'DEMANDA_TUTELA', 'AUTO_ADMISORIO', 'AUTO_INCIDENTE', 'INCIDENTE_DESACATO', 'RESPUESTA'):
        ns = []
        for d in docs(f"d.doc_type='{dt}'"):
            pgs = pages_text(d["file_path"])
            if pgs:
                ns.append(len(pgs))
        if ns:
            print(f"  {dt:20} n={len(ns):3} p50={pctl(ns,50)} p90={pctl(ns,90)} max={max(ns)}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
