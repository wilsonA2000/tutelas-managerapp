"""Knowledge Base con SQLite FTS5 para búsqueda full-text.

Indexa todas las fuentes: emails, PDFs, DOCX, .md files, campos DB.
Permite buscar cualquier texto en todo el ecosistema de datos.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, event
from datetime import datetime

from backend.database.models import Base


class KnowledgeEntry(Base):
    """Entrada en la base de conocimiento indexada."""
    __tablename__ = "knowledge_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, nullable=True, index=True)
    source_type = Column(String, nullable=False, index=True)
    # source_type: email, pdf, docx, md, db_field, cowork_md, email_md
    source_name = Column(String, nullable=False)  # filename or field name
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=True)  # SHA256 for dedup
    created_at = Column(DateTime, default=datetime.utcnow)


def init_fts5(engine):
    """Crear tabla FTS5 virtual para búsqueda full-text.
    Se llama después de create_all()."""
    with engine.connect() as conn:
        # Verificar si ya existe
        result = conn.execute(
            __import__('sqlalchemy').text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge_fts'"
            )
        )
        if result.fetchone():
            return

        # Crear tabla FTS5 vinculada a knowledge_entries
        conn.execute(__import__('sqlalchemy').text("""
            CREATE VIRTUAL TABLE knowledge_fts USING fts5(
                content,
                source_name,
                source_type,
                content='knowledge_entries',
                content_rowid='id'
            )
        """))

        # Triggers para mantener FTS sincronizado
        conn.execute(__import__('sqlalchemy').text("""
            CREATE TRIGGER knowledge_fts_insert AFTER INSERT ON knowledge_entries BEGIN
                INSERT INTO knowledge_fts(rowid, content, source_name, source_type)
                VALUES (new.id, new.content, new.source_name, new.source_type);
            END
        """))
        conn.execute(__import__('sqlalchemy').text("""
            CREATE TRIGGER knowledge_fts_delete AFTER DELETE ON knowledge_entries BEGIN
                INSERT INTO knowledge_fts(knowledge_fts, rowid, content, source_name, source_type)
                VALUES ('delete', old.id, old.content, old.source_name, old.source_type);
            END
        """))
        conn.execute(__import__('sqlalchemy').text("""
            CREATE TRIGGER knowledge_fts_update AFTER UPDATE ON knowledge_entries BEGIN
                INSERT INTO knowledge_fts(knowledge_fts, rowid, content, source_name, source_type)
                VALUES ('delete', old.id, old.content, old.source_name, old.source_type);
                INSERT INTO knowledge_fts(rowid, content, source_name, source_type)
                VALUES (new.id, new.content, new.source_name, new.source_type);
            END
        """))
        conn.commit()
