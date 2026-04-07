"""Motor de base de datos SQLite con SQLAlchemy."""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from backend.core.settings import settings
from backend.database.models import Base

DATABASE_URL = f"sqlite:///{settings.db_path}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 15},
    echo=False,
    pool_size=5,
    pool_recycle=300,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Activar WAL mode y foreign keys en SQLite."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Crear todas las tablas si no existen."""
    import backend.auth.models  # noqa: F401 — register User model
    import backend.knowledge.models  # noqa: F401 — register KnowledgeEntry
    import backend.agent.reasoning  # noqa: F401 — register ReasoningLog
    import backend.agent.memory  # noqa: F401 — register Correction
    import backend.alerts.models  # noqa: F401 — register Alert
    Base.metadata.create_all(bind=engine)
    # Init FTS5 virtual table for full-text search
    from backend.knowledge.models import init_fts5
    init_fts5(engine)
    # Create default admin user if none exists
    from backend.auth.service import create_default_user
    db = SessionLocal()
    try:
        create_default_user(db)
    finally:
        db.close()


def get_db():
    """Dependency de FastAPI para obtener session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
