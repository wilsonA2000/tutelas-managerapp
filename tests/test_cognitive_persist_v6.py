"""Tests F8: cognitive_persist + idempotencia (Capa 7)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case, AuditLog
from backend.cognition.cognitive_persist import (
    persist_case, snapshot_case, diff_snapshots,
    IDEMPOTENT_FIELDS, DEFAULT_ENTROPY_THRESHOLD,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    s = S()
    yield s
    s.close()


def _good_case(db):
    c = Case(
        folder_name="2026-00001 Test",
        processing_status="PENDIENTE",
        radicado_23_digitos="68001400902720260003400",
        radicado_forest="3410516",
        abogado_responsable="JUAN CRUZ",
        accionante="PAOLA GARCIA",
        accionados="GOBERNACION",
        derecho_vulnerado="Salud",
        juzgado="Juzgado 9",
        ciudad="Bucaramanga",
        fecha_ingreso="15/03/2026",
        asunto="Traslado",
        pretensiones="Reubicar",
        oficina_responsable="DD",
        observaciones="En trámite",
        impugnacion="NO",
        incidente="NO",
    )
    db.add(c); db.commit(); return c


def _messy_case(db):
    c = Case(
        folder_name="2026-00002 Mess",
        processing_status="PENDIENTE",
        impugnacion="NO",
        quien_impugno="Alguien",    # contradicción
        sentido_fallo_2nd="CONFIRMA",  # contradicción
        incidente="NO",
        responsable_desacato="X",    # contradicción
    )
    db.add(c); db.commit(); return c


class TestPersistCompleto:
    def test_caso_limpio_queda_completo(self, db):
        case = _good_case(db)
        rep = persist_case(db, case)
        assert rep.status_after == "COMPLETO"
        assert case.entropy_score is not None
        assert case.convergence_iterations == 1
        assert case.entropy_score <= DEFAULT_ENTROPY_THRESHOLD

    def test_registra_audit_log(self, db):
        case = _good_case(db)
        persist_case(db, case)
        audits = db.query(AuditLog).filter(AuditLog.case_id == case.id,
                                            AuditLog.action == "V6_COGNITIVE_PERSIST").all()
        assert len(audits) == 1
        assert "H=" in audits[0].source


class TestPersistRevision:
    def test_caso_inconsistente_queda_revision(self, db):
        case = _messy_case(db)
        rep = persist_case(db, case)
        assert rep.status_after == "REVISION"
        assert "inconsistente" in rep.reason.lower()

    def test_force_complete_ignora_gate(self, db):
        case = _messy_case(db)
        rep = persist_case(db, case, force_complete=True)
        assert rep.status_after == "COMPLETO"


class TestPhaseReductions:
    def test_phase_entropies_en_audit(self, db):
        case = _good_case(db)
        rep = persist_case(db, case, phase_entropies={
            "capa2_regex": 2.5, "capa4_cognition": 2.1, "capa5_bayes": 1.8,
        })
        assert rep.phase_reductions["capa2_regex"] == 2.5
        audit = db.query(AuditLog).filter(AuditLog.case_id == case.id).first()
        assert "phases" in audit.source


class TestIdempotencia:
    def test_snapshot_captura_campos(self, db):
        case = _good_case(db)
        snap = snapshot_case(case)
        assert "radicado_23_digitos" in snap
        assert snap["accionante"] == "PAOLA GARCIA"

    def test_persist_dos_veces_idempotente(self, db):
        case = _good_case(db)
        persist_case(db, case)
        snap1 = snapshot_case(case)
        # Segunda corrida: no cambia nada estructural
        persist_case(db, case, convergence_iterations=1)
        snap2 = snapshot_case(case)
        d = diff_snapshots(snap1, snap2)
        assert d == {}, f"Esperaba idempotencia, pero diffieren: {d}"

    def test_diff_detecta_cambios(self):
        a = {f: None for f in IDEMPOTENT_FIELDS}
        a["accionante"] = "X"
        b = dict(a)
        b["accionante"] = "Y"
        d = diff_snapshots(a, b)
        assert "accionante" in d
        assert d["accionante"] == ("X", "Y")
