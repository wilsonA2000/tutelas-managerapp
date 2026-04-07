"""API de alertas proactivas."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.alerts.detector import run_detection, get_alerts, dismiss_alert, get_alert_counts

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


@router.post("/{alert_id}/dismiss")
def api_dismiss(alert_id: int, db: Session = Depends(get_db)):
    dismiss_alert(db, alert_id)
    return {"message": "Alerta descartada"}
