#!/usr/bin/env python3
"""Fase 6 — Curación del golden a partir del cuadro CURADO de la DB (ground truth).

Regla de Wilson: la verdad es la DB curada en la app, no extracts crudos. Así que:
  - valor NO vacío en la DB  -> valor VERIFICADO (se conserva tal cual).
  - vacío ESTRUCTURALMENTE implicado -> null (vacío VERIFICADO, mide alucinación):
      * impugnacion != SI  -> quien_impugno/forest_impugnacion/juzgado_2nd/
                              sentido_fallo_2nd/fecha_fallo_2nd/parte_resolutiva_2nd
      * incidente   != SI  -> fecha_apertura_incidente/responsable_desacato/
                              abogado_incidente/decision_incidente/parte_resolutiva_incidente
      * incidente_2/3 != SI -> sus campos *_2 / *_3
  - resto de vacíos -> "" (PENDIENTE de criterio legal humano; NO se mide aún).

Conserva el set de casos ya elegido en golden_v1.json. READ-ONLY sobre la DB.
Respalda el golden anterior antes de escribir.

Uso: venv/bin/python3 scripts/bench/golden_curate.py
"""
from __future__ import annotations
import json, sqlite3, sys, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.v9.types import EXCEL_FIELDS  # noqa: E402

DB = ROOT / "data" / "tutelas.db"
GOLDEN = ROOT / "data" / "golden" / "golden_v1.json"

# Campos que dependen estructuralmente de un gate SI/NO.
SECOND_INSTANCE = ["quien_impugno", "forest_impugnacion", "juzgado_2nd",
                   "sentido_fallo_2nd", "fecha_fallo_2nd", "parte_resolutiva_2nd"]
INCIDENTE_1 = ["fecha_apertura_incidente", "responsable_desacato", "abogado_incidente",
               "decision_incidente", "parte_resolutiva_incidente"]
INCIDENTE_2 = ["fecha_apertura_incidente_2", "responsable_desacato_2", "abogado_incidente_2", "decision_incidente_2"]
INCIDENTE_3 = ["fecha_apertura_incidente_3", "responsable_desacato_3", "abogado_incidente_3", "decision_incidente_3"]


def _is_si(v: str) -> bool:
    return (v or "").strip().upper() in ("SI", "SÍ")


def main() -> int:
    g = json.loads(GOLDEN.read_text(encoding="utf-8"))
    case_ids = [k for k in g if k != "_meta"]
    cols = ",".join(EXCEL_FIELDS)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    stats = {"verified_value": 0, "structural_null": 0, "pending_empty": 0, "missing_case": 0}
    out = {"_meta": {
        "status": "DB_CURATED_SNAPSHOT_2026-06-04",
        "n": len(case_ids),
        "rule": "valor DB curado = verdad; vacío estructural (impugnacion/incidente=NO) = null; resto '' pendiente",
        "note": "null = vacío VERIFICADO (mide alucinación). '' = aún sin verificar (no se puntúa).",
    }}

    for cid in case_ids:
        row = con.execute(f"SELECT {cols} FROM cases WHERE id=?", (int(cid),)).fetchone()
        if not row:
            stats["missing_case"] += 1
            continue
        vals = {f: (row[i] or "") for i, f in enumerate(EXCEL_FIELDS)}
        impugna = _is_si(vals["impugnacion"])
        inc1, inc2, inc3 = _is_si(vals["incidente"]), _is_si(vals["incidente_2"]), _is_si(vals["incidente_3"])
        rec: dict = {}
        for f in EXCEL_FIELDS:
            v = (vals[f] or "").strip()
            if v:
                rec[f] = v
                stats["verified_value"] += 1
                continue
            # vacío: ¿estructuralmente implicado?
            structural = (
                (f in SECOND_INSTANCE and not impugna) or
                (f in INCIDENTE_1 and not inc1) or
                (f in INCIDENTE_2 and not inc2) or
                (f in INCIDENTE_3 and not inc3)
            )
            if structural:
                rec[f] = None
                stats["structural_null"] += 1
            else:
                rec[f] = ""
                stats["pending_empty"] += 1
        out[cid] = rec

    con.close()
    shutil.copy2(GOLDEN, GOLDEN.with_suffix(".json.bak_precurate"))
    GOLDEN.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ Golden curado: {len(case_ids)} casos · {GOLDEN.name}")
    print(f"  valores verificados: {stats['verified_value']}")
    print(f"  nulls estructurales (medibles para alucinación): {stats['structural_null']}")
    print(f"  vacíos pendientes (criterio humano, no se puntúan): {stats['pending_empty']}")
    if stats["missing_case"]:
        print(f"  ⚠ casos del golden ya no en DB: {stats['missing_case']}")
    print(f"  backup: {GOLDEN.with_suffix('.json.bak_precurate').name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
