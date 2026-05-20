#!/usr/bin/env python3
"""Barrido: cases con sentido_fallo_1st='CONCEDE' cuyo SENTENCIA_1RA real NIEGA.

Read-only. Ubica el RESUELVE/FALLA del fallo de 1ra y clasifica el verbo del
PRIMERO dispositivo. Imprime un reporte y escribe data/sweep_concede_2026-05-19.json.
"""
from __future__ import annotations
import json, re, sqlite3, sys
from pathlib import Path

from backend.services import seguimiento_resolutivo as SR

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "tutelas.db"

DENIEGA = ("DENEGAR", "DENIEGA", "DENIÉGASE", "NEGAR", "NIEGA", "NIÉGASE", "NIEGUE",
           "IMPROCEDENTE", "IMPROCEDENCIA", "RECHAZAR", "RECHAZA", "NO TUTELAR",
           "NO CONCEDER", "NO AMPARAR", "NO ACCEDER", "ABSTIENE", "ABSTENERSE")
CONCEDE = ("TUTELAR", "AMPARAR", "AMPÁRESE", "CONCEDER", "CONCÉDESE", "PROTEGER",
           "PROTÉJASE", "ORDENAR", "ORDÉNASE", "ACCEDER")
CARENCIA = ("CARENCIA ACTUAL DE OBJETO", "HECHO SUPERADO", "DAÑO CONSUMADO",
            "CARENCIA DE OBJETO", "SUSTRACCIÓN DE MATERIA")


def primer_dispositivo(tail: str) -> str:
    up = tail.upper()
    i = max(up.rfind("RESUELVE"), up.rfind("FALLA"))
    if i < 0:
        return ""
    seg = tail[i: i + 1200]
    # recortar al primer ordinal..segundo
    m = re.search(r"PRIMERO\s*[:.–\-]", seg, re.I)
    if m:
        rest = seg[m.start():]
        m2 = re.search(r"SEGUNDO\s*[:.–\-]", rest, re.I)
        return (rest[:m2.start()] if m2 else rest)[:600]
    return seg[:600]


def clasificar(disp: str) -> str:
    u = disp.upper()
    if not u.strip():
        return "SIN_RESUELVE"
    if any(k in u for k in CARENCIA):
        return "CARENCIA_OBJETO"
    has_c = any(k in u for k in CONCEDE)
    has_d = any(k in u for k in DENIEGA)
    # "NEGAR las demas pretensiones" tras conceder -> sigue CONCEDE
    if has_c and not has_d:
        return "CONCEDE_OK"
    if has_d and not has_c:
        return "DENIEGA_MISMATCH"
    if has_c and has_d:
        # el verbo que aparece primero gana
        pc = min((u.find(k) for k in CONCEDE if k in u), default=9999)
        pd = min((u.find(k) for k in DENIEGA if k in u), default=9999)
        return "CONCEDE_OK" if pc <= pd else "DENIEGA_MISMATCH"
    return "AMBIGUO"


def main():
    con = sqlite3.connect(str(DB)); con.row_factory = sqlite3.Row
    c = con.cursor()
    rows = list(c.execute("""
        SELECT c.id, c.radicado_23_digitos rad, c.accionante, d.file_path, d.filename
        FROM cases c
        JOIN documents d ON d.case_id=c.id AND d.doc_type='SENTENCIA_1RA'
        WHERE c.sentido_fallo_1st='CONCEDE'
          AND c.processing_status != 'DUPLICATE_MERGED'
        GROUP BY c.id ORDER BY c.id"""))
    out = {"DENIEGA_MISMATCH": [], "CARENCIA_OBJETO": [], "AMBIGUO": [],
           "SIN_RESUELVE": [], "CONCEDE_OK": [], "ERROR": []}
    for r in rows:
        try:
            tail, _, ocr = SR.read_resolutive_tail(r["file_path"], 8)
            disp = primer_dispositivo(tail)
            cat = clasificar(disp)
            rec = {"case_id": r["id"], "rad": r["rad"], "accionante": r["accionante"],
                   "filename": r["filename"], "ocr": ocr, "primer": disp.strip()[:240]}
            out[cat].append(rec)
        except Exception as e:
            out["ERROR"].append({"case_id": r["id"], "err": str(e)[:120]})
        print(f"\rprocesados {sum(len(v) for v in out.values())}/{len(rows)}", end="", file=sys.stderr)
    print(file=sys.stderr)
    (ROOT / "data" / "sweep_concede_2026-05-19.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"TOTAL CONCEDE con SENTENCIA_1RA: {len(rows)}")
    for k in ("DENIEGA_MISMATCH", "CARENCIA_OBJETO", "AMBIGUO", "SIN_RESUELVE", "CONCEDE_OK", "ERROR"):
        print(f"  {k}: {len(out[k])}")
    print("\n=== SOSPECHOSOS (DENIEGA_MISMATCH) ===")
    for rec in out["DENIEGA_MISMATCH"]:
        print(f"  case {rec['case_id']} | {rec['accionante']} | ocr={rec['ocr']}")
        print(f"     {rec['primer']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
