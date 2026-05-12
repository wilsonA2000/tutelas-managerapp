#!/usr/bin/env python3
"""Mide entropía de Shannon del cuadro de casos.

Uso:
    python3 scripts/measure_entropy.py                          # DB experimental, reporte completo
    python3 scripts/measure_entropy.py --save logs/entropy_X.json
    python3 scripts/measure_entropy.py --compare a.json b.json  # diff entre dos snapshots
    python3 scripts/measure_entropy.py --db /ruta/otra.db
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Path del proyecto
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.cognition.entropy import entropy_of_case, entropy_of_db, ALL_FIELDS, FIELD_STATES


DB_DEFAULT = "/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026 A/tutelas-app/data/tutelas.db"


class _CaseRow:
    """Adaptador ligero: acceso a columnas como atributos para entropy_of_case."""
    def __init__(self, row: dict):
        self.__dict__.update(row)


def _load_cases(db_path: str) -> list[_CaseRow]:
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cols = ["id", "folder_name", "processing_status", "impugnacion", "incidente",
                *[f for f in ALL_FIELDS]]
        # Eliminar duplicados preservando orden
        seen = set()
        ucols = [c for c in cols if not (c in seen or seen.add(c))]
        q = f"SELECT {', '.join(ucols)} FROM cases"
        rows = conn.execute(q).fetchall()
        return [_CaseRow(dict(r)) for r in rows]
    finally:
        conn.close()


def _report_json(report: dict) -> dict:
    """Transforma reporte a JSON serializable (excluye objetos dataclass)."""
    out = {k: v for k, v in report.items() if k != "reports"}
    out["per_case"] = [
        {
            "id": r.case_id,
            "folder": r.folder_name,
            "status": r.processing_status,
            "h": r.entropy_bits,
            "states": r.state_counts,
            "inconsistent": r.inconsistent_fields,
            "empty_expected": r.expected_empty_fields,
        }
        for r in report.get("reports", [])
    ]
    return out


def _print_summary(report: dict) -> None:
    print("=" * 70)
    print("ENTROPÍA DEL CUADRO DE CASOS")
    print("=" * 70)
    print(f"Total casos:                {report['total_cases']}")
    print(f"Casos COMPLETO:              {report['completos']}")
    print(f"H promedio (todos):          {report['mean_entropy_all']:.4f} bits")
    print(f"H promedio (COMPLETO):       {report['mean_entropy_completos']:.4f} bits")
    print(f"Casos con inconsistencias:   {report['cases_with_inconsistencies']}")
    print(f"Inconsistencias totales:     {report['total_inconsistencies']}")
    print()
    print("Estados agregados (todos los casos, todos los campos):")
    agg = report["aggregate_states"]
    total = sum(agg.values()) or 1
    for state in FIELD_STATES:
        n = agg.get(state, 0)
        pct = 100 * n / total
        print(f"  {state:<24} {n:>6}  ({pct:5.1f}%)")
    print()
    print("Top 10 casos con mayor entropía (más desorden):")
    for w in report.get("worst_cases", []):
        print(f"  case {w['id']:>3}  H={w['h']:.3f}  empty={w['empty']}  inconsistent={w['inconsistent']}  {w['folder'][:45]}")


def _compare(a_path: Path, b_path: Path) -> int:
    a = json.loads(a_path.read_text())
    b = json.loads(b_path.read_text())
    print(f"Baseline A: {a_path.name}")
    print(f"Snapshot B: {b_path.name}")
    print()
    print(f"{'Métrica':<32} {'A':>12} {'B':>12} {'Δ':>12}")
    print("-" * 70)
    for k in ("total_cases", "completos", "mean_entropy_all", "mean_entropy_completos",
              "cases_with_inconsistencies", "total_inconsistencies"):
        va = a.get(k, 0)
        vb = b.get(k, 0)
        if isinstance(va, float):
            print(f"{k:<32} {va:>12.4f} {vb:>12.4f} {(vb-va):>+12.4f}")
        else:
            print(f"{k:<32} {va:>12} {vb:>12} {(vb-va):>+12}")
    print()
    h_drop_pct = 0
    if a.get("mean_entropy_all"):
        h_drop_pct = 100 * (a["mean_entropy_all"] - b["mean_entropy_all"]) / a["mean_entropy_all"]
    print(f"Reducción de entropía global: {h_drop_pct:+.1f}%")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DB_DEFAULT)
    parser.add_argument("--save", type=Path, help="Guardar snapshot JSON")
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("A", "B"),
                        help="Comparar dos snapshots JSON")
    args = parser.parse_args()

    if args.compare:
        return _compare(args.compare[0], args.compare[1])

    cases = _load_cases(args.db)
    report = entropy_of_db(cases)
    _print_summary(report)

    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(_report_json(report), ensure_ascii=False, indent=2))
        print(f"\nSnapshot guardado: {args.save}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
