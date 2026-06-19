"""Backfill: vuelca las actuaciones CPNU ya cacheadas (data/cpnu_cache) a
case_actuaciones (Fase C). Idempotente (dedup en sync_case_actuaciones). Sin red."""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal, wal_checkpoint
from backend.database.models import Case
from backend.email.rad_utils import normalize_rad23
from backend.services.rama_judicial_sync import sync_case_actuaciones

CACHE = ROOT / "data" / "cpnu_cache"


def main():
    db = SessionLocal()
    rad2case = {}
    for cid, r in db.query(Case.id, Case.radicado_23_digitos).filter(
            Case.processing_status != "DUPLICATE_MERGED"):
        rn = normalize_rad23(r)
        if rn:
            rad2case[rn] = cid
    total_added = casos = 0
    for p in glob.glob(str(CACHE / "*.json")):
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        if not d.get("encontrado") or d["rad23"] not in rad2case:
            continue
        case = db.query(Case).filter(Case.id == rad2case[d["rad23"]]).first()
        r = sync_case_actuaciones(db, case, d)
        if r["added"]:
            casos += 1
            total_added += r["added"]
            print(f"  c{case.id}: +{r['added']} actuaciones", flush=True)
    wal_checkpoint()
    db.close()
    print(f"\nTOTAL: +{total_added} actuaciones en {casos} casos", flush=True)


if __name__ == "__main__":
    sys.exit(main())
