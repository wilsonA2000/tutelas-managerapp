"""Canonicaliza abogado_responsable -> abogado_canonical para los 220 casos.

Uso:
    python3 scripts/run_abogado_canonicalization.py --dry-run
    python3 scripts/run_abogado_canonicalization.py --execute

Idempotente: solo escribe si abogado_canonical actual difiere del resuelto.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.data.abogados_resolver import resolve_with_metadata
from backend.database.database import SessionLocal
from backend.database.models import Case


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="Reporte sin escribir")
    g.add_argument("--execute", action="store_true", help="Persiste cambios en DB")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        cases = (
            db.query(Case)
            .filter(Case.processing_status != "DUPLICATE_MERGED")
            .all()
        )
        method_counter: Counter[str] = Counter()
        canon_counter: Counter[str] = Counter()
        changed = 0
        unresolved: list[tuple[int, str]] = []

        for c in cases:
            raw = (c.abogado_responsable or "").strip()
            if not raw:
                method_counter["empty_input"] += 1
                continue
            r = resolve_with_metadata(raw)
            method_counter[r["method"]] += 1
            new_canon = r["canonical"]
            new_conf = float(r["confidence"]) if r["confidence"] else 0.0

            if new_canon:
                canon_counter[new_canon] += 1
            else:
                unresolved.append((c.id, raw))

            prev_canon = c.abogado_canonical
            prev_conf = c.abogado_canonical_confidence
            if prev_canon != new_canon or prev_conf != new_conf:
                changed += 1
                if args.execute:
                    c.abogado_canonical = new_canon
                    c.abogado_canonical_confidence = new_conf

        if args.execute:
            db.commit()
            print(f"\n[OK] Persistidos {changed} cambios en cases.abogado_canonical")
        else:
            print(f"\n[DRY-RUN] Cambiarian {changed} casos")

        print(f"\nTotal casos activos: {len(cases)}")
        print("\nMetodos de resolucion:")
        for m, n in method_counter.most_common():
            print(f"  {n:4d}  {m}")

        print(f"\nCobertura canonical: {sum(canon_counter.values())}/{len(cases)} "
              f"= {sum(canon_counter.values()) / len(cases) * 100:.1f}%")

        print("\nDistribucion canonical (top 10):")
        for canon, n in canon_counter.most_common(10):
            print(f"  {n:4d}  {canon}")

        if unresolved:
            print(f"\nNo resueltos ({len(unresolved)}):")
            for case_id, raw in unresolved[:20]:
                print(f"  case_id={case_id}  raw={raw!r}")
            if len(unresolved) > 20:
                print(f"  ... y {len(unresolved) - 20} mas")

        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
