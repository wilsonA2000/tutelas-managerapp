#!/usr/bin/env python3
"""Reporte semanal de alertas tempranas.

Genera un markdown listo para copiar/pegar al email del equipo jurídico
con los casos en ROJO y AMARILLO, ordenados por prioridad.

Uso:
    python3 scripts/weekly_alerts_report.py                  # stdout
    python3 scripts/weekly_alerts_report.py --out reporte.md # a archivo
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database.database import SessionLocal
from backend.alerts.early_warning import run_early_warning


def _render_case(c: dict) -> str:
    rows = [f"### Caso #{c['case_id']} · {c['folder_name']}"]
    badges = [f"**{c['level']}**", f"score **{c['score']:.2f}**", f"`{c['origen']}`"]
    if c['estado_incidente'] != 'N/A':
        badges.append(f"`{c['estado_incidente']}`")
    if c.get('abogado_responsable'):
        badges.append(f"abogado: {c['abogado_responsable']}")
    rows.append(" · ".join(badges))
    rows.append("")
    rows.append("Razones:")
    for r in c['reasons']:
        rows.append(f"- {r}")
    rows.append("")
    if c.get('days_since_incidente'):
        rows.append(f"_Incidente abierto hace {c['days_since_incidente']} días._")
    rows.append("")
    return "\n".join(rows)


def render_report(summary_dict: dict) -> str:
    now = datetime.now().strftime("%d de %B de %Y")
    rojos = summary_dict['by_level'].get('ROJO', 0)
    amarillos = summary_dict['by_level'].get('AMARILLO', 0)
    verdes = summary_dict['by_level'].get('VERDE', 0)
    total = summary_dict['total_cases_evaluated']

    out = [
        f"# Reporte Semanal de Alertas — {now}",
        "",
        f"_Sistema Tutelas Manager v6.0 · Módulo Early Warning_",
        "",
        "## Resumen ejecutivo",
        "",
        f"- **{rojos}** casos en situación **CRÍTICA** (requieren intervención jurídica inmediata)",
        f"- **{amarillos}** casos en **VIGILANCIA** (revisar próximos días)",
        f"- **{verdes}** casos **EN REGLA**",
        f"- Total evaluados: {total}",
        "",
    ]

    if rojos > 0:
        out.extend([
            "## 🔴 Casos críticos (ROJO)",
            "",
            f"_{rojos} casos requieren acción jurídica inmediata._",
            "",
        ])
        for c in summary_dict['red']:
            out.append(_render_case(c))
            out.append("---")
            out.append("")

    if amarillos > 0:
        out.extend([
            "## 🟡 Casos en vigilancia (AMARILLO)",
            "",
            f"_{amarillos} casos a monitorear._",
            "",
        ])
        for c in summary_dict['yellow']:
            out.append(_render_case(c))
            out.append("---")
            out.append("")

    out.extend([
        "## Metodología",
        "",
        "Este reporte se genera automáticamente por el módulo Early Warning del",
        "sistema Tutelas Manager v6.0. Las reglas son deterministas:",
        "",
        "- **ROJO**: EN_SANCION, o incidente activo >20 días, o fallo CONCEDE",
        "  sin respuesta >10 días.",
        "- **AMARILLO**: incidente activo 10-20 días, fallo CONCEDE sin respuesta",
        "  5-10 días, entropía alta (>2.2 bits), huérfano sin consolidar.",
        "- **VERDE**: sin alertas activas.",
        "",
        "Cada caso puede consultarse en el frontend:",
        "  http://localhost:5174/alertas",
        "",
        f"_Generado: {summary_dict['generated_at']}_",
    ])

    return "\n".join(out)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, help="Escribir a archivo")
    args = p.parse_args()

    db = SessionLocal()
    try:
        summary = run_early_warning(db)
        md = render_report(summary.to_dict())

        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(md, encoding="utf-8")
            print(f"Reporte escrito: {args.out} ({len(md):,} chars)")
        else:
            print(md)
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
