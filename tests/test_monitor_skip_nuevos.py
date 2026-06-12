"""Ciclo de vida post-ingesta (2026-06-12): el monitor NO extrae casos nuevos.

- Caso NUEVO (accion=CASO_NUEVO en la corrida) → candidata, sin _v9_extract.
- Caso EXISTENTE actualizado → extracción inmediata + traza datada en obs.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case
from backend.main import _post_ingest_split, _extract_updated_case


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _mk(db, folder):
    c = Case(folder_name=folder)
    db.add(c); db.commit()
    return c


def test_split_nuevo_vs_actualizado(db):
    nuevo = _mk(db, "2026-00910 CASO NUEVO")
    viejo = _mk(db, "2026-00911 CASO VIEJO")
    emails = [
        {"matched_case": nuevo.folder_name, "accion": "CASO_NUEVO", "adjuntos_guardados": 2},
        {"matched_case": viejo.folder_name, "accion": "CASO_EXISTENTE", "adjuntos_guardados": 1},
        {"matched_case": None, "accion": "AMBIGUO"},  # sin caso → ignorado
    ]
    nuevos, actualizados = _post_ingest_split(db, emails)
    assert [c.id for c, _ in nuevos] == [nuevo.id]
    assert [c.id for c, _ in actualizados] == [viejo.id]
    # docs = adjuntos + 1 (el .md del email)
    assert nuevos[0][1] == 3 and actualizados[0][1] == 2


def test_caso_nuevo_con_segundo_email_sigue_siendo_nuevo(db):
    # Si el caso se creó en esta corrida y luego recibió otro correo en la misma
    # corrida, sigue siendo NUEVO (no se extrae hasta selección manual).
    c = _mk(db, "2026-00912 RECIEN CREADO")
    emails = [
        {"matched_case": c.folder_name, "accion": "CASO_NUEVO", "adjuntos_guardados": 0},
        {"matched_case": c.folder_name, "accion": "CASO_EXISTENTE", "adjuntos_guardados": 1},
    ]
    nuevos, actualizados = _post_ingest_split(db, emails)
    assert [x.id for x, _ in nuevos] == [c.id]
    assert actualizados == []


def test_actualizado_corre_extraccion_y_deja_traza(db):
    c = _mk(db, "2026-00913 EXISTENTE")
    fake_stats = {"ai_fields_extracted": 5, "documents_extracted": 2,
                  "changes": {"sentido_fallo_1st": {"old": None, "new": "CONCEDE"},
                              "fecha_fallo_1st": {"old": None, "new": "10/06/2026"},
                              "__abogado_canonical": {"old": None, "new": "X"}}}
    with patch("backend.main._v9_extract", return_value=fake_stats) as mock_ext:
        stats = _extract_updated_case(db, c, n_docs=2)
    mock_ext.assert_called_once()
    assert stats["campos_escritos"] == 2  # los __internos no cuentan
    obs = c.observaciones or ""
    assert "Ingesta Gmail: 2 doc(s) nuevos" in obs
    assert "sentido_fallo_1st" in obs and "fecha_fallo_1st" in obs


def test_actualizado_sin_cambios_no_ensucia_obs(db):
    c = _mk(db, "2026-00914 SIN CAMBIOS")
    c.observaciones = "nota previa"
    db.commit()
    with patch("backend.main._v9_extract", return_value={"changes": {}}):
        stats = _extract_updated_case(db, c, n_docs=1)
    assert stats["campos_escritos"] == 0
    assert c.observaciones == "nota previa"  # sin ruido
