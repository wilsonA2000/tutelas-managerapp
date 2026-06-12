"""Auto-curación carpeta↔DB (2026-06-12, caso real c557 Luz Narda).

Un rollback a mitad de ingesta deja ARCHIVOS en disco sin fila Document → el
módulo muestra el caso "sin documentos" hasta un refresh manual. La post-ingesta
ahora corre `sync_case_folder` sobre cada caso tocado (self-healing).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case, Document
from backend.services.sync_service import sync_case_folder


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_registra_huerfanos_de_disco(db, tmp_path):
    folder = tmp_path / "2026-00920 PRUEBA HUERFANOS"
    folder.mkdir()
    (folder / "SentenciaTutela.pdf").write_bytes(b"%PDF-1.4 fake")
    (folder / "notas.txt").write_text("no es tipo valido")  # extensión ignorada
    c = Case(folder_name=folder.name, folder_path=str(folder))
    db.add(c); db.commit()

    r = sync_case_folder(db, c, source="test")
    assert r["docs_added"] == 1
    docs = db.query(Document).filter(Document.case_id == c.id).all()
    assert len(docs) == 1 and docs[0].filename == "SentenciaTutela.pdf"
    # created_at queda poblado (fix del default cliente-side — antes NULL)
    assert docs[0].created_at is not None


def test_idempotente(db, tmp_path):
    folder = tmp_path / "2026-00921 PRUEBA IDEM"
    folder.mkdir()
    (folder / "Auto.pdf").write_bytes(b"%PDF-1.4 fake")
    c = Case(folder_name=folder.name, folder_path=str(folder))
    db.add(c); db.commit()
    assert sync_case_folder(db, c, source="test")["docs_added"] == 1
    assert sync_case_folder(db, c, source="test")["docs_added"] == 0  # segunda pasada: nada


def test_elimina_filas_de_archivos_desaparecidos(db, tmp_path):
    folder = tmp_path / "2026-00922 PRUEBA BORRADO"
    folder.mkdir()
    c = Case(folder_name=folder.name, folder_path=str(folder))
    db.add(c); db.commit()
    d = Document(case_id=c.id, filename="fantasma.pdf",
                 file_path=str(folder / "fantasma.pdf"), doc_type="PDF_OTRO")
    db.add(d); db.commit()
    r = sync_case_folder(db, c, source="test")
    assert r["docs_removed"] == 1
    assert db.query(Document).filter(Document.case_id == c.id).count() == 0
