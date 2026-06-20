"""Guard 2026-06-20: cuando F-DEDUP (gmail_monitor.check_inbox) detecta una
copia-duplicada (mismo case_id + subject + sender + fecha±1día bajo distinto
message_id), DEBE marcar el correo de Gmail como leído antes de saltarlo.

Bug histórico: el `continue` de F-DEDUP no llamaba removeLabelIds(UNREAD), así
que la copia-duplicada quedaba no-leída para siempre y cada sync la re-saltaba
(6 correos colgados observados en producción).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.email.gmail_monitor as gm
from backend.database.models import Base, Case, Email


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    # Caso con un email YA ingerido (la copia "original")
    session.add(Case(id=900, folder_name="2026-00900 TEST", accionante="TEST",
                     radicado_23_digitos="68-001-40-09-027-2026-00900-00",
                     processing_status="COMPLETO"))
    session.add(Email(
        id=9001, case_id=900,
        subject="RV: NOTIFICA AUTO ADMISORIO 2026-00900",
        sender="apoyo@santander.gov.co",
        date_received=datetime(2026, 6, 10, 15, 0, 0),
        message_id="<ORIGINAL@exchange>",
        status="ASIGNADO",
    ))
    session.commit()
    yield session
    session.close()


def _mock_service(modify_spy):
    """Servicio Gmail simulado: 1 mensaje no-leído = copia-dup del email 9001
    pero con distinto message_id."""
    svc = MagicMock()
    msgs = svc.users.return_value.messages.return_value
    # list() → un único mensaje, sin nextPageToken
    msgs.list.return_value.execute.return_value = {"messages": [{"id": "GID_DUP"}]}
    # get() → mismo subject/sender/fecha (±1día) que el email 9001, message_id NUEVO
    msgs.get.return_value.execute.return_value = {
        "payload": {
            "headers": [
                {"name": "Subject", "value": "RV: NOTIFICA AUTO ADMISORIO 2026-00900"},
                {"name": "From", "value": "apoyo@santander.gov.co"},
                {"name": "Date", "value": "Wed, 10 Jun 2026 15:30:00 +0000"},
                {"name": "Message-ID", "value": "<COPIA_NUEVA@exchange>"},
            ],
        },
    }
    msgs.modify.return_value.execute.return_value = {}
    msgs.modify.side_effect = modify_spy
    return svc


def test_fdedup_marca_leido_la_copia_duplicada(db, monkeypatch):
    calls = []

    def modify_spy(*args, **kwargs):
        calls.append(kwargs)
        return MagicMock(execute=lambda: {})

    svc = _mock_service(modify_spy)
    monkeypatch.setattr(gm, "_get_gmail_service", lambda: svc)
    # Forzar resolución determinista al caso 900 vía fallback secuencial
    monkeypatch.setattr(gm, "resolve_radicado", lambda s, b: {
        "radicado_23": "68-001-40-09-027-2026-00900-00",
        "radicado_corto": "2026-00900",
    })
    import backend.email.case_lookup_cache as clc
    monkeypatch.setattr(clc, "get_cache", lambda: MagicMock(is_built=False))
    monkeypatch.setattr(gm, "match_to_case",
                        lambda *a, **k: db.query(Case).filter(Case.id == 900).first())

    results = gm.check_inbox(db)

    # No se creó un Email duplicado
    assert db.query(Email).count() == 1
    # El correo-copia NO entró como resultado nuevo (fue saltado)
    assert all(r.get("subject") != "RV: NOTIFICA AUTO ADMISORIO 2026-00900" or r.get("accion") != "CASO_EXISTENTE"
               for r in results)
    # CLAVE: se marcó leído (removeLabelIds UNREAD) sobre el mensaje GID_DUP
    marcado = [c for c in calls
               if c.get("id") == "GID_DUP"
               and "UNREAD" in (c.get("body", {}) or {}).get("removeLabelIds", [])]
    assert marcado, f"F-DEDUP no marcó leído la copia-duplicada. modify calls={calls}"
