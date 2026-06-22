"""Router REST del pipeline v9.

Expone el pipeline simplificado al frontend y a herramientas externas
(curl, Postman, scripts). Todos los endpoints requieren autenticación.

Endpoints:
    GET  /api/v9/preview/{case_id}    — extracción dry-run, no escribe a DB
    POST /api/v9/extract/{case_id}    — extracción con flag apply
    POST /api/v9/extract-batch        — corre v9 sobre N casos
    GET  /api/v9/health               — verifica que v9 carga sin errores

Diseño:
    - dry_run por default (seguro)
    - retorno incluye `changes` con el diff exacto que se aplicaría
    - timing por etapa para diagnosticar bottlenecks en producción
    - llm_calls explícito para que la UI muestre cuántas veces se llamó IA
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.auth.dependencies import require_auth
from backend.auth.models import User
from backend.database.database import get_db
from backend.database.models import Case
from backend.v9.pipeline import extract_case
from backend.v9.types import EXCEL_FIELDS

logger = logging.getLogger("tutelas.v9.router")

router = APIRouter(prefix="/api/v9", tags=["v9"])


def _result_to_payload(result) -> dict:
    """Serializa ExtractionResult a JSON. Misma forma para todos los endpoints."""
    f = result.fields
    return {
        "case_id": result.case_id,
        "folder_name": result.folder_name,
        "completitud": f.completitud(),
        "docs": {"processed": result.docs_processed, "failed": result.docs_failed},
        "llm_calls": result.llm_calls,
        "timing_ms": result.timing_ms,
        "warnings": result.warnings,
        "values": dict(f.values),
        "sources": f.sources_json(),
        "missing_fields": f.missing_fields(),
        "canonical": {
            "abogado": f.abogado_canonical,
            "abogado_confidence": f.abogado_canonical_confidence,
            "dependencia": f.dependencia_canonical,
            "dependencia_confidence": f.dependencia_canonical_confidence,
            "direccion_l1": f.direccion,
            "grupo_l2": f.grupo,
            "equipo_l3": f.equipo,
        },
    }


@router.get("/health")
def health(user: User = Depends(require_auth)):
    """Verifica que v9 importe correctamente y devuelve la lista de campos.

    Útil para detectar misconfigs antes de procesar casos reales.
    """
    return {
        "status": "ok",
        "version": "v9.1",
        "fields_count": len(EXCEL_FIELDS),
        "fields": list(EXCEL_FIELDS),
    }


@router.get("/preview/{case_id}")
def preview(
    case_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_auth),
):
    """Corre v9 en dry-run y devuelve qué escribiría sin tocar DB.

    Sirve para que la UI muestre un "antes/después" antes de aplicar.
    """
    case = db.query(Case.id).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case {case_id} no existe")

    try:
        result = extract_case(db, case_id, dry_run=True)
    except Exception as e:
        logger.exception("v9 preview falló para case=%d", case_id)
        raise HTTPException(status_code=500, detail=f"Pipeline v9 error: {e}")

    payload = _result_to_payload(result)
    payload["dry_run"] = True
    return payload


def _promote_status_on_success(db: Session, case_id: int) -> None:
    """Tras una extracción v9 APLICADA con éxito, promover PENDIENTE→COMPLETO
    (espeja `routers/extraction.py`, que es quien históricamente flipea el status).
    Conservador: NO toca REVISION ni DUPLICATE_MERGED para preservar flags humanos.
    Sin esto, el status quedaba stale (260 casos curados marcados PENDIENTE →
    candidatas falsas en /extraction). Idempotente."""
    try:
        c = db.query(Case).filter(Case.id == case_id).first()
        if c is not None and c.processing_status == "PENDIENTE":
            c.processing_status = "COMPLETO"
            db.commit()
    except Exception:
        db.rollback()


@router.post("/extract/{case_id}")
def extract_one(
    case_id: int,
    apply: bool = Query(False, description="Si true, escribe a DB. Default: dry-run."),
    use_llm: bool = Query(False, description="Si true y apply=true, activa el LLM gap-fill semántico."),
    db: Session = Depends(get_db),
    user: User = Depends(require_auth),
):
    """Extrae 1 caso con v9. Por default es dry-run (no toca DB).

    Pasar `?apply=true` para aplicar cambios. Pasar `?use_llm=true` (junto con
    apply=true) para activar el Qwen3-4B en el gap-fill semántico. Retorna el
    mismo shape que `preview` más una sección `applied_changes` cuando apply=true.
    """
    case = db.query(Case.id).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case {case_id} no existe")

    _use_llm = use_llm and apply  # LLM solo tiene sentido cuando se persiste
    try:
        result = extract_case(db, case_id, dry_run=not apply, use_llm=_use_llm)
    except Exception as e:
        logger.exception("v9 extract falló para case=%d apply=%s", case_id, apply)
        raise HTTPException(status_code=500, detail=f"Pipeline v9 error: {e}")

    if apply:
        _promote_status_on_success(db, case_id)

    payload = _result_to_payload(result)
    payload["dry_run"] = not apply
    payload["applied"] = apply
    return payload


@router.post("/extract-batch")
def extract_batch(
    body: dict = Body(default_factory=dict),
    db: Session = Depends(get_db),
    user: User = Depends(require_auth),
):
    """Corre v9 sobre N casos. Body acepta:

        {
          "case_ids": [1, 2, 3],         # lista explícita (opcional)
          "limit": 10,                   # si no hay case_ids, primeros N (default 10)
          "apply": false,                # default false
          "use_llm": false               # activa Qwen3-4B gap-fill (requiere apply=true)
        }

    Para evitar batches gigantes, limit máximo es 100. Para todos los
    casos correr en background (futuro: usar BackgroundTasks).
    """
    case_ids: Optional[list[int]] = body.get("case_ids")
    limit: int = int(body.get("limit", 10))
    apply: bool = bool(body.get("apply", False))
    use_llm: bool = bool(body.get("use_llm", False))

    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="limit debe estar entre 1 y 100")

    if not case_ids:
        rows = db.query(Case.id).order_by(Case.id).limit(limit).all()
        case_ids = [r[0] for r in rows]

    _use_llm = use_llm and apply

    results: list[dict] = []
    errors: list[dict] = []
    for cid in case_ids:
        try:
            r = extract_case(db, cid, dry_run=not apply, use_llm=_use_llm)
            results.append(_result_to_payload(r))
            if apply:
                _promote_status_on_success(db, cid)
        except Exception as e:
            logger.warning("v9 batch case=%d falló: %s", cid, str(e)[:200])
            errors.append({"case_id": cid, "error": str(e)[:200]})

    if results:
        avg_completitud = sum(r["completitud"] for r in results) / len(results)
        total_llm = sum(r["llm_calls"] for r in results)
        total_ms = sum(r["timing_ms"].get("__total", 0) for r in results)
    else:
        avg_completitud = total_llm = total_ms = 0

    return {
        "dry_run": not apply,
        "applied": apply,
        "count": len(results),
        "errors_count": len(errors),
        "summary": {
            "avg_completitud": round(avg_completitud, 1),
            "total_llm_calls": total_llm,
            "total_ms": total_ms,
            "ms_per_case": round(total_ms / max(len(results), 1), 1),
        },
        "results": results,
        "errors": errors,
    }
