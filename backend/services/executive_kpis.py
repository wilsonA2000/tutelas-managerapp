"""KPIs Ejecutivos — Propuesta 9.9 de la tesis v6.0.

Consolida indicadores operativos para la Secretaría de Educación de la
Gobernación de Santander. Usa datos que v6.0 ya produce (origen,
estado_incidente, entropy_score, fechas) más campos tradicionales.

Filosofía: cifras directamente accionables por el jefe de oficina jurídica
y el Secretario de Educación. Sin IA, sin estimaciones.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from backend.database.models import Case
from backend.alerts.early_warning import run_early_warning, LEVEL_RED, LEVEL_YELLOW


_RE_FECHA = re.compile(r"(\d{1,2})[/\-](\d{1,2})[/\-](20\d{2})")


def _parse(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    m = _RE_FECHA.search(s)
    if not m:
        return None
    try:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _ym(d: datetime) -> str:
    return f"{d.year}-{d.month:02d}"


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().upper()


# ============================================================
# KPIs individuales
# ============================================================

def compute_compliance_rate(cases: list[Case]) -> dict:
    """Tasa de cumplimiento: COMPLETO / (COMPLETO + REVISION + PENDIENTE)."""
    buckets: Counter[str] = Counter()
    for c in cases:
        s = c.processing_status or "PENDIENTE"
        if s == "DUPLICATE_MERGED":
            continue
        buckets[s] += 1
    total = sum(buckets.values())
    completo = buckets.get("COMPLETO", 0)
    rate = (completo / total) if total else 0.0
    return {
        "completo": completo,
        "revision": buckets.get("REVISION", 0),
        "pendiente": buckets.get("PENDIENTE", 0),
        "extrayendo": buckets.get("EXTRAYENDO", 0),
        "total_activos": total,
        "compliance_rate": round(rate, 3),
    }


def compute_response_times(cases: list[Case]) -> dict:
    """Tiempo promedio entre fecha_ingreso y fecha_respuesta."""
    deltas: list[int] = []
    sin_respuesta_con_fallo = 0
    sin_respuesta_count = 0
    for c in cases:
        ingreso = _parse(c.fecha_ingreso)
        resp = _parse(c.fecha_respuesta)
        fallo = _parse(c.fecha_fallo_1st)
        if ingreso and resp:
            delta = max(0, (resp - ingreso).days)
            if delta <= 365:
                deltas.append(delta)
        if ingreso and not resp:
            sin_respuesta_count += 1
            if fallo:
                sin_respuesta_con_fallo += 1
    if not deltas:
        avg = median = p75 = None
    else:
        sorted_d = sorted(deltas)
        n = len(sorted_d)
        avg = round(sum(sorted_d) / n, 1)
        median = sorted_d[n // 2]
        p75 = sorted_d[int(n * 0.75)]
    return {
        "avg_days": avg,
        "median_days": median,
        "p75_days": p75,
        "sample_size": len(deltas),
        "sin_respuesta_total": sin_respuesta_count,
        "sin_respuesta_con_fallo": sin_respuesta_con_fallo,
    }


def compute_fallos_distribution(cases: list[Case]) -> list[dict]:
    """Distribución de sentidos de fallo en 1ra instancia."""
    buckets: Counter[str] = Counter()
    for c in cases:
        s = _norm(c.sentido_fallo_1st)
        if not s or s in ("N/A", "NULL", "PENDIENTE"):
            continue
        # Normalizar a categorías canónicas
        if "CONCEDE" in s or "AMPARA" in s or "TUTELA" in s:
            buckets["CONCEDE"] += 1
        elif "NIEGA" in s or "DENIEG" in s:
            buckets["NIEGA"] += 1
        elif "IMPROCEDENTE" in s:
            buckets["IMPROCEDENTE"] += 1
        elif "MODIFICA" in s:
            buckets["MODIFICA"] += 1
        else:
            buckets["OTRO"] += 1
    total = sum(buckets.values())
    return [
        {"sentido": k, "count": v, "pct": round(100 * v / total, 1) if total else 0}
        for k, v in buckets.most_common()
    ]


def compute_by_month(cases: list[Case]) -> list[dict]:
    """Casos por mes de ingreso — tendencia temporal."""
    buckets: Counter[str] = Counter()
    for c in cases:
        d = _parse(c.fecha_ingreso)
        if d:
            buckets[_ym(d)] += 1
    sorted_keys = sorted(buckets.keys())
    return [{"month": k, "count": buckets[k]} for k in sorted_keys]


def compute_top_municipios(cases: list[Case], limit: int = 10) -> list[dict]:
    buckets: Counter[str] = Counter()
    for c in cases:
        ciudad = (c.ciudad or "").strip()
        if ciudad and ciudad.upper() not in ("", "N/A", "NULL"):
            buckets[ciudad] += 1
    return [
        {"municipio": k, "count": v}
        for k, v in buckets.most_common(limit)
    ]


def compute_top_oficinas(cases: list[Case], limit: int = 10) -> list[dict]:
    buckets: Counter[str] = Counter()
    for c in cases:
        o = (c.oficina_responsable or "").strip()
        if o and o.upper() not in ("", "N/A", "NULL"):
            buckets[o] += 1
    return [
        {"oficina": k, "count": v}
        for k, v in buckets.most_common(limit)
    ]


def compute_top_abogados(cases: list[Case], limit: int = 10) -> list[dict]:
    """Ranking por carga de trabajo del abogado responsable."""
    buckets: Counter[str] = Counter()
    active_cases: defaultdict[str, list[int]] = defaultdict(list)
    for c in cases:
        ab = (c.abogado_responsable or "").strip()
        if ab and ab.upper() not in ("", "N/A", "NULL", "SIN ABOGADO"):
            buckets[ab] += 1
            if (c.estado_incidente or "N/A") in ("ACTIVO", "EN_CONSULTA", "EN_SANCION"):
                active_cases[ab].append(c.id)
    return [
        {
            "abogado": k,
            "total_casos": v,
            "casos_activos_incidente": len(active_cases.get(k, [])),
        }
        for k, v in buckets.most_common(limit)
    ]


def compute_top_accionantes_recurrentes(cases: list[Case], limit: int = 10) -> list[dict]:
    """Top accionantes con más de un proceso abierto (posibles litigantes recurrentes)."""
    buckets: Counter[str] = Counter()
    for c in cases:
        a = (c.accionante or "").strip()
        if a and len(a) >= 10:
            # Normalizar para detectar duplicados con tildes/mayúsculas distintas
            norm = re.sub(r"\s+", " ", a.upper())[:80]
            buckets[norm] += 1
    return [
        {"accionante": k, "procesos": v}
        for k, v in buckets.most_common(limit)
        if v > 1  # solo si hay más de uno
    ]


def compute_by_origen(cases: list[Case]) -> dict:
    buckets: Counter[str] = Counter()
    for c in cases:
        o = c.origen or "SIN_CLASIFICAR"
        buckets[o] += 1
    return dict(buckets)


def compute_by_estado_incidente(cases: list[Case]) -> dict:
    buckets: Counter[str] = Counter()
    for c in cases:
        e = c.estado_incidente or "SIN_DATOS"
        buckets[e] += 1
    return dict(buckets)


def compute_fallo_2nd_distribution(cases: list[Case]) -> list[dict]:
    """v8.3: distribución sentido_fallo_2nd (segunda instancia)."""
    buckets: Counter[str] = Counter()
    for c in cases:
        s = _norm(c.sentido_fallo_2nd)
        if not s or s in ("N/A", "NULL", "PENDIENTE"):
            continue
        if "CONFIRMA" in s:
            buckets["CONFIRMA"] += 1
        elif "REVOCA" in s:
            buckets["REVOCA"] += 1
        elif "MODIFICA" in s:
            buckets["MODIFICA"] += 1
        elif "INHIBE" in s:
            buckets["INHIBE"] += 1
        elif "NULIDAD" in s:
            buckets["NULIDAD"] += 1
        else:
            buckets["OTRO"] += 1
    total = sum(buckets.values())
    return [
        {"sentido": k, "count": v, "pct": round(100 * v / total, 1) if total else 0}
        for k, v in buckets.most_common()
    ]


def compute_pipeline_funnel(cases: list[Case]) -> list[dict]:
    """v8.3: funnel ejecutivo de fallos (TUTELA → fallo_1ST → impugnado → fallo_2ND → incidente → cumplido).

    Metafora visual para el Secretario: cuántas tutelas ingresan vs cuántas terminan
    en sancion/cumplimiento. Cada nivel es un subset estricto del anterior.
    """
    total = len(cases)
    fallo_1 = sum(1 for c in cases if _norm(c.sentido_fallo_1st) and _norm(c.sentido_fallo_1st) not in ("N/A", "PENDIENTE"))
    impugnados = sum(1 for c in cases if _norm(c.impugnacion).startswith("S"))
    fallo_2 = sum(1 for c in cases if _norm(c.sentido_fallo_2nd) and _norm(c.sentido_fallo_2nd) not in ("N/A", "PENDIENTE"))
    incidente = sum(1 for c in cases if _norm(c.incidente).startswith("S"))
    cumplidos = sum(1 for c in cases if (c.estado_incidente or "").upper() == "CUMPLIDO")
    return [
        {"stage": "TUTELA", "label": "Tutelas activas", "count": total, "pct_total": 100.0},
        {"stage": "FALLO_1ST", "label": "Con fallo 1ª instancia", "count": fallo_1,
         "pct_total": round(100 * fallo_1 / total, 1) if total else 0},
        {"stage": "IMPUGNADO", "label": "Impugnadas", "count": impugnados,
         "pct_total": round(100 * impugnados / total, 1) if total else 0},
        {"stage": "FALLO_2ND", "label": "Con fallo 2ª instancia", "count": fallo_2,
         "pct_total": round(100 * fallo_2 / total, 1) if total else 0},
        {"stage": "INCIDENTE", "label": "Con incidente desacato", "count": incidente,
         "pct_total": round(100 * incidente / total, 1) if total else 0},
        {"stage": "CUMPLIDO", "label": "Cumplido / archivado", "count": cumplidos,
         "pct_total": round(100 * cumplidos / total, 1) if total else 0},
    ]


def compute_compliance_plazos(cases: list[Case], db_session=None) -> dict:
    """v8.3: plazos de cumplimiento de fallos CONCEDE.

    Detecta cases con fallo CONCEDE/AMPARA donde han pasado >5 días desde
    fecha_fallo_1st sin cumplimiento registrado (señal de riesgo de incidente
    de desacato). Reusa heurística de R8 EarlyWarning.
    """
    today = datetime.utcnow()
    concedidas_pendientes = []
    concedidas_a_tiempo = 0
    en_sancion = 0
    apercibimiento = 0

    for c in cases:
        senso = _norm(c.sentido_fallo_1st)
        if not ("CONCEDE" in senso or "AMPARA" in senso):
            continue
        fecha_fallo = _parse(c.fecha_fallo_1st)
        if not fecha_fallo:
            continue
        dias = (today - fecha_fallo).days
        estado = (c.estado_incidente or "").upper()
        if estado == "EN_SANCION":
            en_sancion += 1
            continue
        if estado == "CUMPLIDO":
            concedidas_a_tiempo += 1
            continue
        if dias > 10:
            concedidas_pendientes.append({
                "case_id": c.id,
                "folder_name": c.folder_name,
                "dias_desde_fallo": dias,
                "fecha_fallo": c.fecha_fallo_1st,
                "abogado": c.abogado_canonical or c.abogado_responsable,
            })

    return {
        "concedidas_pendientes_cumplimiento": len(concedidas_pendientes),
        "concedidas_cumplidas_a_tiempo": concedidas_a_tiempo,
        "en_sancion": en_sancion,
        "top_pendientes": sorted(concedidas_pendientes,
                                  key=lambda x: -x["dias_desde_fallo"])[:10],
    }


def compute_impugnacion_rate(cases: list[Case]) -> dict:
    con_fallo = [c for c in cases if _norm(c.sentido_fallo_1st)
                 and _norm(c.sentido_fallo_1st) not in ("N/A", "PENDIENTE")]
    impugnadas = [c for c in con_fallo if _norm(c.impugnacion).startswith("S")]
    concedidas = [c for c in con_fallo
                  if any(kw in _norm(c.sentido_fallo_1st) for kw in ("CONCEDE", "AMPARA"))]
    concedidas_impugnadas = [c for c in concedidas if _norm(c.impugnacion).startswith("S")]
    total = len(con_fallo)
    return {
        "total_con_fallo": total,
        "total_impugnadas": len(impugnadas),
        "impugnacion_rate": round(len(impugnadas) / total, 3) if total else 0,
        "concedidas": len(concedidas),
        "concedidas_impugnadas": len(concedidas_impugnadas),
        "rate_impugnacion_sobre_concedidas": (
            round(len(concedidas_impugnadas) / len(concedidas), 3) if concedidas else 0
        ),
    }


# ============================================================
# Entry point consolidado
# ============================================================

def executive_dashboard(db: Session) -> dict:
    """Consolida todos los KPIs ejecutivos en un único payload."""
    now = datetime.utcnow()

    # Tomar solo casos no fusionados
    all_cases = db.query(Case).filter(Case.processing_status != "DUPLICATE_MERGED").all()

    compliance = compute_compliance_rate(all_cases)
    response = compute_response_times(all_cases)
    fallos = compute_fallos_distribution(all_cases)
    fallos_2nd = compute_fallo_2nd_distribution(all_cases)
    pipeline = compute_pipeline_funnel(all_cases)
    plazos = compute_compliance_plazos(all_cases)
    by_month = compute_by_month(all_cases)
    top_municipios = compute_top_municipios(all_cases)
    top_oficinas = compute_top_oficinas(all_cases)
    top_abogados = compute_top_abogados(all_cases)
    top_accionantes = compute_top_accionantes_recurrentes(all_cases)
    by_origen = compute_by_origen(all_cases)
    by_estado_incidente = compute_by_estado_incidente(all_cases)
    impugnacion = compute_impugnacion_rate(all_cases)

    # Early warning integrado (reutiliza 9.4)
    ew = run_early_warning(db)

    # Casos críticos visibles
    casos_sancion = by_estado_incidente.get("EN_SANCION", 0)
    casos_activos_incidente = by_estado_incidente.get("ACTIVO", 0)

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "summary": {
            "total_cases": len(all_cases),
            "compliance_rate": compliance["compliance_rate"],
            "casos_criticos_rojos": ew.by_level.get(LEVEL_RED, 0),
            "casos_vigilancia_amarillos": ew.by_level.get(LEVEL_YELLOW, 0),
            "casos_en_sancion": casos_sancion,
            "casos_con_incidente_activo": casos_activos_incidente,
        },
        "compliance": compliance,
        "response_times": response,
        "impugnacion": impugnacion,
        "fallos_distribution": fallos,
        "fallos_2nd_distribution": fallos_2nd,
        "pipeline_funnel": pipeline,
        "compliance_plazos": plazos,
        "by_month": by_month,
        "by_origen": by_origen,
        "by_estado_incidente": by_estado_incidente,
        "top_municipios": top_municipios,
        "top_oficinas": top_oficinas,
        "top_abogados": top_abogados,
        "top_accionantes_recurrentes": top_accionantes,
    }
