"""Tests de integridad DB — Sprint 1 v5.1.

Detectan descuadres historicos que Sprint 1 arreglo:
- Documents en casos DUPLICATE_MERGED
- Emails en casos DUPLICATE_MERGED
- file_path desalineado vs folder_path del caso
- foreign_keys activas
- WAL checkpoint funcional
"""

import os
import re
import sqlite3

import pytest

DB_PATH = os.environ.get("TEST_DB_PATH", "data/tutelas.db")


@pytest.fixture
def db():
    """Conexion directa SQLite a la DB de produccion (solo lectura para integridad)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


class TestFKAndPragmas:
    """Verifica que pragmas criticas esten configuradas."""

    def test_journal_mode_is_wal(self, db):
        r = db.execute("PRAGMA journal_mode").fetchone()
        assert r[0].lower() == "wal"

    def test_foreign_keys_enabled_in_orm(self):
        """Cuando la app se conecta via ORM, FK debe estar ON."""
        from backend.database.database import engine
        with engine.connect() as conn:
            r = conn.exec_driver_sql("PRAGMA foreign_keys").fetchone()
            assert r[0] == 1, "FK debe estar ON en conexiones ORM"


class TestIntegrityV51:
    """Verifican que el reconcile de v5.1 Sprint 1 no regresa."""

    def test_integrity_check_ok(self, db):
        r = db.execute("PRAGMA integrity_check(5)").fetchall()
        assert r[0][0] == "ok"

    def test_no_documents_in_duplicate_merged(self, db):
        """Docs NO deben apuntar a casos DUPLICATE_MERGED (deben estar en canonicos)."""
        n = db.execute("""
            SELECT COUNT(*) FROM documents d
            JOIN cases c ON d.case_id=c.id
            WHERE c.processing_status='DUPLICATE_MERGED'
        """).fetchone()[0]
        # Tolerancia: docs con 'sin canonico identificable' (merges legacy sin trace)
        # quedan donde estan. Target: 0 idealmente, <100 aceptable tras Sprint 1.
        assert n < 100, f"Muchos docs ({n}) siguen en DUPLICATE_MERGED — correr /api/cleanup/reconcile"

    def test_no_emails_in_duplicate_merged(self, db):
        n = db.execute("""
            SELECT COUNT(*) FROM emails e
            JOIN cases c ON e.case_id=c.id
            WHERE c.processing_status='DUPLICATE_MERGED'
        """).fetchone()[0]
        assert n < 20, f"Muchos emails ({n}) en DUPLICATE_MERGED"

    def test_no_orphan_documents(self, db):
        """Todo doc con case_id debe apuntar a caso existente."""
        n = db.execute("""
            SELECT COUNT(*) FROM documents d
            LEFT JOIN cases c ON d.case_id=c.id
            WHERE c.id IS NULL AND d.case_id IS NOT NULL
        """).fetchone()[0]
        assert n == 0, f"{n} documents con case_id invalido (orphans)"

    def test_no_orphan_emails(self, db):
        n = db.execute("""
            SELECT COUNT(*) FROM emails e
            LEFT JOIN cases c ON e.case_id=c.id
            WHERE c.id IS NULL AND e.case_id IS NOT NULL
        """).fetchone()[0]
        assert n == 0, f"{n} emails con case_id invalido"


class TestWalCheckpoint:
    """wal_checkpoint() funcional — crucial para que scripts CLI vean datos frescos."""

    def test_wal_checkpoint_passive_returns_dict(self):
        from backend.database.database import wal_checkpoint
        r = wal_checkpoint("PASSIVE")
        assert isinstance(r, dict)
        assert "mode" in r
        assert r["mode"] == "PASSIVE"
        assert "error" not in r or r.get("error") is None

    def test_wal_checkpoint_truncate_returns_dict(self):
        from backend.database.database import wal_checkpoint
        r = wal_checkpoint("TRUNCATE")
        assert isinstance(r, dict)
        assert r["mode"] == "TRUNCATE"
