#!/usr/bin/env python3
"""Reingesta comparativa de acumulaciones — antes/después del fix v9.2.

Corre el `acumulacion_resolver` sobre una COPIA de una DB (por defecto el backup
pre-fix del caso Hato) y muestra el estado del cohorte ANTES y DESPUÉS, sin tocar
producción. Demuestra que el sistema nuevo:
  - cosecha el radicado "desnudo" 00047 que el viejo perdía,
  - crea el caso hermano faltante (Liliana) con su accionante,
  - vincula RECTOR/ACUMULADO,
  - enruta cada sentencia individual al caso de su accionante.

Uso:
    ./venv/bin/python3 scripts/acumulacion_reingest_compare.py \
        --db data/tutelas.db.bak_pre_acumulacion_hato_20260525_155705 \
        --case 397 [--apply]
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.database.models import Case, Document  # noqa: E402
from backend.email.acumulacion_resolver import plan_acumulacion, apply_plan  # noqa: E402


def _session(db_file: str):
    engine = create_engine(f"sqlite:///{db_file}")

    @event.listens_for(engine, "connect")
    def _fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    return sessionmaker(bind=engine)()


def _cohorte(db, case_ids: set[int]):
    rows = []
    for c in db.query(Case).filter(Case.id.in_(case_ids)).order_by(Case.id).all():
        ndocs = db.query(Document).filter(Document.case_id == c.id).count()
        rows.append((c.id, c.radicado_23_digitos, (c.accionante or "")[:32],
                     c.tipo_acumulacion, c.acumulado_a_case_id, ndocs))
    return rows


def _print_cohorte(title, rows):
    print(f"\n  {title}")
    print(f"  {'id':>4} {'rad23':<24} {'accionante':<32} {'tipo_acum':<11} {'→padre':>7} {'docs':>4}")
    for r in rows:
        print(f"  {r[0]:>4} {str(r[1] or '—'):<24} {r[2]:<32} {str(r[3] or '—'):<11} {str(r[4] or '—'):>7} {r[5]:>4}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/tutelas.db.bak_pre_acumulacion_hato_20260525_155705")
    ap.add_argument("--case", type=int, required=True, help="caso primario (bucket)")
    ap.add_argument("--apply", action="store_true", help="aplica sobre la COPIA (nunca el original)")
    ap.add_argument("--move-files", action="store_true")
    args = ap.parse_args()

    src = ROOT / args.db
    if not src.exists():
        print(f"ERROR: no existe {src}")
        return 1

    tmp = Path(tempfile.mkdtemp()) / "reingest_copy.db"
    shutil.copy(src, tmp)
    print(f"Copia de trabajo: {tmp}  (origen: {args.db})")

    db = _session(str(tmp))
    try:
        primary = db.get(Case, args.case)
        if not primary:
            print(f"ERROR: caso {args.case} no existe en la DB")
            return 1

        plan = plan_acumulacion(db, primary)
        before_ids = {it.case_id for it in plan.items if it.case_id} | {primary.id}

        print("\n" + "=" * 78)
        print(f"  PLAN DE ACUMULACIÓN para caso primario #{primary.id} "
              f"«{(primary.folder_name or '')[:40]}»")
        print("=" * 78)
        if not plan.is_acumulacion:
            print("  → NO se detectó acumulación.")
            for n in plan.notes:
                print(f"    nota: {n}")
            return 0

        print(f"  Radicados cosechados: {[it.rad_corto for it in plan.items]}")
        print(f"  RECTOR: {plan.rector_rad}   fecha: {plan.fecha or '(sin fecha)'}")
        print("\n  Acciones por radicado:")
        for it in plan.items:
            print(f"    {it.rad_corto}  {it.role:<9} {it.action:<7} "
                  f"case={it.case_id or 'NUEVO'}  accionante={it.accionante or '?'}")
        print("\n  Enrutamiento de documentos individuales:")
        if not plan.doc_routes:
            print("    (ninguno)")
        for r in plan.doc_routes:
            print(f"    doc {r.doc_id} '{r.filename[:45]}' → {r.to_rad} (case {r.to_case_id or 'NUEVO'})")

        _print_cohorte("ANTES:", _cohorte(db, before_ids))

        if not args.apply:
            print("\n  (dry-run — sin cambios. Usa --apply para aplicar sobre la copia.)")
            return 0

        summary = apply_plan(db, plan, primary, move_files=args.move_files)
        after_ids = before_ids | {x["case_id"] for x in summary["created"]}
        _print_cohorte("DESPUÉS:", _cohorte(db, after_ids))
        print(f"\n  Resumen: creados={len(summary['created'])} "
              f"vinculados={len(summary['linked'])} docs_enrutados={len(summary['routed'])}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
