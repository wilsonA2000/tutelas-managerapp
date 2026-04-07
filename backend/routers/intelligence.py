"""API de Inteligencia Legal: analytics, predicciones, plazos."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.intelligence.analytics import (
    get_favorability_by_juzgado, get_appeal_analysis,
    get_lawyer_performance, get_monthly_trends,
    get_rights_analysis, predict_outcome,
)
from backend.intelligence.deadlines import get_calendar_events, get_deadline_summary

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


@router.get("/favorability")
def api_favorability(db: Session = Depends(get_db)):
    """Tasa de favorabilidad por juzgado."""
    return get_favorability_by_juzgado(db)


@router.get("/appeals")
def api_appeals(db: Session = Depends(get_db)):
    """Análisis de impugnaciones."""
    return get_appeal_analysis(db)


@router.get("/lawyers")
def api_lawyers(db: Session = Depends(get_db)):
    """Rendimiento por abogado."""
    return get_lawyer_performance(db)


@router.get("/trends")
def api_trends(db: Session = Depends(get_db)):
    """Tendencia mensual."""
    return get_monthly_trends(db)


@router.get("/rights")
def api_rights(db: Session = Depends(get_db)):
    """Derechos vulnerados más frecuentes."""
    return get_rights_analysis(db)


@router.get("/predict")
def api_predict(
    juzgado: str = Query("", description="Nombre parcial del juzgado"),
    derecho: str = Query("", description="Derecho vulnerado"),
    ciudad: str = Query("", description="Ciudad/municipio"),
    db: Session = Depends(get_db),
):
    """Predicción de resultado basada en datos históricos."""
    return predict_outcome(db, juzgado=juzgado, derecho=derecho, ciudad=ciudad)


@router.get("/calendar")
def api_calendar(db: Session = Depends(get_db)):
    """Eventos de calendario con plazos."""
    return get_calendar_events(db)


@router.get("/deadlines")
def api_deadlines(db: Session = Depends(get_db)):
    """Resumen de plazos para dashboard."""
    return get_deadline_summary(db)
