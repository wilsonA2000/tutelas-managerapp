"""Tests para backend/email/matcher.py (v5.4.4).

Cubre los 6 escenarios críticos + 6 variantes.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.database.models import Base, Case, Email
from backend.email.case_lookup_cache import CaseLookupCache
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

    def test_cc_lookup_vestigial(self, cache):
        # La capa PII se retiró → el índice by_cc_hash queda vacío permanentemente.
        assert cache.lookup_by_cc("1098765432") is None
        assert cache.lookup_by_cc("9999999999") is None

    def test_no_colapsa_consecutivos_contiguos(self, db):
        """Regresión 2026-05-15: el bug histórico usaba `[:20]` como key del
        by_rad23, colapsando rads que difieren solo en el último dígito del
        consec (00011 ↔ 00012, 00100 ↔ 00101, …). Fix: usar `[:21]`.

        Aquí montamos 2 cases con consecutivos contiguos en el mismo despacho
        y verificamos que cada rad-23 hace lookup a su case correcto.
        """
        # Limpieza: borrar cases previos del fixture y montar 2 con consecs
        # contiguos en el mismo despacho.
        db.query(Case).delete()
        db.commit()
        db.add(Case(
            id=500, folder_name="2026-00500 ANA TORRES",
            radicado_23_digitos="68-001-40-09-027-2026-00500-00",
            processing_status="COMPLETO",
        ))
        db.add(Case(
            id=501, folder_name="2026-00501 LUIS GARCIA",
            radicado_23_digitos="68-001-40-09-027-2026-00501-00",  # difiere SOLO en último dígito del consec
            processing_status="COMPLETO",
        ))
        db.commit()
        c = CaseLookupCache()
        c.build(db)
        # Cada uno hace lookup a su propio case (no se colapsan al mismo bucket)
        assert c.lookup_by_rad23("68001400902720260050000") == 500
        assert c.lookup_by_rad23("68001400902720260050100") == 501


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

    def test_solo_cc_ya_no_matchea(self, db, cache):
        # La señal por CC dependía de pii_mappings (capa PII retirada) → ya no produce match.
        s = EmailSignals(cc_accionante="1098765432")
        r = score_case_match(db, cache, s)
        assert r.case_id is None
        assert r.score == 0

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


class TestConflictGuard:
    """#3.4: guard de conflicto de radicado en el scoring."""

    def test_rad23_no_se_degrada_pese_a_forest_de_otro_caso(self, db, cache):
        """Un auto-match por rad23 (autoritativo) NO se degrada aunque el email
        traiga un forest que apunta a OTRO caso. El rad23 manda."""
        s = EmailSignals(
            rad23="68-001-40-09-027-2026-00100-00",  # → caso 100
            forest="20260020000",                      # → caso 200
            sender="tutelas@santander.gov.co",
        )
        r = score_case_match(db, cache, s)
        assert r.case_id == 100
        assert r.confidence == "HIGH"
        assert "rad_conflict_downgrade" not in r.breakdown

    def test_thread_parent_no_se_degrada(self, db, cache):
        """Un match por thread (conversación) es autoritativo: aunque el rad del
        email apunte a otro caso, no se degrada (es una respuesta del hilo)."""
        s = EmailSignals(
            thread_parent_case_id=100,
            rad_corto="2026-00200",  # apunta a caso 200, distinto
        )
        r = score_case_match(db, cache, s)
        assert r.case_id == 100
        assert r.confidence == "HIGH"
        assert "rad_conflict_downgrade" not in r.breakdown


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


class TestResolveRadicado:
    """resolve_radicado: jerarquía anti-conflación subject↔body (2026-05-22).

    Bug raíz: el rad ajeno de la cadena reenviada le ganaba al rad del subject.
    """

    def test_bug_conflacion_0053_0080(self):
        """El short-rad del subject gana al short-rad ajeno del body (sin rad23)."""
        from backend.email.gmail_monitor import resolve_radicado
        r = resolve_radicado(
            "RESPUESTA ACCIÓN DE TUTELA 2026-0053 DESPUES DE LA NULIDAD",
            "De: juzgado ref 2026-00080 Yennifer y 2026-00072 y 2026-00172",
        )
        assert r["radicado_corto"] == "2026-00053"

    def test_rad23_body_gana_a_short_rad_subject(self):
        """rad23 del body manda (ID nacional) — corrige typos de año del subject."""
        from backend.email.gmail_monitor import resolve_radicado
        r = resolve_radicado(
            "RESPUESTA REQUERIMIENTO 2026-0066",  # año equivocado en subject
            "Notificación rad 68266-40-89-001-2025-00066-00 del juzgado",
        )
        assert r["radicado_23"] == "68266-40-89-001-2025-00066-00"
        assert r["radicado_corto"] == "2025-00066"

    def test_rad23_subject_manda(self):
        from backend.email.gmail_monitor import resolve_radicado
        # rad23 continuo en el subject gana sobre cualquier rad del body.
        r = resolve_radicado("Fallo 680014009027202600100", "ref otra tutela 2026-00080")
        assert r["radicado_23"] == "680014009027202600100"
        assert r["radicado_corto"] == "2026-00100"

    def test_subject_sin_rad_usa_body(self):
        from backend.email.gmail_monitor import resolve_radicado
        r = resolve_radicado("RV: NOTIFICACIÓN JUDICIAL", "Auto admite tutela 2026-00170 del juzgado")
        assert r["radicado_corto"] == "2026-00170"

    def test_sin_rad_en_ningun_lado(self):
        from backend.email.gmail_monitor import resolve_radicado
        r = resolve_radicado("RV: saludos", "sin radicado alguno")
        assert r["radicado_corto"] == "" and r["radicado_23"] == ""

    def test_ignora_linea_caso_del_md(self):
        """extract_radicado ignora la anotación **Caso:** (self-referencial) y
        toma el rad del cuerpo real del email (#3.3)."""
        from backend.email.gmail_monitor import extract_radicado
        md = (
            "# RESPUESTA TUTELA\n\n"
            "**De:** juzgado@x\n"
            "**Caso:** 2026-00080 YENNIFER\n"   # anotación del sistema (otro caso)
            "\n---\n\n"
            "Notificación del fallo de tutela 2026-00053 del accionante Edgar."
        )
        assert extract_radicado(md)["radicado_corto"] == "2026-00053"

    def test_rad23_segmentado_con_prefijo_municipio(self):
        """#6: el formato segmentado 'DANE-juzgado-secc-año-consec' (juzgados penales/
        promiscuos) ahora SÍ captura el rad23 con prefijo de municipio, y el ' NI ####'
        (nro interno) queda fuera. Antes devolvía rad23='' y solo el corto."""
        from backend.email.gmail_monitor import extract_radicado
        from backend.email.rad_utils import juzgado_code
        r = extract_radicado("Radicado: 68001-3107-001-2026-00015 NI 6539")
        assert r["radicado_corto"] == "2026-00015"
        assert juzgado_code(r["radicado_23"]) == "680013107001"   # municipio 68001 desambigua

    def test_rad23_continuo_sin_regresion(self):
        """El rad23 continuo (sin separadores) sigue capturándose igual."""
        from backend.email.gmail_monitor import extract_radicado
        r = extract_radicado("Radicado 68079408900120260003700")
        assert r["radicado_corto"] == "2026-00037"
        assert "68079408900120260003700" in r["radicado_23"]


# ─────────────────────────────────────────────────────────────
# Fase 4: rad_corto compartido entre municipios (anti-conflación)
# Fixture: case 100 (Bucaramanga 68001) y case 300 (Cúcuta 54001) comparten
# el rad_corto "2026-00100" en juzgados distintos.
# ─────────────────────────────────────────────────────────────


class TestRadCortoAmbiguo:
    def test_cache_candidatos_multi(self, cache):
        # El rad_corto compartido devuelve AMBOS casos; el único, solo uno.
        assert cache.rad_corto_candidates("2026-00100") == {100, 300}
        assert cache.rad_corto_candidates("2026-00200") == {200}
        assert cache.rad_corto_candidates("2099-99999") == set()

    def test_cache_juzgado_of(self, cache):
        assert cache.juzgado_of(100) == "680014009027"
        assert cache.juzgado_of(300) == "540014105002"
        assert cache.juzgado_of(999) == ""

    def test_ambiguo_sin_rad23_no_autoasigna(self, db, cache):
        # Email solo con el rad_corto compartido y SIN rad23 → no se puede
        # desambiguar el municipio → NO auto-asignar (esto causaba la conflación).
        s = EmailSignals(rad_corto="2026-00100")
        r = score_case_match(db, cache, s)
        assert r.case_id is None
        assert r.confidence == "NONE"

    def test_no_ambiguo_sin_rad23_si_asigna(self, db, cache):
        # rad_corto que solo tiene un caso → sí se asigna (comportamiento previo).
        s = EmailSignals(rad_corto="2026-00200")
        r = score_case_match(db, cache, s)
        assert r.case_id == 200
        assert "rad_corto" in r.breakdown

    def test_rad23_desambigua_a_bucaramanga(self, db, cache):
        # Mismo rad_corto compartido, pero el rad23 del email es de Bucaramanga
        # → debe resolver al caso 100, NUNCA al 300 (Cúcuta).
        s = EmailSignals(rad23="68-001-40-09-027-2026-00100-00", rad_corto="2026-00100")
        r = score_case_match(db, cache, s)
        assert r.case_id == 100

    def test_rad23_desambigua_a_cucuta(self, db, cache):
        s = EmailSignals(rad23="54-001-41-05-002-2026-00100-00", rad_corto="2026-00100")
        r = score_case_match(db, cache, s)
        assert r.case_id == 300

    def test_evict_limpia_candidatos(self, db, cache):
        # Al desindexar un caso, sale de by_rad_corto_all y juzgado12.
        cache._evict_case_no_lock(300)
        assert cache.rad_corto_candidates("2026-00100") == {100}
        assert cache.juzgado_of(300) == ""
