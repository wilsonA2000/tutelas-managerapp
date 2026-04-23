"""Tests F7: live_consolidator (Capa 6).

Usa DB en memoria (SQLite :memory:) para tests aislados.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case, Document, Email, AuditLog
from backend.cognition.live_consolidator import (
    find_parent_for_orphan, find_duplicates_by_rad23,
    apply_consolidation, consolidate_case,
    ConsolidationCandidate, MERGE_AUTO_THRESHOLD,
    _fuzzy_name_score,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def _case(db, **kw):
    c = Case(
        folder_name=kw.get("folder_name", "F"),
        radicado_23_digitos=kw.get("radicado_23_digitos", ""),
        accionante=kw.get("accionante", ""),
        juzgado=kw.get("juzgado", ""),
        ciudad=kw.get("ciudad", ""),
        processing_status=kw.get("processing_status", "COMPLETO"),
        origen=kw.get("origen", "TUTELA"),
    )
    db.add(c)
    db.commit()
    return c


class TestFuzzyScore:
    def test_mismos_nombres_score_1(self):
        assert _fuzzy_name_score("Paola García", "Paola García") == 1.0

    def test_muy_distintos(self):
        assert _fuzzy_name_score("Juan Pérez", "Carmen López") < 0.2


class TestFindParentForOrphan:
    def test_huerfano_encuentra_padre_por_rad23_y_accionante(self, db):
        parent = _case(db, folder_name="2025-00112 Garnica",
                       radicado_23_digitos="68001310300220250011200",
                       accionante="Gabriel Garnica Sarmiento",
                       juzgado="Juzgado Segundo Civil",
                       origen="TUTELA")
        orphan = _case(db, folder_name="2025-00012 Garnica",
                       radicado_23_digitos="68001310300220250011200",  # mismo rad23
                       accionante="Gabriel Garnica Sarmiento",
                       juzgado="Juzgado Segundo Civil",
                       origen="INCIDENTE_HUERFANO")
        cand = find_parent_for_orphan(db, orphan)
        assert cand is not None
        assert cand.parent_case_id == parent.id
        assert cand.score >= MERGE_AUTO_THRESHOLD

    def test_no_huerfano_retorna_none(self, db):
        case = _case(db, origen="TUTELA")
        assert find_parent_for_orphan(db, case) is None

    def test_huerfano_sin_candidato_retorna_none(self, db):
        orphan = _case(db, origen="INCIDENTE_HUERFANO",
                       radicado_23_digitos="68001310300220250099900",
                       accionante="Unique Name")
        assert find_parent_for_orphan(db, orphan) is None


class TestFindDuplicatesByRad23:
    def test_dos_casos_con_mismo_rad23_y_accionante(self, db):
        c1 = _case(db, folder_name="A", radicado_23_digitos="68001310300220250011200",
                   accionante="Juan Pérez")
        c2 = _case(db, folder_name="B", radicado_23_digitos="68001310300220250011200",
                   accionante="Juan Pérez")
        cand = find_duplicates_by_rad23(db, c2)
        assert cand is not None
        assert cand.parent_case_id == min(c1.id, c2.id)
        assert cand.score >= MERGE_AUTO_THRESHOLD


class TestApplyConsolidation:
    def test_mueve_documentos_y_marca_duplicate_merged(self, db):
        src = _case(db, folder_name="A", radicado_23_digitos="68001310300220250011200",
                    accionante="Juan Pérez")
        dst = _case(db, folder_name="B", radicado_23_digitos="68001310300220250011200",
                    accionante="Juan Pérez")
        # Agregar docs al src
        db.add(Document(case_id=src.id, filename="d1.pdf", file_path="/x/d1.pdf"))
        db.add(Document(case_id=src.id, filename="d2.pdf", file_path="/x/d2.pdf"))
        db.commit()

        cand = ConsolidationCandidate(
            case_id=src.id, parent_case_id=dst.id,
            kind="duplicate_merge", score=0.9, reasons=["test"],
        )
        ok = apply_consolidation(db, cand)
        assert ok is True
        # Src marcado
        db.refresh(src)
        assert src.processing_status == "DUPLICATE_MERGED"
        # Docs movidos
        docs_src = db.query(Document).filter(Document.case_id == src.id).count()
        docs_dst = db.query(Document).filter(Document.case_id == dst.id).count()
        assert docs_src == 0
        assert docs_dst == 2
        # Audit log registrado
        audit = db.query(AuditLog).filter(AuditLog.case_id == src.id,
                                           AuditLog.action == "V6_LIVE_CONSOLIDATE").first()
        assert audit is not None


class TestConsolidateCase:
    def test_huerfano_con_match_alto_se_consolida(self, db):
        parent = _case(db, folder_name="2025-00112",
                       radicado_23_digitos="68001310300220250011200",
                       accionante="Gabriel Garnica",
                       origen="TUTELA")
        orphan = _case(db, folder_name="2025-00012",
                       radicado_23_digitos="68001310300220250011200",
                       accionante="Gabriel Garnica",
                       origen="INCIDENTE_HUERFANO")
        db.add(Document(case_id=orphan.id, filename="inc.pdf", file_path="/x/inc.pdf"))
        db.commit()

        report = consolidate_case(db, orphan)
        assert len(report.applied) == 1
        assert report.applied[0].kind == "orphan_to_parent"
        db.refresh(orphan)
        assert orphan.processing_status == "DUPLICATE_MERGED"
