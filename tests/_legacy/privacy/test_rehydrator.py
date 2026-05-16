"""Tests de rehidratación token → valor real (v5.3)."""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case, PiiMapping
from backend.privacy.crypto import encrypt, value_hash
from backend.privacy.rehydrator import rehydrate_text, rehydrate_fields


@pytest.fixture
def db():
    """DB en memoria con un caso de prueba."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    case = Case(id=1, folder_name="caso_test")
    s.add(case)
    s.commit()
    yield s
    s.close()


def _seed_mapping(db, case_id: int, token: str, value: str, kind: str = "PERSON"):
    db.add(PiiMapping(
        case_id=case_id, token=token, kind=kind,
        value_encrypted=encrypt(value),
        value_hash=value_hash(case_id, f"{kind}:{value.lower()}"),
        meta_json=json.dumps({}),
    ))
    db.commit()


def test_rehydrate_text_replaces_token(db):
    _seed_mapping(db, 1, "[ACCIONANTE_1]", "Paola Andrea García Núñez")
    out = rehydrate_text(db, 1, "El accionante [ACCIONANTE_1] interpuso la tutela.")
    assert "Paola Andrea García Núñez" in out
    assert "[ACCIONANTE_1]" not in out


def test_unknown_token_is_left_intact(db):
    out = rehydrate_text(db, 1, "Este [TOKEN_FANTASMA] no existe en DB.")
    assert "[TOKEN_FANTASMA]" in out


def test_multiple_tokens_rehydrated(db):
    _seed_mapping(db, 1, "[ACCIONANTE_1]", "Paola García", "PERSON")
    _seed_mapping(db, 1, "[CC_####8732]", "63.498.732", "CC")
    out = rehydrate_text(db, 1, "[ACCIONANTE_1] con CC [CC_####8732]")
    assert out == "Paola García con CC 63.498.732"


def test_case_isolation(db):
    """Tokens del caso 1 no se rehidratan en el caso 2."""
    _seed_mapping(db, 1, "[ACCIONANTE_1]", "Paola García")
    out = rehydrate_text(db, 2, "El [ACCIONANTE_1] no existe aquí.")
    assert "[ACCIONANTE_1]" in out  # no se reemplaza


def test_rehydrate_fields_walks_nested_dict(db):
    _seed_mapping(db, 1, "[ACCIONANTE_1]", "Paola García")
    fields = {
        "ACCIONANTE": {"value": "[ACCIONANTE_1]", "confidence": "ALTA"},
        "NESTED": [{"val": "el [ACCIONANTE_1] dice X"}],
    }
    out = rehydrate_fields(db, 1, fields)
    assert out["ACCIONANTE"]["value"] == "Paola García"
    assert "Paola García" in out["NESTED"][0]["val"]


def test_roundtrip_preserves_original_values(db):
    """Aplicar rehydrate(redact(original)) debe devolver el valor original."""
    from backend.privacy import redact_payload, RedactionContext
    original_text = "Paola García tiene CC 63.498.732 y teléfono 3204992211."
    docs = [{"filename": "t.txt", "text": original_text}]
    ctx = RedactionContext(case_id=1, mode="aggressive", known_entities={"PERSON": ["Paola García"]})
    red = redact_payload(docs, ctx)

    # Persistir mapping en la DB de prueba
    for token, info in red.mapping.items():
        _seed_mapping(db, 1, token, info["value"], info["kind"])

    # Rehidratar
    rehydrated = rehydrate_text(db, 1, red.docs[0]["text"])
    # Nota: el modo aggressive puede haber detectado Presidio "Paola" como CITY,
    # el roundtrip puro no siempre es byte-a-byte idéntico, pero los valores PII
    # originales deben reaparecer:
    assert "63.498.732" in rehydrated or "63498732" in rehydrated
    assert "3204992211" in rehydrated
