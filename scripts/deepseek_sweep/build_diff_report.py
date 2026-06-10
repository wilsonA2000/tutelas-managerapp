#!/usr/bin/env python3
"""
Construye el reporte de diff del barrido DeepSeek.

Lee los JSONs de data/experiment/results/ y produce:
  data/experiment/diff_summary.csv   — una fila por (case_id, campo)
  data/experiment/diff_report.txt    — resumen por campo para consola

Semáforo:
  VERDE    — current="" y proposed!=""  → fill seguro
  AMARILLO — ambos non-empty y distintos → revisar
  ROJO     — campo manual protegido      → NUNCA pisar
  GRIS     — sin cambio / pipeline vacío → ignorar

Uso:
    python3 scripts/deepseek_sweep/build_diff_report.py
    python3 scripts/deepseek_sweep/build_diff_report.py --only-verde
    python3 scripts/deepseek_sweep/build_diff_report.py --campo accionante ciudad
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = ROOT / "data" / "experiment" / "results"
OUT_CSV = ROOT / "data" / "experiment" / "diff_summary.csv"
OUT_TXT = ROOT / "data" / "experiment" / "diff_report.txt"


def load_results() -> list[dict]:
    results = []
    for p in sorted(RESULTS_DIR.glob("*.json")):
        if p.name in ("checkpoint.json",):
            continue
        if "ERROR" in p.name:
            continue
        try:
            results.append(json.loads(p.read_text()))
        except json.JSONDecodeError:
            print(f"WARN: JSON inválido en {p.name}")
    return results


def build_rows(results: list[dict]) -> list[dict]:
    rows = []
    for res in results:
        case_id = res["case_id"]
        folder = res.get("folder_name", "")
        for d in res.get("diff", []):
            rows.append({
                "case_id": case_id,
                "folder_name": folder,
                "campo": d["campo"],
                "semaforo": d["semaforo"],
                "current": d["current"],
                "proposed": d["proposed"],
                "source": d.get("source", ""),
                "manual_protected": d.get("manual_protected", False),
            })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Reporte de diff barrido DeepSeek")
    parser.add_argument("--only-verde", action="store_true", help="Solo filas VERDE en CSV")
    parser.add_argument("--campo", nargs="+", help="Filtrar por campos específicos")
    args = parser.parse_args()

    results = load_results()
    if not results:
        print("No hay resultados en", RESULTS_DIR)
        print("Corre primero: python3 scripts/deepseek_sweep/run_sweep.py")
        sys.exit(1)

    total_cases = len(results)
    error_cases = sum(1 for p in RESULTS_DIR.glob("*_ERROR.json"))
    rows = build_rows(results)

    # Filtros opcionales
    if args.campo:
        rows = [r for r in rows if r["campo"] in args.campo]
    if args.only_verde:
        rows = [r for r in rows if r["semaforo"] == "VERDE"]

    # ── CSV ───────────────────────────────────────────────────────────────
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "case_id", "folder_name", "campo", "semaforo",
            "current", "proposed", "source", "manual_protected",
        ])
        writer.writeheader()
        writer.writerows(rows)
    print(f"CSV guardado: {OUT_CSV}  ({len(rows)} filas)")

    # ── Stats ─────────────────────────────────────────────────────────────
    by_sem: Counter = Counter(r["semaforo"] for r in rows)
    by_campo_verde: Counter = Counter(r["campo"] for r in rows if r["semaforo"] == "VERDE")
    by_campo_amarillo: Counter = Counter(r["campo"] for r in rows if r["semaforo"] == "AMARILLO")

    # Totales LLM
    llm_total = sum(res.get("llm_calls", 0) for res in results)
    ms_total = sum(res.get("elapsed_ms", 0) for res in results)

    lines = [
        "═══════════════════════════════════════════════════════════════",
        f" REPORTE DIFF — Barrido DeepSeek general",
        "═══════════════════════════════════════════════════════════════",
        f" Cases procesados: {total_cases}   Errores: {error_cases}",
        f" LLM calls totales: {llm_total}    Tiempo total: {ms_total/1000:.1f}s",
        "",
        " SEMÁFORO GLOBAL:",
        f"   🟢 VERDE    (fill vacío seguro): {by_sem['VERDE']:>5}",
        f"   🟡 AMARILLO (conflicto, revisar): {by_sem['AMARILLO']:>5}",
        f"   🔴 ROJO     (manual protegido):  {by_sem['ROJO']:>5}",
        "",
        f" TOP CAMPOS CON VERDE (fill vacío → {by_sem['VERDE']} total):",
    ]
    for campo, cnt in by_campo_verde.most_common(20):
        lines.append(f"   {campo:<35} {cnt:>4} casos")

    if by_campo_amarillo:
        lines += [
            "",
            f" TOP CAMPOS CON AMARILLO (conflicto → {by_sem['AMARILLO']} total):",
        ]
        for campo, cnt in by_campo_amarillo.most_common(15):
            lines += [f"   {campo:<35} {cnt:>4} casos"]

    lines += [
        "",
        " SIGUIENTE PASO:",
        "   Para ver casos amarillos de un campo específico:",
        "     python3 scripts/deepseek_sweep/build_diff_report.py --campo accionante",
        "",
        "   Para aplicar solo los verdes a la DB de experimento:",
        "     python3 scripts/deepseek_sweep/apply_accepted.py --mode fill-empty --target experiment",
        "",
        "   Para aplicar a producción (solo tras revisar experimento):",
        "     python3 scripts/deepseek_sweep/apply_accepted.py --mode fill-empty --target prod",
        "═══════════════════════════════════════════════════════════════",
    ]

    report_text = "\n".join(lines)
    print(report_text)
    OUT_TXT.write_text(report_text + "\n", encoding="utf-8")
    print(f"\nReporte guardado: {OUT_TXT}")


if __name__ == "__main__":
    main()
