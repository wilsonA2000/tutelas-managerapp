#!/usr/bin/env python3
"""Re-corre el resolutivo (con el 4B) sobre los candidatos P1+P2 del sweep.

DRY-RUN: no escribe en la DB. Vuelca data/rerun_4b_p1p2_dryrun.json con las
órdenes propuestas por caso, para revisión humana antes de persistir.

P1 = no_match (PDF leído, sin orden) + sentido CONCEDE/CONFIRMA/REVOCA + 0 órdenes.
P2 = no_pdf por el buscador del rerun PERO la DB sí tiene un doc SENTENCIA*.
"""
from __future__ import annotations
import json, sqlite3, sys
from pathlib import Path

from backend.services import seguimiento_resolutivo as SR

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "tutelas.db"
RERUN = ROOT / "data" / "seguimiento_rerun_2026-05-19.json"
OUT = ROOT / "data" / "rerun_4b_p1p2_dryrun.json"


def main():
    d = json.load(open(RERUN))
    con = sqlite3.connect(str(DB)); con.row_factory = sqlite3.Row
    c = con.cursor()

    def case_meta(cid):
        return c.execute("SELECT accionante,sentido_fallo_1st,sentido_fallo_2nd,fecha_fallo_1st,fecha_fallo_2nd FROM cases WHERE id=?", (cid,)).fetchone()

    def n_ordenes(cid):
        return c.execute("SELECT COUNT(*) FROM compliance_tracking WHERE case_id=? AND ordinal_nombre IS NOT NULL", (cid,)).fetchone()[0]

    targets = []  # (case_id, pdf_path, prioridad)

    # P1: del bucket no_match
    for x in d["no_match"]:
        cid = x["case_id"]; r = case_meta(cid)
        if not r:
            continue
        s1 = (r["sentido_fallo_1st"] or "").upper(); s2 = (r["sentido_fallo_2nd"] or "").upper()
        concede = any(k in s1 or k in s2 for k in ("CONCEDE",)) or any(k in s2 for k in ("REVOCA", "CONFIRMA", "MODIFICA"))
        if concede and n_ordenes(cid) == 0 and x.get("pdf"):
            targets.append((cid, x["pdf"], "P1"))

    # P2: del bucket no_pdf, pero DB tiene SENTENCIA
    for x in d["no_pdf"]:
        cid = x["case_id"]
        doc = c.execute("""SELECT file_path FROM documents
                           WHERE case_id=? AND doc_type LIKE 'SENTENCIA%'
                           ORDER BY (doc_type='SENTENCIA_2DA') DESC, id DESC LIMIT 1""", (cid,)).fetchone()
        if doc and doc["file_path"]:
            targets.append((cid, doc["file_path"], "P2"))

    print(f"Total a procesar: {len(targets)}", file=sys.stderr)
    out = []
    for i, (cid, pdf, prio) in enumerate(targets, 1):
        r = case_meta(cid)
        fecha = r["fecha_fallo_2nd"] or r["fecha_fallo_1st"]
        try:
            res = SR.extract_ordenes_focalizado(
                pdf, sentido_fallo_1st=r["sentido_fallo_1st"], sentido_fallo_2nd=r["sentido_fallo_2nd"],
                fecha_fallo=fecha, sed_es_accionada=True, use_llm=True)
            rec = {
                "case_id": cid, "prio": prio, "accionante": r["accionante"],
                "f1": r["sentido_fallo_1st"], "f2": r["sentido_fallo_2nd"],
                "metodo": res.metodo, "n_ordenes": len(res.ordenes),
                "pdf": Path(pdf).name,
                "ordenes": [{
                    "ordinal": o.ordinal_nombre, "verbo": o.verbo_orden,
                    "dest": o.destinatario_tipo, "tipo_plazo": o.tipo_plazo,
                    "plazo_dias": o.plazo_dias, "accion": o.accion_resumida[:200], "source": o.source,
                } for o in res.ordenes],
            }
        except Exception as e:
            rec = {"case_id": cid, "prio": prio, "accionante": r["accionante"], "error": str(e)[:160]}
        out.append(rec)
        print(f"\r[{i}/{len(targets)}] case {cid} {rec.get('metodo','ERR')} n={rec.get('n_ordenes','-')}      ", end="", file=sys.stderr)
    print(file=sys.stderr)

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    con_ord = [r for r in out if r.get("n_ordenes", 0) > 0]
    print(f"\nDONE. {len(out)} casos procesados. {len(con_ord)} con órdenes propuestas. -> {OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
