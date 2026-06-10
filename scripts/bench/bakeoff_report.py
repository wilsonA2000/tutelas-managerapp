#!/usr/bin/env python3
"""Fase 1 — Reporte de la matriz + regla de decisión por carril.

Lee data/bench/*.json (salidas del arnés) y produce:
  - una tabla celda × (velocidad warm/cold · calidad · degeneración · tok/s · mem)
  - delta vs baseline (current__baseline__cache-true)
  - recomendación por carril (RÁPIDO / PROFUNDO) según la regla del plan.

Regla RÁPIDO:  min alucinación (o, si el oro aún no tiene null curados, max accuracy
               y degeneración=0) sujeto a lat_warm ≤ baseline; desempata por menor tiempo.
Regla PROFUNDO: max accuracy/semántico sujeto a pico mem ≤ presupuesto; tiempo relajado.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCH_DIR = ROOT / "data" / "bench"
RAM_BUDGET_MB = int(os.getenv("BENCH_RAM_BUDGET_MB", "24000"))
BASELINE_TAG = os.getenv("BENCH_BASELINE_TAG", "current__baseline__cache-true")


def load_cells() -> list[dict]:
    cells = []
    for fn in sorted(BENCH_DIR.glob("*.json")):
        try:
            d = json.loads(fn.read_text(encoding="utf-8"))
            if "agg" in d:
                cells.append(d)
        except Exception as e:  # noqa: BLE001
            print(f"  (saltado {fn.name}: {e})", file=sys.stderr)
    return cells


def _f(v, nd=2):
    return "—" if v is None else f"{v:.{nd}f}"


def main() -> int:
    cells = load_cells()
    if not cells:
        print(f"No hay celdas en {BENCH_DIR.relative_to(ROOT)} todavía. Corre bakeoff_matrix.sh.")
        return 0

    base = next((c for c in cells if c["tag"] == BASELINE_TAG), None)
    base_warm = base["agg"]["lat_warm_avg_s"] if base else None

    # Tabla
    hdr = f"{'celda':42} {'warm_s':>7} {'cold_s':>7} {'acc':>6} {'halu':>6} {'deg':>4} {'dec_tps':>8} {'mem_MB':>8}"
    print(hdr); print("-" * len(hdr))
    for c in sorted(cells, key=lambda x: (x["agg"].get("lat_warm_avg_s") or 9e9)):
        a = c["agg"]
        mark = "  ←baseline" if c["tag"] == BASELINE_TAG else ""
        print(f"{c['tag'][:42]:42} {_f(a.get('lat_warm_avg_s')):>7} {_f(a.get('lat_cold_s')):>7} "
              f"{_f(a.get('accuracy_present_avg'),3):>6} {_f(a.get('hallucination_rate_avg'),3):>6} "
              f"{a.get('degenerate_total','—'):>4} {_f(a.get('decode_tokps_avg'),1):>8} "
              f"{_f(a.get('peak_rss_mb'),0):>8}{mark}")

    if base:
        print(f"\nbaseline = {BASELINE_TAG}: warm {_f(base_warm)}s · "
              f"acc {_f(base['agg'].get('accuracy_present_avg'),3)}")
    else:
        print(f"\n⚠ sin fila baseline ({BASELINE_TAG}). La compuerta de tiempo no se puede aplicar.")

    unverified = any(c.get("golden_status") == "UNVERIFIED_SEED" for c in cells)
    if unverified:
        print("⚠ gold UNVERIFIED_SEED → alucinación no medible aún; uso accuracy + degeneración=0 como proxy.")

    def acc(c):  # noqa: ANN001
        return c["agg"].get("accuracy_present_avg") or -1

    def warm(c):  # noqa: ANN001
        return c["agg"].get("lat_warm_avg_s")

    # --- Carril RÁPIDO ---
    fast = [c for c in cells if c["agg"].get("degenerate_total", 1) == 0
            and (base_warm is None or (warm(c) is not None and warm(c) <= base_warm + 1e-6))]
    if fast:
        if unverified:
            pick = max(fast, key=lambda c: (acc(c), -(warm(c) or 9e9)))
        else:
            pick = min(fast, key=lambda c: (c["agg"].get("hallucination_rate_avg") or 9e9, warm(c) or 9e9))
        print(f"\n🏁 CARRIL RÁPIDO → {pick['tag']}  (warm {_f(warm(pick))}s · acc {_f(acc(pick),3)} · "
              f"halu {_f(pick['agg'].get('hallucination_rate_avg'),3)})")
    else:
        print("\n🏁 CARRIL RÁPIDO → ninguna celda cumple (degeneración=0 y ≤ baseline). Revisa la tabla.")

    # --- Carril PROFUNDO ---
    deep = [c for c in cells if (c["agg"].get("peak_rss_mb") or 0) <= RAM_BUDGET_MB]
    if deep:
        pick = max(deep, key=lambda c: (acc(c), -(warm(c) or 9e9)))
        print(f"🧠 CARRIL PROFUNDO → {pick['tag']}  (acc {_f(acc(pick),3)} · warm {_f(warm(pick))}s · "
              f"mem {_f(pick['agg'].get('peak_rss_mb'),0)}MB ≤ {RAM_BUDGET_MB})")
    else:
        print(f"🧠 CARRIL PROFUNDO → ninguna celda bajo el presupuesto de {RAM_BUDGET_MB}MB.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
