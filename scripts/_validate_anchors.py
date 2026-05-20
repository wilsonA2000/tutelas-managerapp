#!/usr/bin/env python3
"""Validación de ANCLAS jurídicas contra el corpus real (read-only).

Por cada doc muestreado, busca cada patrón-ancla página por página y reporta en qué
página cae + un snippet, para confirmar que el ancla pega en la sección correcta
(y descubrir variaciones / falsos positivos). Claude lee la salida y refina.
"""
from __future__ import annotations
import re, sqlite3, sys
from pathlib import Path
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "tutelas.db"

ANCHORS = {
    "PRETENSIONES": re.compile(r"(?i)\b(pretensi[oó]n(?:es)?\b|solicit[oa]\b|s[úu]plic\w*|ruego\s+a\s+su|se\s+sirva\s+(?:tutelar|amparar|ordenar|conceder)|por\s+lo\s+(?:anterior|expuesto)[,\s]+solicit)"),
    "HECHOS": re.compile(r"(?i)\b(hechos\b|fundamentos\s+f[áa]cticos|con\s+base\s+en\s+los\s+(?:siguientes\s+)?hechos|relaci[oó]n\s+de\s+(?:los\s+)?hechos)"),
    "CALIDAD": re.compile(r"(?i)(obrando\s+en\s+calidad|actuando\s+(?:como|en\s+calidad)|en\s+(?:mi|su)\s+calidad\s+de|agente\s+oficios\w*|representante\s+legal)"),
    "RESUELVE": re.compile(r"(?i)(\br\s*e\s*s\s*u\s*e\s*l\s*v\s*e\b|\bfalla\b|en\s+m[ée]rito\s+de\s+lo\s+expuesto|administrando\s+justicia)"),
    "DESISTIMIENTO": re.compile(r"(?i)(acepta\w*\s+(?:el\s+)?desistimiento|tener\s+por\s+desistid|desistimiento\s+de\s+la\s+(?:acci[oó]n|tutela))"),
    "DESACATO": re.compile(r"(?i)(incidente\s+de\s+desacato|sancionar\s+por\s+desacato|abstenerse\s+de\s+(?:sancionar|abrir))"),
}

# qué anclas miramos por tipo de doc
BY_TYPE = {
    "DEMANDA_TUTELA": ["PRETENSIONES", "HECHOS", "CALIDAD"],
    "SENTENCIA_1RA":  ["RESUELVE"],
    "SENTENCIA_2DA":  ["RESUELVE"],
    "AUTO_INCIDENTE": ["DESISTIMIENTO", "DESACATO", "RESUELVE"],
    "INCIDENTE_DESACATO": ["DESACATO", "DESISTIMIENTO"],
}


def main():
    con = sqlite3.connect(str(DB)); con.row_factory = sqlite3.Row; c = con.cursor()
    for dtype, anchors in BY_TYPE.items():
        rows = list(c.execute(
            f"""SELECT d.filename,d.file_path FROM documents d JOIN cases ca ON ca.id=d.case_id
                WHERE d.doc_type=? AND d.file_path LIKE '%.pdf' AND ca.processing_status!='DUPLICATE_MERGED'
                ORDER BY d.id LIMIT 7""", (dtype,)))
        print(f"\n{'='*78}\n### {dtype} — anclas: {anchors}\n{'='*78}")
        for r in rows:
            try:
                doc = pymupdf.open(r["file_path"]); pgs = [doc[i].get_text() or "" for i in range(doc.page_count)]; doc.close()
            except Exception:
                continue
            if not pgs:
                continue
            print(f"\n  · {r['filename'][:55]}  ({len(pgs)} págs)")
            for a in anchors:
                rx = ANCHORS[a]
                hits = []
                for i, t in enumerate(pgs):
                    m = rx.search(t)
                    if m:
                        snip = re.sub(r"\s+", " ", t[max(0, m.start()-30):m.start()+70])
                        hits.append((i+1, snip))
                if hits:
                    pg, snip = hits[0]
                    print(f"      {a:13} 1ª pág {pg}/{len(pgs)} ({len(hits)} hits): …{snip}…")
                else:
                    print(f"      {a:13} (sin match)")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
