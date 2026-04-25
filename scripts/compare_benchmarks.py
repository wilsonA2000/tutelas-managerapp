#!/usr/bin/env python3
"""Compara los 3 benchmarks de Gmail ingest experimento v6.0.1.

Genera tabla markdown comparativa.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"

LABELS = [
    ("baseline_pre_v601", "Baseline pre-v6.0.1"),
    ("v601_retroactive", "v6.0.1 retroactivo"),
    ("v601_fresh", "v6.0.1 fresh"),
]


def load(label: str) -> dict:
    f = LOGS / f"benchmark_{label}.json"
    return json.loads(f.read_text())


def delta(a, b, fmt=""):
    try:
        d = b - a
        sign = "+" if d > 0 else ""
        return f"{sign}{d:{fmt}}"
    except (TypeError, ValueError):
        return "-"


def main():
    data = [load(l[0]) for l in LABELS]
    names = [l[1] for l in LABELS]

    print("# Comparativa benchmarks Gmail ingest — experimento TUTELAS 2026 B\n")
    print(f"- {names[0]}: pre-optimización (estado a sync crasheado)")
    print(f"- {names[1]}: pesos + IGNORE + reconcile + regex aplicados RETROACTIVAMENTE sobre la DB crasheada")
    print(f"- {names[2]}: DB vacía + carpetas limpias + re-sync FRESCO con código v6.0.1")
    print()

    # Tabla 1: conteos base
    print("## Conteos\n")
    print("| Métrica | " + " | ".join(names) + " | Δ fresh vs baseline |")
    print("|---|" + "---:|" * (len(names) + 1))
    for key in ["cases", "documents", "emails"]:
        vals = [d["counts"][key] for d in data]
        print(f"| {key} | {vals[0]} | {vals[1]} | {vals[2]} | {delta(vals[0], vals[2])} |")

    print()
    print("## Email status distribution\n")
    statuses = sorted(set().union(*(d["email_status"].keys() for d in data)))
    print("| status | " + " | ".join(names) + " |")
    print("|---|" + "---:|" * len(names))
    for s in statuses:
        vals = [d["email_status"].get(s, 0) for d in data]
        print(f"| {s} | {vals[0]} | {vals[1]} | {vals[2]} |")

    print()
    print("## Match confidence distribution\n")
    confidences = ["NULL", "NONE", "LOW", "MEDIUM", "HIGH", "NEW_CASE"]
    print("| confidence | " + " | ".join(names) + " |")
    print("|---|" + "---:|" * len(names))
    for c in confidences:
        vals = [d["match_confidence"].get(c, 0) for d in data]
        if any(vals):
            print(f"| {c} | {vals[0]} | {vals[1]} | {vals[2]} |")

    print()
    print("## Métricas clave\n")
    print("| métrica | " + " | ".join(names) + " |")
    print("|---|" + "---:|" * len(names))
    for key, label in [
        ("coverage_pct", "Cobertura (% ASIGNADO)"),
        ("orphan_emails", "Emails huérfanos (case_id NULL)"),
    ]:
        vals = [d[key] for d in data]
        print(f"| {label} | {vals[0]} | {vals[1]} | {vals[2]} |")
    for key, label in [
        ("avg", "Score promedio"),
        ("min", "Score mínimo"),
        ("max", "Score máximo"),
    ]:
        vals = [d["score_stats"][key] for d in data]
        vals = [v if v is not None else "-" for v in vals]
        print(f"| {label} | {vals[0]} | {vals[1]} | {vals[2]} |")

    print()
    print("## Calidad de casos\n")
    print("| métrica | " + " | ".join(names) + " |")
    print("|---|" + "---:|" * len(names))
    for key, label in [
        ("without_rad23", "Casos sin rad23"),
        ("without_forest", "Casos sin forest"),
        ("without_accionante", "Casos sin accionante"),
    ]:
        vals = [d["cases_quality"][key] for d in data]
        print(f"| {label} | {vals[0]} | {vals[1]} | {vals[2]} |")

    print()
    print("## Resumen ejecutivo\n")
    pre = data[0]; retro = data[1]; fresh = data[2]
    print(f"- **Coverage**: {pre['coverage_pct']:.1f}% → {retro['coverage_pct']:.1f}% (retro) → **{fresh['coverage_pct']:.1f}%** (fresh)")
    print(f"- **Quarantine (AMBIGUO)**: {pre['email_status'].get('AMBIGUO',0)} → {retro['email_status'].get('AMBIGUO',0)} → **{fresh['email_status'].get('AMBIGUO',0)}**")
    print(f"- **Huérfanos**: {pre['orphan_emails']} → {retro['orphan_emails']} → **{fresh['orphan_emails']}**")
    print(f"- **HIGH-confidence matches**: {pre['match_confidence'].get('HIGH',0)} → {retro['match_confidence'].get('HIGH',0)} → **{fresh['match_confidence'].get('HIGH',0)}**")
    print(f"- **Score promedio**: {pre['score_stats']['avg']} → {retro['score_stats']['avg']} → **{fresh['score_stats']['avg']}**")


if __name__ == "__main__":
    main()
