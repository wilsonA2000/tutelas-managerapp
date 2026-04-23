#!/usr/bin/env python3
"""Compara snapshot pre vs estado actual de la DB para medir ganancia v5.5.

Uso:
    python3 scripts/compare_extraction_v55.py logs/snapshot_pre_reextract_v55_XXXX.json

Reporta por campo:
- Nuevos valores (estaban vacíos, ahora llenos)
- Cambiados (tenían valor, ahora otro)
- Perdidos (tenían valor, ahora vacíos)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

DB_EXPERIMENT = "/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026 A/tutelas-app/data/tutelas.db"

SEMANTIC_FIELDS = [
    "radicado_23_digitos", "radicado_forest", "accionante", "accionados",
    "vinculados", "derecho_vulnerado", "juzgado", "ciudad", "fecha_ingreso",
    "asunto", "pretensiones", "oficina_responsable", "sentido_fallo_1st",
    "fecha_fallo_1st", "impugnacion", "quien_impugno", "sentido_fallo_2nd",
    "fecha_fallo_2nd", "responsable_desacato", "decision_incidente",
    "observaciones",
]


def load_snapshot(path: Path) -> dict[int, dict]:
    data = json.loads(path.read_text())
    return {row["id"]: row for row in data}


def load_current(db: str) -> dict[int, dict]:
    conn = sqlite3.connect(db)
    try:
        cols = ["id", "processing_status", *SEMANTIC_FIELDS]
        rows = conn.execute(f"SELECT {', '.join(cols)} FROM cases").fetchall()
        return {r[0]: dict(zip(cols, r)) for r in rows}
    finally:
        conn.close()


def is_filled(v) -> bool:
    if v is None:
        return False
    s = str(v).strip()
    if not s:
        return False
    return s.lower() not in ("n/a", "no aplica", "-", "pendiente", "revision")


def compare(pre: dict, cur: dict) -> dict:
    common_ids = set(pre.keys()) & set(cur.keys())
    diffs = {"ganados": Counter(), "cambiados": Counter(), "perdidos": Counter()}
    per_case_ganados = {}

    for cid in common_ids:
        p = pre[cid]
        c = cur[cid]
        case_gains = []
        for f in SEMANTIC_FIELDS:
            pv = p.get(f)
            cv = c.get(f)
            pf = is_filled(pv)
            cf = is_filled(cv)
            if not pf and cf:
                diffs["ganados"][f] += 1
                case_gains.append(f)
            elif pf and not cf:
                diffs["perdidos"][f] += 1
            elif pf and cf and str(pv).strip() != str(cv).strip():
                diffs["cambiados"][f] += 1
        if case_gains:
            per_case_ganados[cid] = case_gains

    return {
        "common_cases": len(common_ids),
        "pre_only": len(set(pre) - set(cur)),
        "cur_only": len(set(cur) - set(pre)),
        "by_field": diffs,
        "per_case_ganados": per_case_ganados,
    }


def coverage_stats(rows: dict[int, dict]) -> dict:
    """% de casos con cada campo lleno."""
    stats = {}
    total = len(rows)
    if total == 0:
        return stats
    for f in SEMANTIC_FIELDS:
        filled = sum(1 for r in rows.values() if is_filled(r.get(f)))
        stats[f] = round(100 * filled / total, 1)
    return stats


def status_counts(rows: dict[int, dict]) -> Counter:
    return Counter(r.get("processing_status", "?") for r in rows.values())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path, help="JSON snapshot pre")
    parser.add_argument("--db", default=DB_EXPERIMENT)
    args = parser.parse_args()

    if not args.snapshot.exists():
        print(f"ERROR: snapshot no existe: {args.snapshot}")
        return 1

    pre = load_snapshot(args.snapshot)
    cur = load_current(args.db)

    diff = compare(pre, cur)
    cov_pre = coverage_stats(pre)
    cov_cur = coverage_stats(cur)

    print("=" * 70)
    print("COMPARATIVA EXTRACCIÓN PRE vs POST v5.5")
    print("=" * 70)
    print(f"Casos comunes: {diff['common_cases']} · "
          f"solo-pre: {diff['pre_only']} · solo-post: {diff['cur_only']}")
    print()
    print("Estado procesamiento:")
    print(f"  pre : {dict(status_counts(pre))}")
    print(f"  post: {dict(status_counts(cur))}")
    print()
    print("─" * 70)
    print(f"{'CAMPO':<25} {'COV PRE':>8} {'COV POST':>9} {'Δ':>6} {'GANADOS':>8} {'PERDIDOS':>9} {'CAMBIADOS':>10}")
    print("─" * 70)
    for f in SEMANTIC_FIELDS:
        p = cov_pre.get(f, 0)
        c = cov_cur.get(f, 0)
        delta = round(c - p, 1)
        sign = "+" if delta > 0 else ("" if delta < 0 else " ")
        print(f"{f:<25} {p:>7.1f}% {c:>8.1f}% {sign}{delta:>5.1f} "
              f"{diff['by_field']['ganados'][f]:>8} "
              f"{diff['by_field']['perdidos'][f]:>9} "
              f"{diff['by_field']['cambiados'][f]:>10}")
    print("─" * 70)
    total_ganados = sum(diff['by_field']['ganados'].values())
    total_perdidos = sum(diff['by_field']['perdidos'].values())
    total_cambiados = sum(diff['by_field']['cambiados'].values())
    print(f"{'TOTAL':<25} {'':<17} {'':>6} {total_ganados:>8} {total_perdidos:>9} {total_cambiados:>10}")
    print()
    print(f"Casos con mejoras: {len(diff['per_case_ganados'])}")
    if diff["per_case_ganados"]:
        top = sorted(diff["per_case_ganados"].items(), key=lambda kv: -len(kv[1]))[:5]
        print("Top casos con más campos ganados:")
        for cid, fields in top:
            print(f"  case {cid}: +{len(fields)} campos → {', '.join(fields[:6])}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
