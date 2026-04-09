#!/usr/bin/env python3
"""Benchmark v4.7 — CLI reusable para generar reportes comparativos.

Uso:
    # Reporte markdown de las ultimas 24h
    python scripts/benchmark_v47.py

    # Reporte JSON de un rango especifico
    python scripts/benchmark_v47.py --since 2026-04-09 --until 2026-04-10 --output json

    # Reporte CSV para Excel
    python scripts/benchmark_v47.py --output csv > benchmark.csv

    # Filtrar por provider
    python scripts/benchmark_v47.py --provider deepseek

Ejecuta desde la raiz del proyecto (tutelas-app/).
Reusa backend/reports/benchmark.py (logica pura, compartida con el endpoint).
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Asegurar que tutelas-app/ esta en el path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal  # noqa: E402
from backend.reports.benchmark import (  # noqa: E402
    compute_period_metrics,
    render_markdown_report,
)


def render_csv(metrics: dict) -> str:
    """Renderizar metricas como CSV (1 fila = 1 metrica)."""
    lines = ["metric,value"]
    cost = metrics.get("cost", {})
    lines.append(f"cost_total_usd,{cost.get('total_usd', 0)}")
    lines.append(f"cost_per_case_usd,{cost.get('per_case_avg_usd', 0)}")
    lat = metrics.get("latency", {})
    lines.append(f"latency_p50_s,{lat.get('p50_s', 0)}")
    lines.append(f"latency_p95_s,{lat.get('p95_s', 0)}")
    lines.append(f"latency_avg_s,{lat.get('avg_s', 0)}")
    lines.append(f"latency_max_s,{lat.get('max_s', 0)}")
    cov = metrics.get("coverage", {})
    lines.append(f"avg_fields_per_case,{cov.get('avg_fields_per_case', 0)}")
    err = metrics.get("errors", {})
    lines.append(f"errors_total,{err.get('total', 0)}")
    lines.append(f"errors_rate_pct,{err.get('rate_pct', 0)}")
    lines.append(f"rate_limit_events,{err.get('rate_limit_events', 0)}")
    proj = metrics.get("projection_1000_cases", {})
    lines.append(f"projection_1000_cost_usd,{proj.get('cost_usd', 0)}")
    lines.append(f"projection_1000_hours,{proj.get('time_hours', 0)}")
    universe = metrics.get("universe", {})
    lines.append(f"cases_touched,{universe.get('cases_touched', 0)}")
    lines.append(f"ai_calls,{universe.get('ai_calls', 0)}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark v4.7 — reporte comparativo de TokenUsage + Case"
    )
    parser.add_argument(
        "--since",
        help="Inicio del rango (ISO: 2026-04-09 o 2026-04-09T11:00:00). Default: -24h",
    )
    parser.add_argument(
        "--until",
        help="Fin del rango (ISO). Default: ahora",
    )
    parser.add_argument(
        "--provider",
        help="Filtrar por provider ('deepseek', 'anthropic', 'google', etc)",
    )
    parser.add_argument(
        "--version-tag",
        default="v4.7",
        help="Etiqueta del reporte (default: v4.7)",
    )
    parser.add_argument(
        "--output",
        choices=["json", "md", "csv"],
        default="md",
        help="Formato de salida (default: md)",
    )
    args = parser.parse_args()

    def _parse(s: str | None, default: datetime) -> datetime:
        if not s:
            return default
        try:
            # Acepta tanto '2026-04-09' como '2026-04-09T11:00:00'
            if "T" not in s:
                s = s + "T00:00:00"
            return datetime.fromisoformat(s)
        except ValueError:
            print(f"ERROR: fecha invalida '{s}'. Use ISO format.", file=sys.stderr)
            sys.exit(1)

    now = datetime.utcnow()
    since_dt = _parse(args.since, now - timedelta(hours=24))
    until_dt = _parse(args.until, now)

    with SessionLocal() as db:
        metrics = compute_period_metrics(
            db=db,
            since=since_dt,
            until=until_dt,
            provider=args.provider,
            version_tag=args.version_tag,
        )

    if args.output == "json":
        print(json.dumps(metrics, indent=2, default=str))
    elif args.output == "csv":
        print(render_csv(metrics))
    else:
        print(render_markdown_report(metrics))


if __name__ == "__main__":
    main()
