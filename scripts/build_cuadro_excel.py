#!/usr/bin/env python3
"""Genera el cuadro Excel final (39 columnas) desde la DB.

Reutiliza `backend.reports.excel_generator.generate_excel` (las 3 hojas:
PORTADA / TUTELAS / ESTADISTICAS). No re-extrae nada — vuelca lo que ya está
en la tabla `cases` (lo que poblaron los `field_extractor`s de v9).

Uso:
    ./venv/bin/python3 scripts/build_cuadro_excel.py
    ./venv/bin/python3 scripts/build_cuadro_excel.py --output /tmp/cuadro.xlsx
    ./venv/bin/python3 scripts/build_cuadro_excel.py --coverage   # imprime % no-vacío por columna
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import EXPORTS_DIR  # noqa: E402
from backend.database.database import SessionLocal  # noqa: E402
from backend.database.models import Case  # noqa: E402
from backend.reports.excel_generator import COLUMN_CONFIG, generate_excel  # noqa: E402


def _load_cases(db):
    """Mismos filtros que `POST /api/reports/excel` (excluye merged y carpetas vacías)."""
    return (
        db.query(Case)
        .filter(
            Case.folder_name.isnot(None),
            Case.folder_name != "None",
            Case.folder_name != "",
            Case.processing_status != "DUPLICATE_MERGED",
        )
        .order_by(Case.id)
        .all()
    )


def _value_for(case, csv_col: str) -> str:
    if csv_col == "_TIPO_ACTUACION":
        return getattr(case, "tipo_actuacion", "TUTELA") or "TUTELA"
    attr = Case.CSV_FIELD_MAP.get(csv_col, "")
    return (getattr(case, attr, "") or "") if attr else ""


def _print_coverage(cases: list) -> None:
    total = len(cases)
    print(f"\nCobertura por columna ({total} casos):")
    print("-" * 64)
    for csv_col, header, _ in COLUMN_CONFIG:
        n = sum(1 for c in cases if str(_value_for(c, csv_col)).strip())
        pct = (100.0 * n / total) if total else 0.0
        bar = "#" * int(pct / 4)
        print(f"  {header:<24} {n:>4}/{total:<4} {pct:5.1f}%  {bar}")
    # completitud media por caso (sobre las 39 columnas del cuadro)
    per_case = []
    n_cols = len(COLUMN_CONFIG)
    for c in cases:
        filled = sum(1 for csv_col, _, _ in COLUMN_CONFIG if str(_value_for(c, csv_col)).strip())
        per_case.append(100.0 * filled / n_cols)
    avg = sum(per_case) / len(per_case) if per_case else 0.0
    print("-" * 64)
    print(f"  Completitud media por caso: {avg:.1f}%  ({n_cols} columnas)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Genera el cuadro Excel de tutelas (39 columnas) desde la DB.")
    ap.add_argument("--output", "-o", type=Path, default=None,
                    help="Ruta del .xlsx de salida (default: data/exports/CUADRO_TUTELAS_<ts>.xlsx)")
    ap.add_argument("--coverage", action="store_true",
                    help="Imprime también el % de celdas no-vacías por columna.")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        cases = _load_cases(db)
        if not cases:
            print("No hay casos en la base de datos.", file=sys.stderr)
            return 1

        if args.output is not None:
            out_path = args.output
            out_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone(timedelta(hours=-5))).strftime("%Y%m%d_%H%M")
            out_path = EXPORTS_DIR / f"CUADRO_TUTELAS_{ts}.xlsx"

        generate_excel(cases, str(out_path))
        size_kb = out_path.stat().st_size / 1024
        print(f"OK — {len(cases)} casos -> {out_path}  ({size_kb:.1f} KB)")
        print(f"     {len(COLUMN_CONFIG)} columnas | hojas: PORTADA, TUTELAS, ESTADISTICAS")

        if args.coverage:
            _print_coverage(cases)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
