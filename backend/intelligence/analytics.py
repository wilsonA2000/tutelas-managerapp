"""Analytics de inteligencia legal: tendencias, predicciones, estadísticas avanzadas."""

import logging
from collections import Counter, defaultdict
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.database.models import Case

logger = logging.getLogger("tutelas.intelligence")


def get_favorability_by_juzgado(db: Session) -> list[dict]:
    """Tasa de favorabilidad (NIEGA/IMPROCEDENTE) por juzgado."""
    cases = db.query(Case).filter(
        Case.juzgado.isnot(None), Case.juzgado != "",
        Case.sentido_fallo_1st.isnot(None), Case.sentido_fallo_1st != "",
    ).all()

    by_juzgado = defaultdict(lambda: {"total": 0, "favorable": 0, "desfavorable": 0})
    for c in cases:
        juz = (c.juzgado or "").strip()[:80]
        fallo = (c.sentido_fallo_1st or "").upper()
        by_juzgado[juz]["total"] += 1
        if fallo in ("NIEGA", "IMPROCEDENTE"):
            by_juzgado[juz]["favorable"] += 1
        elif fallo in ("CONCEDE", "CONCEDE PARCIALMENTE"):
            by_juzgado[juz]["desfavorable"] += 1

    result = []
    for juz, stats in sorted(by_juzgado.items(), key=lambda x: x[1]["total"], reverse=True):
        rate = (stats["favorable"] / stats["total"] * 100) if stats["total"] > 0 else 0
        result.append({
            "juzgado": juz,
            "total": stats["total"],
            "favorable": stats["favorable"],
            "desfavorable": stats["desfavorable"],
            "tasa_favorabilidad": round(rate, 1),
        })
    return result[:20]


def get_appeal_analysis(db: Session) -> dict:
    """Análisis de impugnaciones: éxito por tipo."""
    cases = db.query(Case).filter(Case.impugnacion == "SI").all()

    total = len(cases)
    by_result = Counter()
    by_who = Counter()

    for c in cases:
        fallo_2 = (c.sentido_fallo_2nd or "").upper()
        who = (c.quien_impugno or "N/A")
        if fallo_2:
            by_result[fallo_2] += 1
        by_who[who] += 1

    return {
        "total_impugnaciones": total,
        "resueltas": sum(by_result.values()),
        "pendientes": total - sum(by_result.values()),
        "by_result": dict(by_result),
        "by_impugnante": dict(by_who),
        "tasa_revocacion": round(by_result.get("REVOCA", 0) / max(sum(by_result.values()), 1) * 100, 1),
    }


def get_lawyer_performance(db: Session) -> list[dict]:
    """Rendimiento por abogado: casos asignados, completitud, favorabilidad."""
    cases = db.query(Case).filter(
        Case.abogado_responsable.isnot(None), Case.abogado_responsable != "",
    ).all()

    by_lawyer = defaultdict(lambda: {"total": 0, "favorable": 0, "with_fallo": 0, "active": 0})
    for c in cases:
        lawyer = (c.abogado_responsable or "").strip()
        by_lawyer[lawyer]["total"] += 1
        if c.estado == "ACTIVO":
            by_lawyer[lawyer]["active"] += 1
        fallo = (c.sentido_fallo_1st or "").upper()
        if fallo:
            by_lawyer[lawyer]["with_fallo"] += 1
            if fallo in ("NIEGA", "IMPROCEDENTE"):
                by_lawyer[lawyer]["favorable"] += 1

    result = []
    for lawyer, stats in sorted(by_lawyer.items(), key=lambda x: x[1]["total"], reverse=True):
        rate = (stats["favorable"] / max(stats["with_fallo"], 1)) * 100
        result.append({
            "abogado": lawyer,
            "total_casos": stats["total"],
            "activos": stats["active"],
            "con_fallo": stats["with_fallo"],
            "favorables": stats["favorable"],
            "tasa_favorabilidad": round(rate, 1),
        })
    return result


def get_monthly_trends(db: Session) -> list[dict]:
    """Tendencia mensual de tutelas ingresadas."""
    cases = db.query(Case).filter(
        Case.fecha_ingreso.isnot(None), Case.fecha_ingreso != "",
    ).all()

    by_month = Counter()
    for c in cases:
        fecha = c.fecha_ingreso or ""
        # Try DD/MM/YYYY format
        parts = fecha.split("/")
        if len(parts) == 3:
            month_key = f"{parts[2]}-{parts[1]}"  # YYYY-MM
            by_month[month_key] += 1

    return [
        {"month": k, "count": v}
        for k, v in sorted(by_month.items())
    ]


def get_rights_analysis(db: Session) -> list[dict]:
    """Análisis de derechos vulnerados más frecuentes."""
    cases = db.query(Case).filter(
        Case.derecho_vulnerado.isnot(None), Case.derecho_vulnerado != "",
    ).all()

    rights = Counter()
    for c in cases:
        for r in (c.derecho_vulnerado or "").split(" - "):
            r = r.strip().upper()
            if r and len(r) > 2:
                rights[r] += 1

    return [
        {"derecho": r, "count": c}
        for r, c in rights.most_common(15)
    ]


def predict_outcome(db: Session, juzgado: str = "", derecho: str = "", ciudad: str = "") -> dict:
    """Predicción simple basada en datos históricos."""
    q = db.query(Case).filter(
        Case.sentido_fallo_1st.isnot(None), Case.sentido_fallo_1st != "",
    )
    if juzgado:
        q = q.filter(Case.juzgado.contains(juzgado))
    if derecho:
        q = q.filter(Case.derecho_vulnerado.contains(derecho))
    if ciudad:
        q = q.filter(Case.ciudad.contains(ciudad))

    cases = q.all()
    total = len(cases)
    if total < 3:
        return {"prediction": "INSUFICIENTE", "confidence": 0, "sample_size": total,
                "message": "Menos de 3 casos similares para predecir"}

    fallos = Counter((c.sentido_fallo_1st or "").upper() for c in cases)
    most_common = fallos.most_common(1)[0]
    confidence = round(most_common[1] / total * 100, 1)

    return {
        "prediction": most_common[0],
        "confidence": confidence,
        "sample_size": total,
        "breakdown": dict(fallos),
        "message": f"Basado en {total} casos similares, {confidence}% terminaron en {most_common[0]}",
    }
