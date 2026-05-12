#!/usr/bin/env python3
"""Arregla las 2 contradicciones frecuentes que dejan casos en REVISION v6.0.

Patrón 1 (dominante, ~86 casos):
  impugnacion = 'NO'
  + sentido_fallo_2nd o fecha_fallo_2nd o quien_impugno poblados
  → inferir impugnacion = 'SI' (la evidencia de 2da instancia manda)

Patrón 2 (~7 casos):
  incidente = 'NO'
  + fecha_apertura_incidente o responsable_desacato o decision_incidente
    poblados
  → inferir incidente = 'SI'

Tras arreglar, re-persiste vía cognitive_persist para que el entropy gate
los reevalúe. Esperado: la mayoría pasan de REVISION a COMPLETO.

Uso:
    python3 scripts/fix_contradictions_v6.py              # dry-run
    python3 scripts/fix_contradictions_v6.py --apply      # aplica
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database.database import SessionLocal
from backend.database.models import Case
from backend.cognition.cognitive_persist import persist_case


def _has(s):
    return bool(s and str(s).strip() and str(s).strip().upper() not in ("N/A", "NULL", "NONE"))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true", help="Escribir cambios a DB")
    args = p.parse_args()

    db = SessionLocal()
    try:
        fixed_imp = 0
        fixed_inc = 0
        candidates: list[Case] = []

        for case in db.query(Case).filter(Case.processing_status == "REVISION").all():
            changed = False

            # Patrón 1: impugnacion=NO pero hay datos 2da instancia
            if (case.impugnacion or "").upper().startswith("N"):
                if _has(case.sentido_fallo_2nd) or _has(case.fecha_fallo_2nd) or _has(case.quien_impugno) or _has(case.juzgado_2nd):
                    case.impugnacion = "SI"
                    fixed_imp += 1
                    changed = True

            # Patrón 2: incidente=NO pero hay datos desacato
            if (case.incidente or "").upper().startswith("N"):
                if _has(case.fecha_apertura_incidente) or _has(case.responsable_desacato) or _has(case.decision_incidente):
                    case.incidente = "SI"
                    fixed_inc += 1
                    changed = True

            if changed:
                candidates.append(case)

        print(f"[dry-run={not args.apply}]")
        print(f"Casos con patrón impugnacion NO→SI: {fixed_imp}")
        print(f"Casos con patrón incidente NO→SI: {fixed_inc}")
        print(f"Total candidatos únicos: {len(candidates)}")

        if not args.apply:
            db.rollback()
            print("\nSin aplicar. Usa --apply para escribir a DB.")
            return 0

        db.commit()
        print(f"\nCampos corregidos: {fixed_imp + fixed_inc}")

        # Re-persistir con entropy gate
        print("\nRe-persistiendo con cognitive_persist...")
        promoted = 0
        still_revision = 0
        for case in candidates:
            rep = persist_case(db, case, convergence_iterations=case.convergence_iterations or 1)
            if rep.status_after == "COMPLETO":
                promoted += 1
            else:
                still_revision += 1

        print(f"Promovidos a COMPLETO: {promoted}")
        print(f"Siguen en REVISION: {still_revision}")

        # Resumen final
        print("\n=== Estado final ===")
        from sqlalchemy import func
        for st, n in db.query(Case.processing_status, func.count(Case.id)).group_by(Case.processing_status).all():
            print(f"  {st}: {n}")

        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
