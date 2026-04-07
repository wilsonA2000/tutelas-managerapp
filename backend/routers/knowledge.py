"""API de Knowledge Base: búsqueda full-text e indexación."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.knowledge.search import full_text_search, get_stats, search_by_case
from backend.knowledge.indexer import rebuild_index
from backend.core.settings import settings

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/search")
def api_search(
    q: str = Query(..., min_length=2, description="Texto a buscar"),
    source_type: str | None = Query(None, description="Filtrar por tipo: email, pdf, docx, md, db_field"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    results = full_text_search(db, q, limit=limit, source_type=source_type)
    return {
        "query": q,
        "count": len(results),
        "results": [
            {
                "id": r.id,
                "case_id": r.case_id,
                "source_type": r.source_type,
                "source_name": r.source_name,
                "snippet": r.snippet,
                "rank": r.rank,
            }
            for r in results
        ],
    }


@router.get("/case/{case_id}")
def api_case_knowledge(case_id: int, db: Session = Depends(get_db)):
    entries = search_by_case(db, case_id)
    return {
        "case_id": case_id,
        "count": len(entries),
        "entries": [
            {
                "id": e.id,
                "source_type": e.source_type,
                "source_name": e.source_name,
                "content_preview": e.content[:200] if e.content else "",
            }
            for e in entries
        ],
    }


@router.get("/stats")
def api_stats(db: Session = Depends(get_db)):
    return get_stats(db)


@router.post("/rebuild")
def api_rebuild(db: Session = Depends(get_db)):
    count = rebuild_index(db, settings.BASE_DIR)
    return {"message": f"Índice reconstruido: {count} entradas", "count": count}
