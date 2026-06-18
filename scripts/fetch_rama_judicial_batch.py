"""Fase D batch: descarga los expedientes CPNU de los casos que en cache tienen
actuaciones con documentos. Resumible (dedup sha256 → re-correr salta lo ya bajado).
Aislado por caso (una excepción no mata el batch). Uso:
    python3 scripts/fetch_rama_judicial_batch.py [--dry-run] [--throttle 0.4] [--only 4,512]
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal
from backend.database.models import Case
from backend.email.rad_utils import normalize_rad23
from backend.services import rama_judicial_client as rj
from backend.services.rama_judicial_fetcher import fetch_case_documents

CACHE = ROOT / "data" / "cpnu_cache"


def cases_con_docs(db):
    """case_ids cuyo rad23 está en cache con actuaciones-con-documento."""
    rad2case = {}
    for cid, r in db.query(Case.id, Case.radicado_23_digitos).filter(
            Case.processing_status != "DUPLICATE_MERGED"):
        rn = normalize_rad23(r)
        if rn:
            rad2case[rn] = cid
    out = []
    for p in glob.glob(str(CACHE / "*.json")):
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        if not d.get("encontrado"):
            continue
        cond = [a for a in d.get("actuaciones", [])
                if a.get("con_documentos") and a.get("id_reg_actuacion")]
        if cond and d["rad23"] in rad2case:
            out.append(rad2case[d["rad23"]])
    return sorted(set(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--throttle", type=float, default=1.5,
                    help="segundos entre llamadas/descargas (CPNU bloquea ráfagas)")
    ap.add_argument("--case-cooldown", type=float, default=8.0,
                    help="pausa entre casos para no gatillar el rate-limit por IP")
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    db = SessionLocal()
    ids = cases_con_docs(db)
    if args.only:
        want = {int(x) for x in args.only.split(",")}
        ids = [c for c in ids if c in want]
    print(f"casos a procesar: {len(ids)} -> {ids}", flush=True)

    session = rj._new_session()
    tot = {"descargados": 0, "dedup": 0, "errors": 0, "casos_ok": 0}
    for i, cid in enumerate(ids, 1):
        try:
            r = fetch_case_documents(db, cid, dry_run=args.dry_run,
                                     throttle=args.throttle, session=session)
            d, dd, e = r.get("descargados", 0), r.get("dedup", 0), r.get("errors", 0)
            tot["descargados"] += d; tot["dedup"] += dd; tot["errors"] += e
            tot["casos_ok"] += 1
            print(f"[{i}/{len(ids)}] c{cid}: {r.get('estado')} "
                  f"descargados={d} dedup={dd} errors={e}", flush=True)
        except Exception as e:
            print(f"[{i}/{len(ids)}] c{cid}: EXCEPCIÓN {type(e).__name__}: {str(e)[:120]}",
                  flush=True)
            traceback.print_exc()
        time.sleep(args.case_cooldown)   # cooldown entre casos (anti rate-limit CPNU)
    db.close()
    print(f"\nTOTAL: descargados={tot['descargados']} dedup={tot['dedup']} "
          f"errors={tot['errors']} casos={tot['casos_ok']}/{len(ids)}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
