#!/usr/bin/env python3
"""Fase 0 — Selección del gold set: los N casos MÁS COMPLETOS.

Decisión del usuario (híbrido): arrancamos con los 60 casos con más campos
EXCEL_FIELDS no vacíos como baseline inmediato, y se curan a mano después
(marcando `null` = vacío VERIFICADO para medir alucinación/abstención).

SEGURO: conexión READ-ONLY (mode=ro) — no escribe nunca la DB de producción.
Reusa la fuente única de verdad backend.v9.types.EXCEL_FIELDS.

Uso:
    venv/bin/python3 scripts/bench/golden_select.py            # top 60 -> candidatos + seed
    venv/bin/python3 scripts/bench/golden_select.py --n 40
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.v9.types import EXCEL_FIELDS  # noqa: E402

DB_PATH = ROOT / "data" / "tutelas.db"
GOLDEN_DIR = ROOT / "data" / "golden"
CANDIDATES = GOLDEN_DIR / "golden_candidates.json"
GOLDEN_V1 = GOLDEN_DIR / "golden_v1.json"

# Campos verbatim/semánticos "difíciles" — para reportar cobertura de estratificación.
HARD_SIGNALS = ("incidente", "impugnacion", "pretensiones", "derecho_vulnerado", "observaciones")


def _ro_conn() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def _fill_expr() -> str:
    return " + ".join(
        f"(CASE WHEN {f} IS NOT NULL AND TRIM({f})!='' THEN 1 ELSE 0 END)"
        for f in EXCEL_FIELDS
    )


def select_most_complete(conn: sqlite3.Connection, n: int) -> list[dict]:
    """Top-N casos COMPLETO por nº de EXCEL_FIELDS no vacíos."""
    q = (
        f"SELECT id, ({_fill_expr()}) AS llenos "
        "FROM cases WHERE processing_status='COMPLETO' "
        "ORDER BY llenos DESC, id ASC LIMIT ?"
    )
    rows = conn.execute(q, (n,)).fetchall()
    out = []
    cols = ",".join(EXCEL_FIELDS)
    for cid, llenos in rows:
        vals = conn.execute(f"SELECT {cols} FROM cases WHERE id=?", (cid,)).fetchone()
        case_vals = {f: (vals[i] or "") for i, f in enumerate(EXCEL_FIELDS)}
        out.append({
            "case_id": cid,
            "fill_count": llenos,
            "completitud_pct": round(100 * llenos / len(EXCEL_FIELDS), 1),
            "has_incidente": (case_vals["incidente"] or "").upper() in ("SI", "SÍ"),
            "has_impugnacion": (case_vals["impugnacion"] or "").upper() in ("SI", "SÍ"),
            "has_pretensiones": bool((case_vals["pretensiones"] or "").strip()),
            "_values": case_vals,
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60, help="nº de casos más completos")
    args = ap.parse_args()

    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    with _ro_conn() as conn:
        sel = select_most_complete(conn, args.n)

    if not sel:
        print("!! 0 casos COMPLETO encontrados", file=sys.stderr)
        return 1

    # Candidatos (ranking + señales de estratificación, sin valores)
    candidates = [{k: v for k, v in c.items() if k != "_values"} for c in sel]
    CANDIDATES.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")

    # Seed golden_v1: valores ACTUALES de la DB. "" = aún NO verificado-ausente.
    # El humano edita y cambia "" -> null donde confirme ausencia real.
    seed = {
        "_meta": {
            "status": "UNVERIFIED_SEED",
            "n": len(sel),
            "rule": "top-N COMPLETO por EXCEL_FIELDS no vacíos",
            "note": "Verificar a mano. '' = no verificado; null = vacío VERIFICADO (para alucinación/abstención).",
        }
    }
    for c in sel:
        seed[str(c["case_id"])] = c["_values"]
    GOLDEN_V1.write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")

    # Reporte
    n = len(sel)
    strat = {
        "con_incidente": sum(c["has_incidente"] for c in sel),
        "con_impugnacion": sum(c["has_impugnacion"] for c in sel),
        "con_pretensiones": sum(c["has_pretensiones"] for c in sel),
    }
    print(f"✓ {n} casos seleccionados (fill_count {sel[-1]['fill_count']}–{sel[0]['fill_count']} de {len(EXCEL_FIELDS)})")
    print(f"  estratificación: {strat}")
    print(f"  → {CANDIDATES.relative_to(ROOT)}")
    print(f"  → {GOLDEN_V1.relative_to(ROOT)}  (seed UNVERIFIED — pendiente curación manual)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
