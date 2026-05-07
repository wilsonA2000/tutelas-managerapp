"""API de Inteligencia Legal: analytics, predicciones, plazos, similitud."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.database.models import Case
from backend.intelligence.analytics import (
    get_favorability_by_juzgado, get_appeal_analysis,
    get_lawyer_performance, get_monthly_trends,
    get_rights_analysis, predict_outcome,
)
from backend.intelligence.deadlines import get_calendar_events, get_deadline_summary

logger = logging.getLogger("tutelas.api.intelligence")

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


# ---------- helpers para /similar ----------

_SIMILAR_FIELDS = ("asunto", "pretensiones", "accionados", "derecho_vulnerado")
_VALID_SOURCES = {"historical", "current", "mixed"}


def _build_case_text(case: Case) -> str:
    parts = [getattr(case, f, None) for f in _SIMILAR_FIELDS]
    text = " | ".join(p for p in parts if p)
    return text[:4000]


class NeighborOut(BaseModel):
    rank: int
    score: float
    source: str
    case_id: int
    tema: str | None = None
    dependencia: str | None = None
    direccion: str | None = None
    tipo: str | None = None
    fallo: str | None = None
    text_preview: str = ""


class ConsensusOut(BaseModel):
    target: str
    value: str
    confidence: float
    n_valid: int
    n_neighbors: int


class SimilarResponse(BaseModel):
    case_id: int
    k: int
    source: str
    latency_ms: float
    neighbors: list[NeighborOut]
    consensus: list[ConsensusOut]
    reasoning: str


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


# ---------- Capa 2 v9.0: similitud semántica BGE-M3 ----------

@router.get("/similar/{case_id}", response_model=SimilarResponse)
def api_similar(
    case_id: int,
    k: int = Query(5, ge=1, le=20),
    source: str = Query("historical",
        description="historical | current | mixed"),
    db: Session = Depends(get_db),
):
    """Vecinos semánticos del caso `case_id` sobre embeddings BGE-M3.

    - `source=historical`: consenso sobre 4,354 casos etiquetados Excel
    - `source=current`: casos similares en producción (excluye el propio)
    - `source=mixed`: ambos
    """
    import time
    from backend.ml.embeddings import search_similar, knn_consensus

    if source not in _VALID_SOURCES:
        raise HTTPException(400, f"source inválido; usa {_VALID_SOURCES}")

    case = db.query(Case).filter(Case.id == case_id).first()
    if case is None:
        raise HTTPException(404, f"Caso {case_id} no existe")

    text = _build_case_text(case)
    if len(text) < 20:
        raise HTTPException(422,
            f"Caso {case_id} sin texto suficiente para similitud "
            f"(faltan asunto/pretensiones)")

    src_filter = None if source == "mixed" else source
    excl = case_id if source != "historical" else None

    t0 = time.time()
    try:
        neigh = search_similar(text, k=k,
            source_filter=src_filter, exclude_case_id=excl)
    except FileNotFoundError as e:
        raise HTTPException(503,
            "Índice FAISS no construido. Corre "
            "`python -m backend.ml.embeddings.index_builder --rebuild`") from e
    latency = (time.time() - t0) * 1000

    consensus_targets = ("tema", "dependencia", "tipo", "fallo")
    consensus_out: list[ConsensusOut] = []
    if source != "current":
        for tgt in consensus_targets:
            try:
                p = knn_consensus(text, target=tgt, k=k,
                    min_agreement=0.4, source="historical")
            except Exception:
                logger.exception("consensus %s falló", tgt)
                continue
            if p:
                consensus_out.append(ConsensusOut(
                    target=p.target, value=p.value,
                    confidence=p.confidence,
                    n_valid=p.n_valid, n_neighbors=p.n_neighbors,
                ))

    reasoning = _build_reasoning(case, neigh, consensus_out, source)

    return SimilarResponse(
        case_id=case_id,
        k=k,
        source=source,
        latency_ms=round(latency, 1),
        neighbors=[NeighborOut(rank=i+1, **{
            "score": n.score, "source": n.source, "case_id": n.case_id,
            "tema": n.tema, "dependencia": n.dependencia,
            "direccion": n.direccion, "tipo": n.tipo, "fallo": n.fallo,
            "text_preview": n.text_preview,
        }) for i, n in enumerate(neigh)],
        consensus=consensus_out,
        reasoning=reasoning,
    )


def _build_reasoning(case: Case, neigh, consensus, source: str) -> str:
    """Genera explicación legible (sin LLM, plantilla determinista)."""
    if not neigh:
        return ("No se encontraron casos suficientemente similares en el corpus. "
                "El caso puede ser atípico o tener texto insuficiente.")

    parts = []
    parts.append(
        f"Caso #{case.id} comparado con {len(neigh)} vecinos del corpus "
        f"{source}. Score top: {neigh[0].score:.2f}."
    )

    by_fallo = {}
    for n in neigh:
        if n.fallo:
            by_fallo[n.fallo] = by_fallo.get(n.fallo, 0) + 1
    if by_fallo:
        dist = ", ".join(f"{v}× {k}" for k, v in
            sorted(by_fallo.items(), key=lambda x: -x[1]))
        parts.append(f"Fallo histórico vecinos: {dist}.")

    for c in consensus:
        if c.confidence >= 0.6:
            parts.append(
                f"Consenso fuerte para {c.target}: «{c.value}» "
                f"({int(c.confidence*100)}% acuerdo, {c.n_valid}/{c.n_neighbors} vecinos)."
            )
        elif c.confidence >= 0.4:
            parts.append(
                f"Consenso parcial para {c.target}: «{c.value}» "
                f"({int(c.confidence*100)}% acuerdo). Verificar manualmente."
            )

    return " ".join(parts)


@router.get("/similar-by-text", response_model=SimilarResponse)
def api_similar_by_text(
    text: str = Query(..., min_length=20, max_length=8000),
    k: int = Query(5, ge=1, le=20),
    source: str = Query("historical"),
):
    """Búsqueda por texto libre (útil para chat agente y debug).

    No consulta DB — operate sobre el texto crudo del usuario.
    """
    import time
    from backend.ml.embeddings import search_similar, knn_consensus

    if source not in _VALID_SOURCES:
        raise HTTPException(400, f"source inválido; usa {_VALID_SOURCES}")

    src_filter = None if source == "mixed" else source

    t0 = time.time()
    try:
        neigh = search_similar(text, k=k, source_filter=src_filter)
    except FileNotFoundError as e:
        raise HTTPException(503, "Índice FAISS no construido") from e
    latency = (time.time() - t0) * 1000

    consensus_out: list[ConsensusOut] = []
    if source != "current":
        for tgt in ("tema", "dependencia", "tipo", "fallo"):
            try:
                p = knn_consensus(text, target=tgt, k=k,
                    min_agreement=0.4, source="historical")
            except Exception:
                continue
            if p:
                consensus_out.append(ConsensusOut(
                    target=p.target, value=p.value,
                    confidence=p.confidence,
                    n_valid=p.n_valid, n_neighbors=p.n_neighbors,
                ))

    return SimilarResponse(
        case_id=0,
        k=k,
        source=source,
        latency_ms=round(latency, 1),
        neighbors=[NeighborOut(rank=i+1, **{
            "score": n.score, "source": n.source, "case_id": n.case_id,
            "tema": n.tema, "dependencia": n.dependencia,
            "direccion": n.direccion, "tipo": n.tipo, "fallo": n.fallo,
            "text_preview": n.text_preview,
        }) for i, n in enumerate(neigh)],
        consensus=consensus_out,
        reasoning=f"Búsqueda por texto libre: {len(neigh)} vecinos, "
                  f"top-score {neigh[0].score:.2f}." if neigh else
                  "Sin coincidencias.",
    )
