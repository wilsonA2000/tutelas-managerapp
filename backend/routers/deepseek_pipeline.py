"""Router del pipeline experimental DeepSeek end-to-end."""
from __future__ import annotations
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth.dependencies import require_auth
from backend.database.database import get_db
from backend.deepseek_pipeline.client import is_available
from backend.deepseek_pipeline.pipeline import (
    run_pipeline, apply_to_db, _load_cached, _result_to_dict, RESULTS_DIR
)

router = APIRouter(prefix="/api/deepseek", tags=["deepseek-pipeline"])
log = logging.getLogger("tutelas.routers.deepseek_pipeline")


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health")
def deepseek_health():
    """Verifica si DeepSeek está configurado."""
    return {
        "available": is_available(),
        "message": "DeepSeek pipeline experimental activo" if is_available()
                   else "DEEPSEEK_API_KEY no configurada — añadir al .env",
    }


# ── Procesar un caso completo ──────────────────────────────────────────────────

class PipelineRequest(BaseModel):
    classify_docs: bool = True    # Fase 1: clasificar documentos
    extract: bool = True          # Fase 2: extraer 43 campos
    use_cached: bool = False      # Usar resultado guardado si existe


@router.post("/process/{case_id}")
def process_case(
    case_id: int,
    req: PipelineRequest = PipelineRequest(),
    db: Session = Depends(get_db),
    _user=Depends(require_auth),
):
    """
    Corre el pipeline DeepSeek completo para un caso:
    1. Clasifica los documentos
    2. Extrae los 43 campos
    3. Devuelve comparación vs v9

    No modifica la DB — solo guarda resultado en data/experiment/deepseek_pipeline/
    """
    if not is_available():
        raise HTTPException(400, "DEEPSEEK_API_KEY no configurada")

    result = run_pipeline(
        db, case_id,
        use_cached=req.use_cached,
        classify_docs=req.classify_docs,
        extract=req.extract,
    )

    if result.error:
        raise HTTPException(500, result.error)

    return _result_to_dict(result)


# ── Ver resultado guardado ─────────────────────────────────────────────────────

@router.get("/result/{case_id}")
def get_result(
    case_id: int,
    _user=Depends(require_auth),
):
    """Devuelve el resultado guardado del último pipeline para un caso."""
    result = _load_cached(case_id)
    if not result:
        raise HTTPException(404, f"No hay resultado para case {case_id}. Corre /process primero.")
    return _result_to_dict(result)


# ── Aplicar a la DB ────────────────────────────────────────────────────────────

class ApplyRequest(BaseModel):
    mode: str = "fill-empty"   # fill-empty | all-non-manual


@router.post("/apply/{case_id}")
def apply_result(
    case_id: int,
    req: ApplyRequest = ApplyRequest(),
    db: Session = Depends(get_db),
    _user=Depends(require_auth),
):
    """
    Aplica los campos del resultado DeepSeek a la DB de producción.

    mode='fill-empty'    → solo llena campos vacíos (seguro, recomendado)
    mode='all-non-manual' → también sobrescribe campos no-manuales
    """
    result = apply_to_db(db, case_id, mode=req.mode)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


# ── Batch ─────────────────────────────────────────────────────────────────────

class BatchRequest(BaseModel):
    case_ids: Optional[list[int]] = None   # None = todos los activos
    limit: int = 10
    classify_docs: bool = True
    extract: bool = True
    skip_cached: bool = True


@router.post("/process-batch")
def process_batch(
    req: BatchRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_auth),
):
    """
    Procesa un lote de casos con el pipeline DeepSeek.
    Por defecto salta los que ya tienen resultado guardado.
    """
    if not is_available():
        raise HTTPException(400, "DEEPSEEK_API_KEY no configurada")

    from backend.database.models import Case

    if req.case_ids:
        case_ids = req.case_ids[:req.limit]
    else:
        rows = db.query(Case.id).filter(Case.estado != "DUPLICATE_MERGED").limit(req.limit).all()
        case_ids = [r[0] for r in rows]

    if req.skip_cached:
        case_ids = [cid for cid in case_ids if not (RESULTS_DIR / f"{cid}.json").exists()]

    results_summary = []
    for cid in case_ids:
        try:
            r = run_pipeline(db, cid, classify_docs=req.classify_docs, extract=req.extract)
            n_verde = sum(1 for d in r.diff_vs_v9 if d["semaforo"] == "VERDE")
            results_summary.append({
                "case_id": cid,
                "folder_name": r.folder_name,
                "completitud": r.extraction.completitud() if r.extraction else 0,
                "verde": n_verde,
                "elapsed_ms": r.elapsed_ms_total,
                "error": r.error,
            })
        except Exception as exc:
            results_summary.append({"case_id": cid, "error": str(exc)[:200]})

    return {
        "processed": len(results_summary),
        "results": results_summary,
    }


# ── Stats globales ────────────────────────────────────────────────────────────

@router.get("/stats")
def get_stats(_user=Depends(require_auth)):
    """Cuántos casos tienen resultado guardado y resumen del diff."""
    from collections import Counter
    import json

    files = list(RESULTS_DIR.glob("*.json"))
    if not files:
        return {"total_procesados": 0}

    verde_total = amarillo_total = 0
    completitudes = []
    for p in files:
        try:
            d = json.loads(p.read_text())
            for diff in d.get("diff_vs_v9", []):
                if diff["semaforo"] == "VERDE":
                    verde_total += 1
                elif diff["semaforo"] == "AMARILLO":
                    amarillo_total += 1
            ext = d.get("extraction")
            if ext:
                completitudes.append(ext.get("completitud", 0))
        except Exception:
            pass

    return {
        "total_procesados": len(files),
        "diff_verde_total": verde_total,
        "diff_amarillo_total": amarillo_total,
        "completitud_promedio": round(sum(completitudes) / len(completitudes), 1) if completitudes else 0,
    }
