"""Tests para backend/email/matcher.py (v5.4.4).

Cubre los 6 escenarios críticos + 6 variantes.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.database.models import Base, Case, Email, PiiMapping
from backend.email.case_lookup_cache import CaseLookupCache, hash_cc
from backend.email.matcher import (
    EmailSignals,
    MatchResult,
    resolve_thread_parent,
    score_case_match,
)


# ─────────────────────────────────────────────────────────────
# Fixture DB en memoria con casos de prueba
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Casos de prueba
    cases = [
        Case(
            id=100,
            folder_name="2026-00100 JUAN PEREZ",
            accionante="JUAN CARLOS PEREZ GARCIA",
            radicado_23_digitos="68-001-40-09-027-2026-00100-00",
            radicado_forest="20260019953",
            processing_status="COMPLETO",
        ),
        Case(
            id=200,
            folder_name="2026-00200 MARIA LOPEZ",
            accionante="MARIA LOPEZ RODRIGUEZ",
            radicado_23_digitos="68-001-41-05-002-2026-00200-00",
            radicado_forest="20260020000",
            processing_status="COMPLETO",
        ),
        # Caso que comparte year:seq con otro pero en juzgado distinto (F7)
        Case(
            id=300,
            folder_name="2026-00100 PEDRO RAMIREZ",
            accionante="PEDRO RAMIREZ SILVA",
            radicado_23_digitos="54-001-41-05-002-2026-00100-00",  # Cúcuta
            radicado_forest="20260030000",
            processing_status="COMPLETO",
        ),
        # Caso DUPLICATE_MERGED (no debe aparecer en cache)
        Case(
            id=400,
            folder_name="2026-00400 MERGED",
            radicado_23_digitos="68-001-40-09-027-2026-00400-00",
            processing_status="DUPLICATE_MERGED",
        ),
    ]
    for c in cases:
        session.add(c)

    # PII mapping para CC lookup
    cc_hash_juan = hash_cc("1098765432")
    session.add(PiiMapping(
        case_id=100,
        token="[CC_####5432]",
        kind="CC",
        value_encrypted=b"fake",
        value_hash=cc_hash_juan,
        meta_json="{}",
    ))

    # Email padre para thread test
    session.add(Email(
        id=1,
        message_id="<msg-original-2026@gmail.com>",
        subject="Notificación tutela original",
        sender="juzgado@judicatura.gov.co",
        case_id=100,
        status="ASIGNADO",
    ))

    session.commit()
    yield session
    session.close()


@pytest.fixture
def cache(db):
    c = CaseLookupCache()
    c.build(db)
    return c


# ─────────────────────────────────────────────────────────────
# Cache
# ─────────────────────────────────────────────────────────────


class TestCacheBuild:
    def test_excluye_duplicate_merged(self, cache):
        assert cache.lookup_by_rad23("68-001-40-09-027-2026-00400-00") is None

    def test_indexa_rad23(self, cache):
        assert cache.lookup_by_rad23("68-001-40-09-027-2026-00100-00") == 100

    def test_indexa_forest(self, cache):
        assert cache.lookup_by_forest("20260019953") == 100

    def test_indexa_rad_corto_derivado(self, cache):
        # 2026-00100 aparece en 2 casos (100 Bucaramanga y 300 Cúcuta).
        # El dict solo puede guardar 1 — verificamos que al menos uno queda.
        # Para lookups únicos F7 usa rad23 o juzgado_code (desambiguan).
        assert cache.lookup_by_rad_corto("2026-00100") in (100, 300)
        # rad_corto único queda bien indexado
        assert cache.lookup_by_rad_corto("2026-00200") == 200

    def test_indexa_cc_hash(self, cache):
        assert cache.lookup_by_cc("1098765432") == 100

    def test_cc_inexistente(self, cache):
        assert cache.lookup_by_cc("9999999999") is None


# ─────────────────────────────────────────────────────────────
# Scoring — un solo criterio
# ─────────────────────────────────────────────────────────────


class TestScoringUnica:
    def test_solo_rad23(self, db, cache):
        s = EmailSignals(rad23="68-001-40-09-027-2026-00100-00")
        r = score_case_match(db, cache, s)
        assert r.case_id == 100
        assert r.score == 70  # v6.0.1: rad23 alone = auto-match
        assert r.confidence == "HIGH"
        assert "rad23" in r.breakdown

    def test_solo_forest_remitente_generico(self, db, cache):
        s = EmailSignals(forest="20260019953", sender="apoyojur@santander.gov.co")
        r = score_case_match(db, cache, s)
        assert r.case_id == 100
        assert r.score == 20  # v6.0.1: WEIGHT_FOREST_GENERIC bumped 15→20
        assert r.confidence == "LOW"

    def test_forest_con_tutelas_sender(self, db, cache):
        s = EmailSignals(forest="20260019953", sender="tutelas@santander.gov.co")
        r = score_case_match(db, cache, s)
        assert r.case_id == 100
        assert r.score == 50  # v6.0.1: WEIGHT_FOREST_VERIFIED_SENDER bumped 25→50

    def test_solo_cc(self, db, cache):
        s = EmailSignals(cc_accionante="1098765432")
        r = score_case_match(db, cache, s)
        assert r.case_id == 100
        assert r.score == 20

    def test_ningun_match(self, db, cache):
        s = EmailSignals(rad23="68-001-40-09-027-2099-99999-00")
        r = score_case_match(db, cache, s)
        assert r.case_id is None
        assert r.confidence == "NONE"


# ─────────────────────────────────────────────────────────────
# Scoring — múltiples criterios
# ─────────────────────────────────────────────────────────────


class TestScoringMultiple:
    def test_rad23_mas_cc_high(self, db, cache):
        """rad23 (40) + CC (20) + nombre (10) = 70 → HIGH."""
        s = EmailSignals(
            rad23="68-001-40-09-027-2026-00100-00",
            cc_accionante="1098765432",
            accionante_name="JUAN CARLOS PEREZ GARCIA",
        )
        r = score_case_match(db, cache, s)
        assert r.case_id == 100
        assert r.score >= 70
        assert r.confidence == "HIGH"
        assert r.is_auto_match

    def test_rad23_mas_forest_tutelas_sender(self, db, cache):
        """v6.0.1: rad23 (70) + forest_verified (50) = 120 → HIGH (ambos auto-match)."""
        s = EmailSignals(
            rad23="68-001-40-09-027-2026-00100-00",
            forest="20260019953",
            sender="tutelas@santander.gov.co",
        )
        r = score_case_match(db, cache, s)
        assert r.case_id == 100
        assert r.score == 120
        assert r.confidence == "HIGH"

    def test_thread_parent_solo(self, db, cache):
        """v6.0.1: Thread parent +70 = HIGH (antes 50, MEDIUM)."""
        s = EmailSignals(thread_parent_case_id=100)
        r = score_case_match(db, cache, s)
        assert r.case_id == 100
        assert r.score == 70
        assert r.confidence == "HIGH"

    def test_thread_mas_rad23_auto(self, db, cache):
        """v6.0.1: Thread (70) + rad23 (70) = 140 HIGH."""
        s = EmailSignals(
            thread_parent_case_id=100,
            rad23="68-001-40-09-027-2026-00100-00",
        )
        r = score_case_match(db, cache, s)
        assert r.case_id == 100
        assert r.score == 140
        assert r.confidence == "HIGH"


# ─────────────────────────────────────────────────────────────
# F7 — juzgado_code rechaza rad_corto homónimo
# ─────────────────────────────────────────────────────────────


class TestF7Guard:
    def test_rad_corto_homonimo_diferente_juzgado_rechazado(self, db, cache):
        """Caso 100 (Bucaramanga) y 300 (Cúcuta) comparten year:seq 2026-00100.
        Email con rad23 de Cúcuta debe matchear 300, NO 100."""
        s = EmailSignals(
            rad23="54-001-41-05-002-2026-00100-00",
            rad_corto="2026-00100",
        )
        r = score_case_match(db, cache, s)
        # rad23 lookup exacto → case 300 (Cúcuta). rad_corto 2026-00100 → cache
        # tiene uno de los dos (el primero indexado). El F7 guard debe impedir
        # que el rad_corto match sume si es a case distinto.
        assert r.case_id == 300

    def test_rad_corto_sin_rad23_cualquier_caso(self, db, cache):
        """Sin rad23, rad_corto sí suma WEIGHT_RAD_CORTO_SIN_JUZGADO."""
        s = EmailSignals(rad_corto="2026-00200")
        r = score_case_match(db, cache, s)
        assert r.case_id == 200
        assert r.score == 12  # v6.0.1: WEIGHT_RAD_CORTO_SIN_JUZGADO bumped 7→12


# ─────────────────────────────────────────────────────────────
# Threading resolver
# ─────────────────────────────────────────────────────────────


class TestThreadingResolver:
    def test_in_reply_to_hereda_case(self, db):
        """Email B con In-Reply-To apuntando al email original ya asignado."""
        cid = resolve_thread_parent(
            db,
            in_reply_to="<msg-original-2026@gmail.com>",
            references="",
        )
        assert cid == 100

    def test_references_busca_toda_la_cadena(self, db):
        """References con múltiples message_ids separados por espacio."""
        cid = resolve_thread_parent(
            db,
            in_reply_to="",
            references="<otro-que-no-existe@x.com> <msg-original-2026@gmail.com>",
        )
        assert cid == 100

    def test_headers_vacios(self, db):
        assert resolve_thread_parent(db, "", "") is None

    def test_mensaje_desconocido(self, db):
        assert resolve_thread_parent(db, "<nonexistent@x.com>", "") is None


# ─────────────────────────────────────────────────────────────
# MatchResult serialización
# ─────────────────────────────────────────────────────────────


class TestMatchResult:
    def test_to_signals_json_valido(self, db, cache):
        s = EmailSignals(rad23="68-001-40-09-027-2026-00100-00")
        r = score_case_match(db, cache, s)
        j = r.to_signals_json()
        import json as _json
        parsed = _json.loads(j)
        assert parsed["score"] == 70  # v6.0.1
        assert parsed["confidence"] == "HIGH"
        assert "rad23" in parsed["breakdown"]
