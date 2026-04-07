"""Motor de búsqueda full-text sobre el Knowledge Base."""

from dataclasses import dataclass
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.knowledge.models import KnowledgeEntry


@dataclass
class SearchResult:
    id: int
    case_id: int | None
    source_type: str
    source_name: str
    snippet: str
    rank: float


def full_text_search(db: Session, query: str, limit: int = 20, source_type: str | None = None) -> list[SearchResult]:
    """Búsqueda full-text usando FTS5.

    Args:
        query: Texto a buscar (soporta operadores FTS5: AND, OR, NOT, NEAR)
        limit: Máximo resultados
        source_type: Filtrar por tipo de fuente (email, pdf, docx, md, db_field)
    """
    # Sanitize query for FTS5
    safe_query = query.replace('"', '').replace("'", "").strip()
    if not safe_query:
        return []

    # Build FTS5 query with source_type filter
    if source_type:
        sql = text("""
            SELECT ke.id, ke.case_id, ke.source_type, ke.source_name,
                   snippet(knowledge_fts, 0, '<b>', '</b>', '...', 64) as snippet,
                   rank
            FROM knowledge_fts
            JOIN knowledge_entries ke ON knowledge_fts.rowid = ke.id
            WHERE knowledge_fts MATCH :query AND ke.source_type = :source_type
            ORDER BY rank
            LIMIT :limit
        """)
        rows = db.execute(sql, {"query": safe_query, "source_type": source_type, "limit": limit}).fetchall()
    else:
        sql = text("""
            SELECT ke.id, ke.case_id, ke.source_type, ke.source_name,
                   snippet(knowledge_fts, 0, '<b>', '</b>', '...', 64) as snippet,
                   rank
            FROM knowledge_fts
            JOIN knowledge_entries ke ON knowledge_fts.rowid = ke.id
            WHERE knowledge_fts MATCH :query
            ORDER BY rank
            LIMIT :limit
        """)
        rows = db.execute(sql, {"query": safe_query, "limit": limit}).fetchall()

    return [
        SearchResult(
            id=r[0], case_id=r[1], source_type=r[2], source_name=r[3],
            snippet=r[4] or "", rank=r[5] or 0.0,
        )
        for r in rows
    ]


def search_by_case(db: Session, case_id: int, query: str | None = None) -> list[KnowledgeEntry]:
    """Obtener todo el conocimiento de un caso específico."""
    q = db.query(KnowledgeEntry).filter(KnowledgeEntry.case_id == case_id)
    if query:
        q = q.filter(KnowledgeEntry.content.contains(query))
    return q.order_by(KnowledgeEntry.source_type).all()


def search_by_content(db: Session, text_fragment: str, limit: int = 10) -> list[KnowledgeEntry]:
    """Búsqueda simple por LIKE (fallback si FTS5 no disponible)."""
    return db.query(KnowledgeEntry).filter(
        KnowledgeEntry.content.contains(text_fragment)
    ).limit(limit).all()


def get_stats(db: Session) -> dict:
    """Estadísticas del Knowledge Base."""
    total = db.query(KnowledgeEntry).count()
    by_type = {}
    for row in db.execute(text(
        "SELECT source_type, COUNT(*) FROM knowledge_entries GROUP BY source_type"
    )).fetchall():
        by_type[row[0]] = row[1]
    cases_indexed = db.execute(text(
        "SELECT COUNT(DISTINCT case_id) FROM knowledge_entries WHERE case_id IS NOT NULL"
    )).scalar()
    return {"total_entries": total, "by_type": by_type, "cases_indexed": cases_indexed}
