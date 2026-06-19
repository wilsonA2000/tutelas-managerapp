"""Router REST de la API CPNU (Rama Judicial) — operador-facing (Fase E).

Permite, desde la ficha de un caso:
  GET  /api/rama-judicial/preview/{case_id}     — consulta CPNU (read-only), devuelve
       proceso + actuaciones reales. Cachea en RamaJudicialSync.
  POST /api/rama-judicial/fetch-docs/{case_id}  — descarga el expediente (documentos
       de las actuaciones) al folder del caso (dry_run opcional).

Todos requieren auth. Pegan la API pública de la Rama Judicial — usar con criterio
(rate-limit por IP en ráfagas).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.auth.dependencies import require_auth
from backend.auth.models import User
from backend.database.database import get_db
from backend.database.models import Case
from backend.email.rad_utils import normalize_rad23, is_valid_rad23
from backend.services import rama_judicial_client as rj

logger = logging.getLogger("tutelas.rama_judicial.router")

router = APIRouter(prefix="/api/rama-judicial", tags=["rama-judicial"])


@router.get("/preview/{case_id}")
def preview(case_id: int, db: Session = Depends(get_db), user: User = Depends(require_auth)):
    """Consulta CPNU por el rad23 del caso y devuelve proceso + actuaciones (no escribe
    en el cuadro; sí cachea la respuesta en RamaJudicialSync)."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    rad = normalize_rad23(case.radicado_23_digitos)
    if not is_valid_rad23(rad):
        return {"case_id": case_id, "rad23": rad, "encontrado": False,
                "error": "El caso no tiene un radicado de 23 dígitos consultable"}
    try:
        from backend.v9.rama_judicial_enrich import _get_or_sync
        data = _get_or_sync(db, case, rad)  # usa/actualiza cache
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"CPNU no respondió: {str(e)[:150]}")
    if not data:
        raise HTTPException(status_code=502, detail="CPNU no respondió")
    return {"case_id": case_id, **data}


@router.post("/fetch-docs/{case_id}")
def fetch_docs(case_id: int, dry_run: bool = Query(True),
               db: Session = Depends(get_db), user: User = Depends(require_auth)):
    """Descarga los documentos del expediente CPNU al folder del caso. dry_run=True
    (default) solo lista lo que bajaría."""
    from backend.services.rama_judicial_fetcher import fetch_case_documents
    try:
        return fetch_case_documents(db, case_id, dry_run=dry_run, throttle=1.0)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Descarga falló: {str(e)[:150]}")
