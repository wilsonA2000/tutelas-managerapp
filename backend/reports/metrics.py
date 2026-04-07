"""Calculos de metricas para reportes."""

from datetime import datetime


def _parse_date(date_str: str) -> datetime | None:
    """Parsear fecha en formato DD/MM/YYYY."""
    if not date_str:
        return None
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def calculate_metrics(cases: list) -> dict:
    """Calcular metricas completas para reportes."""
    total = len(cases)
    if total == 0:
        return {"total": 0}

    activos = sum(1 for c in cases if (c.estado or "").upper() == "ACTIVO")
    inactivos = sum(1 for c in cases if (c.estado or "").upper() == "INACTIVO")

    # Tiempos de respuesta
    response_times = []
    for c in cases:
        ingreso = _parse_date(c.fecha_ingreso or "")
        respuesta = _parse_date(c.fecha_respuesta or "")
        if ingreso and respuesta:
            delta = (respuesta - ingreso).days
            if 0 <= delta <= 365:
                response_times.append(delta)

    avg_response = round(sum(response_times) / len(response_times), 1) if response_times else None

    # Fallos
    fallos = {}
    for c in cases:
        f = (c.sentido_fallo_1st or "").strip().upper()
        if f:
            key = f if f in ("CONCEDE", "NIEGA", "IMPROCEDENTE") else "OTRO"
            fallos[key] = fallos.get(key, 0) + 1

    # Completitud por campo
    field_completitud = {}
    for csv_col, attr in type(cases[0]).CSV_FIELD_MAP.items():
        filled = sum(1 for c in cases if getattr(c, attr))
        field_completitud[csv_col] = round(filled / total * 100, 1)

    # Casos por mes
    monthly = {}
    for c in cases:
        d = _parse_date(c.fecha_ingreso or "")
        if d:
            key = d.strftime("%Y-%m")
            monthly[key] = monthly.get(key, 0) + 1

    # Carga por abogado
    lawyer_load = {}
    for c in cases:
        lawyer = (c.abogado_responsable or "").strip()
        if lawyer:
            lawyer_load[lawyer] = lawyer_load.get(lawyer, 0) + 1

    return {
        "total": total,
        "activos": activos,
        "inactivos": inactivos,
        "sin_estado": total - activos - inactivos,
        "avg_response_days": avg_response,
        "min_response_days": min(response_times) if response_times else None,
        "max_response_days": max(response_times) if response_times else None,
        "fallos": fallos,
        "field_completitud": field_completitud,
        "monthly_trend": dict(sorted(monthly.items())),
        "lawyer_workload": dict(sorted(lawyer_load.items(), key=lambda x: -x[1])[:15]),
    }
