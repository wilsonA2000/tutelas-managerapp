"""Fixtures globales para la suite de tests E2E.

DB temporal en /tmp, sin dependencia de IA ni Gmail.
"""

import os
import sys
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# Asegurar que el directorio raiz esta en el path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ============================================================
# Directorios temporales
# ============================================================

@pytest.fixture(scope="session")
def tmp_base_dir():
    """Directorio temporal que simula BASE_DIR con carpetas de casos."""
    d = tempfile.mkdtemp(prefix="tutelas_test_cases_")
    # Crear 3 carpetas de caso de prueba
    for name in [
        "2026-00001 JUAN PEREZ GOMEZ",
        "2026-00002 MARIA GARCIA LOPEZ",
        "2026-00003 PEDRO MARTINEZ",
    ]:
        folder = Path(d) / name
        folder.mkdir()
        # Crear un PDF dummy
        (folder / "001AutoAdmisorio.pdf").write_bytes(b"%PDF-1.4 dummy")
        (folder / "Gmail - RV_ Tutela.pdf").write_bytes(b"%PDF-1.4 email")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(scope="session")
def tmp_app_dir(tmp_base_dir):
    """Directorio temporal para app_dir (data, exports, backups)."""
    app_dir = Path(tmp_base_dir) / "tutelas-app"
    app_dir.mkdir(exist_ok=True)
    (app_dir / "data").mkdir(exist_ok=True)
    (app_dir / "data" / "exports").mkdir(exist_ok=True)
    (app_dir / "data" / "backups").mkdir(exist_ok=True)
    (app_dir / "data" / "sandbox").mkdir(exist_ok=True)
    return str(app_dir)


# ============================================================
# Base de datos temporal
# ============================================================

@pytest.fixture(scope="session")
def test_engine(tmp_app_dir):
    """Engine SQLAlchemy con DB temporal."""
    db_path = Path(tmp_app_dir) / "data" / "tutelas_test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


@pytest.fixture(scope="session")
def TestSessionFactory(test_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session")
def _create_tables(test_engine):
    """Crear todas las tablas en la DB de test."""
    from backend.database.models import Base
    import backend.auth.models  # noqa
    import backend.knowledge.models  # noqa
    import backend.agent.reasoning  # noqa
    import backend.agent.memory  # noqa
    import backend.alerts.models  # noqa
    Base.metadata.create_all(bind=test_engine)


# ============================================================
# Seed data
# ============================================================

@pytest.fixture(scope="session")
def seed_data(_create_tables, TestSessionFactory, tmp_base_dir):
    """Poblar la DB de test con datos minimos."""
    from backend.database.models import (
        Case, Document, Email, AuditLog, Extraction,
        ComplianceTracking, TokenUsage,
    )
    from backend.auth.models import User
    from backend.auth.service import hash_password

    db = TestSessionFactory()
    try:
        # Usuario admin
        user = User(
            username="testadmin",
            password_hash=hash_password("test123"),
            full_name="Test Admin",
            role="admin",
        )
        db.add(user)
        db.flush()

        base = Path(tmp_base_dir)

        # Caso 1: COMPLETO
        c1 = Case(
            folder_name="2026-00001 JUAN PEREZ GOMEZ",
            folder_path=str(base / "2026-00001 JUAN PEREZ GOMEZ"),
            processing_status="COMPLETO",
            radicado_23_digitos="68001400300120260000100",
            accionante="JUAN PEREZ GOMEZ",
            juzgado="JUZGADO PRIMERO CIVIL MUNICIPAL",
            ciudad="BUCARAMANGA",
            estado="ACTIVO",
            derecho_vulnerado="SALUD",
            sentido_fallo_1st="CONCEDE",
            fecha_fallo_1st="15/03/2026",
            fecha_ingreso="01/03/2026",
            abogado_responsable="DRA. ANA RUIZ",
            oficina_responsable="SECRETARIA DE SALUD",
        )
        db.add(c1)
        db.flush()

        # Caso 2: PENDIENTE (>20% completitud = 8+ campos de 36)
        c2 = Case(
            folder_name="2026-00002 MARIA GARCIA LOPEZ",
            folder_path=str(base / "2026-00002 MARIA GARCIA LOPEZ"),
            processing_status="PENDIENTE",
            accionante="MARIA GARCIA LOPEZ",
            radicado_23_digitos="68001400300120260000200",
            estado="ACTIVO",
            juzgado="JUZGADO SEGUNDO CIVIL MUNICIPAL",
            ciudad="FLORIDABLANCA",
            derecho_vulnerado="SALUD",
            fecha_ingreso="05/03/2026",
            oficina_responsable="SECRETARIA DE SALUD",
        )
        db.add(c2)
        db.flush()

        # Caso 3: REVISION (>20% completitud = 8+ campos de 36)
        c3 = Case(
            folder_name="2026-00003 PEDRO MARTINEZ",
            folder_path=str(base / "2026-00003 PEDRO MARTINEZ"),
            processing_status="REVISION",
            accionante="PEDRO MARTINEZ",
            radicado_23_digitos="68001400300120260000300",
            estado="ACTIVO",
            juzgado="JUZGADO TERCERO CIVIL MUNICIPAL",
            ciudad="BUCARAMANGA",
            derecho_vulnerado="PETICION",
            fecha_ingreso="10/03/2026",
            oficina_responsable="SECRETARIA GENERAL",
        )
        db.add(c3)
        db.flush()

        # Documentos
        docs = [
            Document(case_id=c1.id, filename="001AutoAdmisorio.pdf",
                     file_path=str(base / "2026-00001 JUAN PEREZ GOMEZ" / "001AutoAdmisorio.pdf"),
                     doc_type="AUTO_ADMISORIO", file_size=1024, verificacion="OK",
                     extracted_text="Auto admisorio de tutela. Radicado 68001400300120260000100"),
            Document(case_id=c1.id, filename="Gmail - RV_ Tutela.pdf",
                     file_path=str(base / "2026-00001 JUAN PEREZ GOMEZ" / "Gmail - RV_ Tutela.pdf"),
                     doc_type="GMAIL", file_size=512, verificacion="OK"),
            Document(case_id=c2.id, filename="001AutoAdmisorio.pdf",
                     file_path=str(base / "2026-00002 MARIA GARCIA LOPEZ" / "001AutoAdmisorio.pdf"),
                     doc_type="AUTO_ADMISORIO", file_size=2048, verificacion="SOSPECHOSO",
                     verificacion_detalle="Radicado no coincide"),
            Document(case_id=c3.id, filename="001AutoAdmisorio.pdf",
                     file_path=str(base / "2026-00003 PEDRO MARTINEZ" / "001AutoAdmisorio.pdf"),
                     doc_type="AUTO_ADMISORIO", file_size=768, verificacion="NO_PERTENECE",
                     verificacion_detalle="Radicado 2026-00099 encontrado, no coincide con caso",
                     extracted_text="Radicado 68001400300120260009900"),
            Document(case_id=c3.id, filename="Gmail - RV_ Tutela.pdf",
                     file_path=str(base / "2026-00003 PEDRO MARTINEZ" / "Gmail - RV_ Tutela.pdf"),
                     doc_type="GMAIL", file_size=300),
        ]
        db.add_all(docs)
        db.flush()

        # Emails
        e1 = Email(
            message_id="msg001@gmail.com",
            subject="RV: Tutela 2026-00001",
            sender="juzgado@cendoj.ramajudicial.gov.co",
            date_received=datetime.utcnow() - timedelta(days=5),
            body_preview="Se notifica tutela radicada...",
            case_id=c1.id,
            status="ASIGNADO",
        )
        e2 = Email(
            message_id="msg002@gmail.com",
            subject="RV: Tutela nueva",
            sender="otro@cendoj.ramajudicial.gov.co",
            date_received=datetime.utcnow() - timedelta(days=1),
            body_preview="Nueva tutela sin asignar...",
            status="PENDIENTE",
        )
        db.add_all([e1, e2])
        db.flush()

        # AuditLog
        db.add(AuditLog(
            case_id=c1.id,
            field_name="ACCIONANTE",
            old_value="",
            new_value="JUAN PEREZ GOMEZ",
            action="AI_EXTRAER",
            source="pipeline",
        ))

        # Extraction
        db.add(Extraction(
            case_id=c1.id,
            document_id=docs[0].id,
            field_name="ACCIONANTE",
            extracted_value="JUAN PEREZ GOMEZ",
            confidence="ALTA",
            extraction_method="regex",
        ))

        # ComplianceTracking
        db.add(ComplianceTracking(
            case_id=c1.id,
            instancia="1ra",
            sentido_fallo="CONCEDE",
            fecha_fallo="15/03/2026",
            plazo_dias=48,
            estado="PENDIENTE",
        ))

        # TokenUsage
        db.add(TokenUsage(
            provider="groq",
            model="llama-3.3-70b-versatile",
            tokens_input=5000,
            tokens_output=1000,
            cost_total="0.00",
            case_id=c1.id,
            fields_extracted=5,
            duration_ms=1200,
        ))

        db.commit()

        yield {
            "user_id": user.id,
            "case_ids": [c1.id, c2.id, c3.id],
            "doc_ids": [d.id for d in docs],
            "email_ids": [e1.id, e2.id],
        }

    finally:
        db.close()


# ============================================================
# FastAPI app con overrides
# ============================================================

@pytest.fixture(scope="session")
def app(test_engine, TestSessionFactory, seed_data, tmp_base_dir, tmp_app_dir):
    """App FastAPI con DB de test y sin dependencias externas."""
    from backend.database.database import get_db

    # Patch settings ANTES de importar main
    with patch("backend.core.settings.settings.BASE_DIR", tmp_base_dir), \
         patch.object(
             type(__import__("backend.core.settings", fromlist=["settings"]).settings),
             "app_dir", new_callable=lambda: property(lambda self: Path(tmp_app_dir))
         ), \
         patch.object(
             type(__import__("backend.core.settings", fromlist=["settings"]).settings),
             "db_path", new_callable=lambda: property(lambda self: Path(tmp_app_dir) / "data" / "tutelas_test.db")
         ):

        from backend.main import app as fastapi_app

        # Override get_db dependency
        def _override_get_db():
            db = TestSessionFactory()
            try:
                yield db
            finally:
                db.close()

        fastapi_app.dependency_overrides[get_db] = _override_get_db

        # Monkey-patch SessionLocal en modulos que lo usan directamente
        import backend.main
        import backend.routers.extraction as ext_router
        backend.main.SessionLocal = TestSessionFactory
        ext_router.SessionLocal = TestSessionFactory

        yield fastapi_app

        # Cleanup
        fastapi_app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def client(app):
    """HTTP client para tests (sin servidor corriendo)."""
    from starlette.testclient import TestClient
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ============================================================
# Auth
# ============================================================

@pytest.fixture(scope="session")
def auth_headers(client):
    """Headers de autenticacion para endpoints protegidos."""
    r = client.post("/api/auth/login", json={
        "username": "testadmin",
        "password": "test123",
    })
    assert r.status_code == 200, f"Login failed: {r.text}"
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# Reset global state
# ============================================================

@pytest.fixture(autouse=True)
def reset_globals():
    """Resetear estado global entre tests."""
    import backend.main as m
    m.extraction_in_progress = False
    m.extraction_progress = {"current": 0, "total": 0, "case_name": "", "results": []}
    m.gmail_check_in_progress = False
    m.gmail_check_result = {}
    m.sync_in_progress = False
    m.sync_result = {}
    yield


# ============================================================
# Helper IDs
# ============================================================

@pytest.fixture(scope="session")
def case_ids(seed_data):
    return seed_data["case_ids"]


@pytest.fixture(scope="session")
def doc_ids(seed_data):
    return seed_data["doc_ids"]


@pytest.fixture(scope="session")
def email_ids(seed_data):
    return seed_data["email_ids"]
