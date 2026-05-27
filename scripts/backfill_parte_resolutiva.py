#!/usr/bin/env python3
"""Backfill de `parte_resolutiva_1st` / `parte_resolutiva_2nd` (transcripción verbatim
del RESUELVE) sobre los casos existentes.

DETERMINISTA — 0 LLM, 0 GPU. Solo llena columnas VACÍAS (respeta lo curado a mano).

Uso:
    python3 scripts/backfill_parte_resolutiva.py            # dry-run (no escribe)
    python3 scripts/backfill_parte_resolutiva.py --apply    # escribe (hacer backup antes)
"""
from __future__ import annotations

import sys
import warnings

warnings.filterwarnings("ignore")

from backend.database.database import SessionLocal
from backend.database.models import Case, Document
from backend.v9.field_extractor import (
    extract_parte_resolutiva_1ra_for_case,
    extract_parte_resolutiva_2da_for_case,
)

APPLY = "--apply" in sys.argv


def main() -> None:
    db = SessionLocal()
    # Casos que tienen alguna sentencia (1ra o 2da)
    cids = {
        r[0]
        for r in db.query(Document.case_id)
        .filter(Document.doc_type.in_(["SENTENCIA_1RA", "SENTENCIA_2DA"]))
        .distinct()
        .all()
    }
    fill_1 = fill_2 = skip_1 = skip_2 = 0
    samples: list[str] = []
    for cid in sorted(cids):
        c = db.query(Case).get(cid)
        if not c:
            continue
        # 1ra — solo si está vacío
        if not (c.parte_resolutiva_1st or "").strip():
            v, _src = extract_parte_resolutiva_1ra_for_case(db, c)
            if v:
                if APPLY:
                    c.parte_resolutiva_1st = v
                fill_1 += 1
                if len(samples) < 5:
                    samples.append(f"c{cid} 1ra: {v[:90]!r}")
        else:
            skip_1 += 1
        # 2da — solo si está vacío
        if not (c.parte_resolutiva_2nd or "").strip():
            v, _src = extract_parte_resolutiva_2da_for_case(db, c)
            if v:
                if APPLY:
                    c.parte_resolutiva_2nd = v
                fill_2 += 1
        else:
            skip_2 += 1

    if APPLY:
        db.commit()

    print(f"Casos con sentencia: {len(cids)}")
    print(f"parte_resolutiva_1st a llenar: {fill_1}  (ya tenían valor: {skip_1})")
    print(f"parte_resolutiva_2nd a llenar: {fill_2}  (ya tenían valor: {skip_2})")
    print()
    print("Muestras:")
    for s in samples:
        print("  ", s)
    print()
    print("APLICADO ✓" if APPLY else "DRY-RUN (usar --apply para escribir; hacer backup antes)")


if __name__ == "__main__":
    main()
