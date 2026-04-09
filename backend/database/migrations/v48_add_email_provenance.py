"""Migracion v4.8: agregar email_id + email_message_id a documents.

Agrega el vinculo inmutable entre Document y Email de origen, implementando
el patron "paquetes inmutables" (ver memoria project_v48_provenance.md).

Idempotente: detecta si las columnas ya existen antes de agregarlas.

Uso:
    python -m backend.database.migrations.v48_add_email_provenance

O desde Python:
    from backend.database.migrations.v48_add_email_provenance import run
    run()
"""

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger("tutelas.migrations")


def _column_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    """Check si una columna existe en una tabla SQLite."""
    cursor.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in cursor.fetchall()]
    return column in cols


def _index_exists(cursor: sqlite3.Cursor, index_name: str) -> bool:
    """Check si un indice existe."""
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (index_name,),
    )
    return cursor.fetchone() is not None


def run(db_path: str | None = None) -> dict:
    """Aplica la migracion v4.8 de forma idempotente.

    Args:
        db_path: Ruta a la DB. Si None, usa settings.db_path.

    Returns:
        dict con las acciones aplicadas.
    """
    if db_path is None:
        from backend.core.settings import settings
        db_path = str(settings.db_path)

    if not Path(db_path).exists():
        raise FileNotFoundError(f"DB no encontrada: {db_path}")

    result: dict = {
        "db_path": db_path,
        "actions": [],
        "skipped": [],
    }

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 1. Agregar documents.email_id (FK a emails.id)
        if _column_exists(cursor, "documents", "email_id"):
            result["skipped"].append("documents.email_id ya existe")
        else:
            cursor.execute(
                "ALTER TABLE documents ADD COLUMN email_id INTEGER REFERENCES emails(id)"
            )
            result["actions"].append("ALTER TABLE documents ADD COLUMN email_id")
            logger.info("Added column documents.email_id")

        # 2. Agregar documents.email_message_id (string, para backfill/debug)
        if _column_exists(cursor, "documents", "email_message_id"):
            result["skipped"].append("documents.email_message_id ya existe")
        else:
            cursor.execute(
                "ALTER TABLE documents ADD COLUMN email_message_id TEXT"
            )
            result["actions"].append("ALTER TABLE documents ADD COLUMN email_message_id")
            logger.info("Added column documents.email_message_id")

        # 3. Crear indice en email_id para acelerar get_siblings()
        if _index_exists(cursor, "ix_documents_email_id"):
            result["skipped"].append("ix_documents_email_id ya existe")
        else:
            cursor.execute(
                "CREATE INDEX ix_documents_email_id ON documents(email_id)"
            )
            result["actions"].append("CREATE INDEX ix_documents_email_id")
            logger.info("Created index ix_documents_email_id")

        # 4. Crear indice en email_message_id para buscar por gmail id
        if _index_exists(cursor, "ix_documents_email_message_id"):
            result["skipped"].append("ix_documents_email_message_id ya existe")
        else:
            cursor.execute(
                "CREATE INDEX ix_documents_email_message_id ON documents(email_message_id)"
            )
            result["actions"].append("CREATE INDEX ix_documents_email_message_id")
            logger.info("Created index ix_documents_email_message_id")

        conn.commit()
        result["status"] = "ok"

    except Exception as e:
        conn.rollback()
        result["status"] = "error"
        result["error"] = str(e)
        logger.error("Migration v48 failed: %s", e, exc_info=True)
        raise
    finally:
        conn.close()

    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import json
    r = run()
    print(json.dumps(r, indent=2))
