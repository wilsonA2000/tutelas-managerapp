"""Benchmark v4.7 — agregaciones de metricas sobre TokenUsage + AuditLog + Case.

Funciones puras (sin side-effects) consumidas por:
- Endpoint GET /api/metrics/comparison (backend/routers/extraction.py)
- Script CLI scripts/benchmark_v47.py

Reusa TokenUsage (costos/latencia/errores) y Case.CSV_FIELD_MAP (cobertura).
NO crea tablas nuevas. NO modifica datos.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from backend.database.models import Case, TokenUsage, AuditLog


# Campos principales a medir para cobertura (subset de CSV_FIELD_MAP)
TRACKED_FIELDS = [
    "radicado_23_digitos",
    "radicado_forest",
    "accionante",
    "accionados",
    "juzgado",
    "ciudad",
    "derecho_vulnerado",
    "fecha_ingreso",
    "asunto",
    "pretensiones",
    "oficina_responsable",
    "estado",
    "sentido_fallo_1st",
    "fecha_fallo_1st",
    "impugnacion",
    "incidente",
    "observaciones",
    "abogado_responsable",
]


def _percentile(values: list[int], p: float) -> float:
    """p50/p95/p99 sobre lista de enteros."""
    if not values:
        return 0.0
    values = sorted(values)
    k = (len(values) - 1) * p
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return float(values[f])
    return values[f] + (values[c] - values[f]) * (k - f)


def compute_period_metrics(
    db: Session,
    since: datetime | None = None,
    until: datetime | None = None,
    provider: str | None = None,
    version_tag: str = "v4.7",
) -> dict[str, Any]:
    """Agregaciones sobre TokenUsage + Case en un rango de fechas.

    Args:
        db: Sesion SQLAlchemy
        since: Inicio del rango (None = sin limite inferior)
        until: Fin del rango (None = ahora)
        provider: Filtrar por provider especifico ('deepseek', 'anthropic', etc)
        version_tag: Etiqueta informativa para el reporte

    Returns:
        Dict con cost, latency, coverage, errors, providers_used, projection_1000
    """
    if until is None:
        until = datetime.now(timezone.utc).replace(tzinfo=None)

    # Query base sobre TokenUsage en el rango
    q = db.query(TokenUsage)
    if since is not None:
        q = q.filter(TokenUsage.timestamp >= since)
    if until is not None:
        q = q.filter(TokenUsage.timestamp <= until)
    if provider:
        q = q.filter(TokenUsage.provider == provider)

    usage_rows = q.all()

    # --- COSTOS ---
    total_cost = 0.0
    cost_by_provider: dict[str, float] = {}
    calls_by_provider: dict[str, int] = {}
    tokens_in_total = 0
    tokens_out_total = 0

    for r in usage_rows:
        try:
            c = float(r.cost_total or 0)
        except (TypeError, ValueError):
            c = 0.0
        total_cost += c
        key = f"{r.provider}/{r.model}"
        cost_by_provider[key] = cost_by_provider.get(key, 0.0) + c
        calls_by_provider[key] = calls_by_provider.get(key, 0) + 1
        tokens_in_total += r.tokens_input or 0
        tokens_out_total += r.tokens_output or 0

    # Casos unicos tocados en el rango
    case_ids_in_range = {r.case_id for r in usage_rows if r.case_id is not None}
    n_cases = len(case_ids_in_range)
    cost_per_case = (total_cost / n_cases) if n_cases else 0.0

    # --- LATENCIA ---
    durations_ms = [r.duration_ms or 0 for r in usage_rows if r.duration_ms]
    latency = {
        "p50_s": round(_percentile(durations_ms, 0.50) / 1000.0, 2),
        "p95_s": round(_percentile(durations_ms, 0.95) / 1000.0, 2),
        "avg_s": round(sum(durations_ms) / len(durations_ms) / 1000.0, 2) if durations_ms else 0.0,
        "max_s": round(max(durations_ms) / 1000.0, 2) if durations_ms else 0.0,
    }

    # --- ERRORES ---
    errors_total = sum(1 for r in usage_rows if r.error)
    errors_by_provider: dict[str, int] = {}
    rate_limit_events = 0
    for r in usage_rows:
        if r.error:
            key = f"{r.provider}/{r.model}"
            errors_by_provider[key] = errors_by_provider.get(key, 0) + 1
            err_lower = (r.error or "").lower()
            if "429" in err_lower or "rate" in err_lower or "limit" in err_lower:
                rate_limit_events += 1

    error_rate = (errors_total / len(usage_rows) * 100) if usage_rows else 0.0

    # --- COBERTURA POR CAMPO ---
    # Sobre los casos tocados en el rango (unicos, COMPLETO)
    coverage: dict[str, float] = {}
    avg_fields_per_case = 0.0
    cases_in_range = []

    if case_ids_in_range:
        cases_in_range = (
            db.query(Case)
            .filter(Case.id.in_(case_ids_in_range))
            .all()
        )
        for field in TRACKED_FIELDS:
            filled = sum(
                1 for c in cases_in_range
                if getattr(c, field, None) and str(getattr(c, field)).strip()
            )
            coverage[field] = round(filled / len(cases_in_range) * 100, 1) if cases_in_range else 0.0

        field_counts = [
            sum(1 for f in TRACKED_FIELDS if getattr(c, f, None) and str(getattr(c, f)).strip())
            for c in cases_in_range
        ]
        avg_fields_per_case = round(sum(field_counts) / len(field_counts), 1) if field_counts else 0.0

    # --- CASOS PROBLEMATICOS (fields_count < 5) ---
    problematic_cases = []
    if cases_in_range:
        for c in cases_in_range:
            fc = sum(1 for f in TRACKED_FIELDS if getattr(c, f, None) and str(getattr(c, f)).strip())
            if fc < 5:
                problematic_cases.append({
                    "id": c.id,
                    "folder_name": c.folder_name,
                    "fields_count": fc,
                    "status": c.processing_status,
                })

    # --- PROYECCION ESCALABLE (1000 casos) ---
    projection_1000 = {
        "cost_usd": round(cost_per_case * 1000, 2),
        "time_hours": round(latency["avg_s"] * 1000 / 3600, 1) if latency["avg_s"] else 0.0,
        "tokens_input_m": round(tokens_in_total / max(n_cases, 1) * 1000 / 1_000_000, 2),
        "tokens_output_m": round(tokens_out_total / max(n_cases, 1) * 1000 / 1_000_000, 2),
    }

    # --- PROVIDERS USADOS ---
    providers_used = [
        {
            "provider_model": pm,
            "calls": calls_by_provider[pm],
            "cost_usd": round(cost_by_provider.get(pm, 0), 4),
        }
        for pm in sorted(calls_by_provider, key=lambda k: -calls_by_provider[k])
    ]

    return {
        "version_tag": version_tag,
        "period": {
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
        },
        "universe": {
            "cases_touched": n_cases,
            "ai_calls": len(usage_rows),
            "tokens_input": tokens_in_total,
            "tokens_output": tokens_out_total,
        },
        "cost": {
            "total_usd": round(total_cost, 4),
            "per_case_avg_usd": round(cost_per_case, 6),
            "by_provider": {k: round(v, 4) for k, v in cost_by_provider.items()},
        },
        "latency": latency,
        "coverage": {
            "by_field": coverage,
            "avg_fields_per_case": avg_fields_per_case,
        },
        "errors": {
            "total": errors_total,
            "rate_pct": round(error_rate, 2),
            "rate_limit_events": rate_limit_events,
            "by_provider": errors_by_provider,
        },
        "providers_used": providers_used,
        "problematic_cases": problematic_cases,
        "projection_1000_cases": projection_1000,
    }


def render_markdown_report(metrics: dict[str, Any]) -> str:
    """Renderizar el dict de metricas como tabla markdown lista para pegar."""
    lines: list[str] = []
    lines.append(f"# Benchmark {metrics.get('version_tag', '?')}")
    lines.append("")
    period = metrics.get("period", {})
    lines.append(f"**Rango:** {period.get('since') or 'inicio'} → {period.get('until') or 'ahora'}")
    universe = metrics.get("universe", {})
    lines.append(f"**Casos tocados:** {universe.get('cases_touched', 0)}")
    lines.append(f"**Llamadas IA:** {universe.get('ai_calls', 0)}")
    lines.append("")

    lines.append("## Costos")
    cost = metrics.get("cost", {})
    lines.append(f"- **Total:** ${cost.get('total_usd', 0)} USD")
    lines.append(f"- **Por caso:** ${cost.get('per_case_avg_usd', 0)} USD")
    lines.append("- **Por provider:**")
    for k, v in (cost.get("by_provider") or {}).items():
        lines.append(f"  - {k}: ${v}")
    lines.append("")

    lines.append("## Latencia")
    lat = metrics.get("latency", {})
    lines.append(f"- p50: {lat.get('p50_s', 0)}s")
    lines.append(f"- p95: {lat.get('p95_s', 0)}s")
    lines.append(f"- avg: {lat.get('avg_s', 0)}s")
    lines.append(f"- max: {lat.get('max_s', 0)}s")
    lines.append("")

    lines.append("## Cobertura por campo")
    cov = (metrics.get("coverage") or {}).get("by_field", {})
    lines.append(f"- **Promedio de campos por caso:** {metrics.get('coverage', {}).get('avg_fields_per_case', 0)}")
    lines.append("")
    lines.append("| Campo | Cobertura |")
    lines.append("|---|---|")
    for field, pct in sorted(cov.items(), key=lambda x: -x[1]):
        lines.append(f"| {field} | {pct}% |")
    lines.append("")

    lines.append("## Errores")
    err = metrics.get("errors", {})
    lines.append(f"- Total: {err.get('total', 0)}")
    lines.append(f"- Rate: {err.get('rate_pct', 0)}%")
    lines.append(f"- Rate-limit events: {err.get('rate_limit_events', 0)}")
    lines.append("")

    lines.append("## Proyeccion 1000 casos")
    proj = metrics.get("projection_1000_cases", {})
    lines.append(f"- **Costo:** ${proj.get('cost_usd', 0)} USD")
    lines.append(f"- **Tiempo:** {proj.get('time_hours', 0)} horas")
    lines.append(f"- **Tokens input:** {proj.get('tokens_input_m', 0)}M")
    lines.append(f"- **Tokens output:** {proj.get('tokens_output_m', 0)}M")
    lines.append("")

    problematic = metrics.get("problematic_cases", [])
    if problematic:
        lines.append("## Casos problematicos (<5 campos)")
        lines.append("")
        lines.append("| ID | Folder | Campos | Status |")
        lines.append("|---|---|---|---|")
        for c in problematic[:20]:
            folder = (c.get("folder_name") or "")[:60]
            lines.append(f"| {c.get('id')} | {folder} | {c.get('fields_count')} | {c.get('status')} |")
        lines.append("")

    return "\n".join(lines)
