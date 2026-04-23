"""API de alertas proactivas."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.alerts.detector import run_detection, get_alerts, dismiss_alert, get_alert_counts, mark_alerts_seen
from backend.alerts.early_warning import run_early_warning, score_case, LEVEL_RED, LEVEL_YELLOW
from backend.database.models import Case

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("/")
def api_get_alerts(
    status: str | None = Query(None),
    severity: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return get_alerts(db, status=status, severity=severity, limit=limit)


@router.get("/counts")
def api_alert_counts(db: Session = Depends(get_db)):
    return get_alert_counts(db)


@router.post("/scan")
def api_scan_alerts(db: Session = Depends(get_db)):
    counts = run_detection(db)
    return {"message": "Escaneo completado", "alerts_created": counts}


@router.post("/mark-seen")
def api_mark_seen(db: Session = Depends(get_db)):
    count = mark_alerts_seen(db)
    return {"message": f"{count} alertas marcadas como vistas", "count": count}


@router.post("/{alert_id}/dismiss")
def api_dismiss(alert_id: int, db: Session = Depends(get_db)):
    dismiss_alert(db, alert_id)
    return {"message": "Alerta descartada"}


# =============================================================
# v6.0 Propuesta 9.4 — Early Warning System (semáforo institucional)
# =============================================================

@router.get("/early-warning")
def api_early_warning(
    level: str | None = Query(None, description="Filtrar por nivel: ROJO / AMARILLO / VERDE"),
    origen: str | None = Query(None, description="Filtrar por origen: TUTELA / INCIDENTE_HUERFANO / AMBIGUO"),
    db: Session = Depends(get_db),
):
    """Dashboard de alertas tempranas: semáforo de riesgo por caso.

    Retorna conteos por nivel (ROJO/AMARILLO/VERDE), lista ordenada de
    casos críticos con razones explícitas, y metadata operativa.
    """
    summary = run_early_warning(db)
    payload = summary.to_dict()
    if level:
        level = level.upper()
        if level == LEVEL_RED:
            payload["filtered"] = {"level": LEVEL_RED, "cases": payload["red"]}
        elif level == LEVEL_YELLOW:
            payload["filtered"] = {"level": LEVEL_YELLOW, "cases": payload["yellow"]}
        else:
            payload["filtered"] = {"level": level, "cases": []}
    if origen:
        origen = origen.upper()
        payload["red"] = [c for c in payload["red"] if c["origen"] == origen]
        payload["yellow"] = [c for c in payload["yellow"] if c["origen"] == origen]
    return payload


@router.get("/early-warning/{case_id}")
def api_early_warning_case(case_id: int, db: Session = Depends(get_db)):
    """Score detallado de un caso individual con razones."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return {"error": "caso no encontrado"}, 404
    return score_case(case).to_dict()
