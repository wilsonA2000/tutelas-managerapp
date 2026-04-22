"""Motor de base de datos SQLite con SQLAlchemy."""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from backend.core.settings import settings
from backend.database.models import Base

DATABASE_URL = f"sqlite:///{settings.db_path}"

# v5.1 (Sprint 1): pool_size=1 en modo single-user local evita snapshots divergentes
# entre conexiones concurrentes que veia el usuario como "DB descuadrada".
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 15},
    echo=False,
    pool_size=1,
    pool_recycle=300,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Activar WAL, FKs y ajustes de rendimiento en cada conexion SQLite.

    v5.1: foreign_keys=ON en CADA connect (antes se perdia en conexiones reusadas del pool).
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")  # menor overhead que FULL, seguro con WAL
    cursor.execute("PRAGMA busy_timeout=10000")  # 10s antes de fallar por lock
    cursor.close()


def wal_checkpoint(mode: str = "PASSIVE") -> dict:
    """v5.1 Sprint 1: forzar flush WAL -> archivo principal.

    Modos:
    - PASSIVE: no bloquea escritores activos (default, recomendado para scheduler)
    - FULL: espera a que escritores terminen (usar en mantenimiento)
    - TRUNCATE: FULL + trunca el .db-wal a 0 bytes (pre-backup)

    Ejecutar periodicamente evita que .db-wal crezca indefinidamente y
    garantiza que scripts CLI vean datos frescos al abrir el .db principal.
    """
    try:
        with engine.connect() as conn:
            row = conn.exec_driver_sql(f"PRAGMA wal_checkpoint({mode})").fetchone()
            return {"mode": mode, "busy": row[0], "log_pages": row[1], "checkpointed": row[2]}
    except Exception as e:
        return {"mode": mode, "error": str(e)}


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
