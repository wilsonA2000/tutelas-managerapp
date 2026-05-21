#!/usr/bin/env python3
"""Confirmar docs REVISAR que pertenecen al caso; reportar los SOSPECHOSOS (rad ajeno).

Para cada caso con docs en verificacion='REVISAR':
  - extrae texto (PDF/DOCX/MD) y busca rad23 (68\\d{21}) y rad corto del caso.
  - PERTENECE  -> el doc no trae ningún rad23 ajeno (sin rad = insumo SED, o solo el propio).
  - SOSPECHOSO -> trae un rad23 cuyo rad21 (primeros 21 díg) difiere del rad21 del caso.

--apply confirma a OK los PERTENECE (verificacion='OK', anota detalle, audit_log).
Los SOSPECHOSO NUNCA se tocan (se listan para revisión 1-a-1).

Uso:
    python3 scripts/confirm_revisar_belongs.py --dry-run
    python3 scripts/confirm_revisar_belongs.py --apply
    python3 scripts/confirm_revisar_belongs.py --dry-run --case 60
"""
from __future__ import annotations
import argparse, json, re, sys, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import sqlite3
from backend.extraction.pdf_extractor import extract_pdf

RAD23 = re.compile(r"68\d{21}")
DB = ROOT / "data" / "tutelas.db"


def doc_text(fp: str) -> str:
    if not fp:
        return ""
    p = Path(fp)
    if not p.exists():
        return ""
    low = p.name.lower()
    try:
        if low.endswith(".pdf"):
            r = extract_pdf(fp, first_pages=3, last_pages=2)
            return getattr(r, "text", "") if not isinstance(r, str) else r
        if low.endswith((".md", ".txt")):
            return p.read_text(encoding="utf-8", errors="ignore")
        if low.endswith(".docx"):
            from backend.extraction.docx_extractor import extract_docx
            r = extract_docx(fp)
            return getattr(r, "text", "") if not isinstance(r, str) else (r or "")
    except Exception:
        return ""
    return ""  # .doc antiguos u otros: tratados como sin-rad (insumo)


def classify(text: str, case_rad21: str) -> tuple[str, list[str]]:
    rads = set(RAD23.findall(text or ""))
    foreign = sorted(r for r in rads if r[:21] != case_rad21)
    if foreign:
        return "SOSPECHOSO", foreign
    return "PERTENECE", []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--case", type=int, default=None)
    ap.add_argument("--status", default="REVISAR", help="verificacion a procesar (REVISAR | '' )")
    args = ap.parse_args()
    apply = args.apply and not args.dry_run

    db = sqlite3.connect(str(DB))
    c = db.cursor()
    q = ("select d.id,d.case_id,d.filename,d.file_path,c.radicado_23_digitos "
         "from documents d join cases c on c.id=d.case_id "
         f"where d.verificacion=?")
    if args.case:
        q += f" and d.case_id={args.case}"
    rows = c.execute(q, (args.status,)).fetchall()
    print(f"REVISAR a analizar: {len(rows)}  (modo {'APPLY' if apply else 'DRY-RUN'})")

    belongs, suspects = [], []
    by_case_belong: dict[int, int] = {}
    for did, cid, fn, fp, rad23 in rows:
        rad21 = (rad23 or "")[:21]
        if not rad21:
            # Caso sin rad23: si el doc tampoco trae rad23 es insumo -> PERTENECE.
            # Si trae rad23(s) puede ser el rad real del caso o uno ajeno -> revisar.
            doc_rads = sorted(set(RAD23.findall(doc_text(fp))))
            if not doc_rads:
                belongs.append((did, cid, fn))
                by_case_belong[cid] = by_case_belong.get(cid, 0) + 1
            else:
                suspects.append((did, cid, fn, [f"(caso sin rad23; doc trae {r})" for r in doc_rads]))
            continue
        verdict, foreign = classify(doc_text(fp), rad21)
        if verdict == "PERTENECE":
            belongs.append((did, cid, fn))
            by_case_belong[cid] = by_case_belong.get(cid, 0) + 1
        else:
            suspects.append((did, cid, fn, foreign))

    print(f"\n== PERTENECE: {len(belongs)} docs en {len(by_case_belong)} casos ==")
    print(f"== SOSPECHOSO (rad ajeno o caso sin rad): {len(suspects)} docs ==")
    for did, cid, fn, foreign in suspects:
        print(f"  d{did} c{cid} {fn[:55]} | ajeno={foreign}")

    if apply:
        now = datetime.datetime.now(datetime.UTC).isoformat()
        for did, cid, fn in belongs:
            c.execute(
                "update documents set verificacion='OK', "
                "verificacion_detalle=COALESCE(verificacion_detalle,'')||? where id=?",
                (" | [2026-05-21] confirmado OK: pertenece al caso (sin rad ajeno) tras revisión REVISAR", did))
            c.execute(
                "insert into audit_log(case_id,field_name,old_value,new_value,action,source,timestamp,entity_type,entity_id,description) "
                "values(?,?,?,?,?,?,?,?,?,?)",
                (cid, "verificacion", args.status or "(vacío)", "OK", "CONFIRM_BELONGS", "confirm_revisar_belongs",
                 now, "document", did, f"Confirmado OK: {fn[:80]} (sin rad ajeno)"))
        db.commit()
        print(f"\nAPLICADO: {len(belongs)} docs -> OK. {len(suspects)} sospechosos intactos en REVISAR.")
    else:
        out = ROOT / "data" / "revisar_suspects.json"
        out.write_text(json.dumps([{"doc": d, "case": ci, "file": f, "foreign": fo}
                                   for d, ci, f, fo in suspects], ensure_ascii=False, indent=2))
        print(f"\n(dry-run) sospechosos -> {out}")


if __name__ == "__main__":
    main()
