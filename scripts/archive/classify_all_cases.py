#!/usr/bin/env python3
"""Pobla cases.origen y cases.estado_incidente usando case_classifier v6.0.

Uso:
    python3 scripts/classify_all_cases.py                 # dry run
    python3 scripts/classify_all_cases.py --apply         # escribe a DB
    python3 scripts/classify_all_cases.py --only-null     # solo casos con origen NULL
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database.database import SessionLocal
from backend.database.models import Case
from backend.cognition.procedural_timeline import build_timeline
from backend.cognition.case_classifier import classify_case


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true", help="Escribe a DB (default dry-run)")
    p.add_argument("--only-null", action="store_true", help="Solo casos con origen=NULL")
    args = p.parse_args()

    db = SessionLocal()
    try:
        q = db.query(Case)
        if args.only_null:
            q = q.filter(Case.origen.is_(None))
        cases = q.all()
        stats_origen: Counter[str] = Counter()
        stats_estado: Counter[str] = Counter()
        changes = 0

        print(f"Clasificando {len(cases)} casos ({'apply' if args.apply else 'dry-run'})\n")
        for case in cases:
            tl = build_timeline(case)
            cls = classify_case(case, tl)
            stats_origen[cls.origen] += 1
            stats_estado[cls.estado_incidente] += 1

            if cls.origen != case.origen or cls.estado_incidente != case.estado_incidente:
                changes += 1
                if changes <= 20:
                    print(f"  case {case.id:>3} {case.folder_name[:45]:<45} "
                          f"{case.origen or '—':<18} → {cls.origen:<18} "
                          f"estado: {case.estado_incidente or '—':<12} → {cls.estado_incidente}")

            if args.apply:
                case.origen = cls.origen
                case.estado_incidente = cls.estado_incidente

        if args.apply:
            db.commit()

        print("\n=== Distribución origen ===")
        for o, n in stats_origen.most_common():
            print(f"  {o or '(null)':<20} {n}")
        print("\n=== Distribución estado_incidente ===")
        for e, n in stats_estado.most_common():
            print(f"  {e or '(null)':<20} {n}")
        print(f"\nTotal casos procesados: {len(cases)}")
        print(f"Cambios: {changes} ({'aplicados' if args.apply else 'no aplicados — usa --apply'})")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
