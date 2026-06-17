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

from backend.database.models import Base, Case, Document, Email
from backend.services.sync_service import sync_case_folder, import_email_attachments_to_case


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


# ── Fix A (2026-06-17): assign importa adjuntos huérfanos ────────────────────
# Correos AMBIGUO entran sin caso → adjunto a _emails_sin_clasificar/ sin fila
# Document. Al asignar email→caso, import_email_attachments_to_case lo mueve,
# registra+extrae y vincula email_id.

def test_import_adjunto_huerfano_al_asignar(db, tmp_path):
    unsorted = tmp_path / "_emails_sin_clasificar"
    unsorted.mkdir()
    orphan = unsorted / "RTA EDGAR.pdf"
    orphan.write_bytes(b"%PDF-1.4 contestacion fake con suficiente texto " + b"x" * 200)
    folder = tmp_path / "2026-00125 EDGAR GALVIS"
    folder.mkdir()
    c = Case(folder_name=folder.name, folder_path=str(folder))
    db.add(c); db.commit()
    e = Email(message_id="<m1>", subject="RESPUESTA TUTELA", sender="sed@x.gov.co",
              attachments=[{"filename": orphan.name, "saved_path": str(orphan)}])
    db.add(e); db.commit()

    r = import_email_attachments_to_case(db, e, c, source="test")
    assert r["moved"] == 1 and r["errors"] == 0
    # el archivo se movió a la carpeta del caso y dejó de estar en _emails_sin_clasificar
    assert (folder / "RTA EDGAR.pdf").exists() and not orphan.exists()
    # quedó registrado como Document vinculado al email
    doc = db.query(Document).filter(Document.case_id == c.id,
                                    Document.filename == "RTA EDGAR.pdf").first()
    assert doc is not None and doc.email_id == e.id


def test_import_dedup_sha256_no_duplica(db, tmp_path):
    """Si el caso YA tiene el mismo contenido (p.ej. traído por expediente), el
    huérfano se descarta (dedup por hash), no se duplica."""
    payload = b"%PDF-1.4 mismo contenido " + b"y" * 200
    folder = tmp_path / "2026-00200 PRUEBA DEDUP"
    folder.mkdir()
    (folder / "ya_existe.pdf").write_bytes(payload)  # ya en la carpeta
    c = Case(folder_name=folder.name, folder_path=str(folder))
    db.add(c); db.commit()
    unsorted = tmp_path / "_emails_sin_clasificar"
    unsorted.mkdir()
    dup = unsorted / "RTA_reenviada.pdf"
    dup.write_bytes(payload)  # mismo sha256, otro nombre
    e = Email(message_id="<m2>", subject="RV: RESPUESTA", sender="sed@x.gov.co",
              attachments=[{"filename": dup.name, "saved_path": str(dup)}])
    db.add(e); db.commit()

    r = import_email_attachments_to_case(db, e, c, source="test")
    assert r["moved"] == 0 and r["deduped"] == 1
    assert not dup.exists()  # huérfano dup eliminado
    assert not (folder / "RTA_reenviada.pdf").exists()  # no se duplicó en la carpeta
