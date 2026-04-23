"""Tests F6: procedural_timeline + case_classifier (Capa 4)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.cognition.procedural_timeline import (
    build_timeline, DOC_TYPE_TO_POSITION, _refine_position, _parse_date,
)
from backend.cognition.case_classifier import classify_case, INCIDENT_STATES, CASE_ORIGINS


class _Doc:
    def __init__(self, filename, doc_type, text=""):
        self.filename = filename
        self.doc_type = doc_type
        self.extracted_text = text


class _Case:
    def __init__(self, id_, folder, docs):
        self.id = id_
        self.folder_name = folder
        self.documents = docs


class TestPositionRefinement:
    def test_auto_admisorio_por_tipo(self):
        pos, _ = _refine_position("PDF_AUTO_ADMISORIO", "AutoAdmite.pdf", "")
        assert pos == "AUTO_ADMISORIO"

    def test_fallo_2nd_por_keyword(self):
        pos, signals = _refine_position("PDF_SENTENCIA", "Fallo.pdf",
                                        "SEGUNDA INSTANCIA CONFIRMA fallo de primera")
        assert pos == "FALLO_2ND"
        assert any("segunda" in s for s in signals)

    def test_sancion_por_filename(self):
        pos, _ = _refine_position("PDF_OTRO", "SancionaDesacato.pdf", "")
        assert pos == "SANCION"

    def test_grado_consulta(self):
        pos, _ = _refine_position("PDF_OTRO", "OficioRemite.pdf",
                                  "se remite en GRADO DE CONSULTA")
        assert pos == "REMITE_CONSULTA"

    def test_vincula(self):
        pos, _ = _refine_position("PDF_OTRO", "AutoVincula.pdf",
                                  "se dispone vincular al tercero")
        assert pos == "AUTO_VINCULA"


class TestParseDate:
    def test_fecha_numerica(self):
        assert _parse_date("Bucaramanga, 15/03/2026") == "15/03/2026"
        assert _parse_date("fecha 3-4-2026") == "03/04/2026"

    def test_sin_fecha(self):
        assert _parse_date("sin fechas") is None


class TestBuildTimeline:
    def test_caso_tutela_completa(self):
        docs = [
            _Doc("AutoAdmite.pdf", "PDF_AUTO_ADMISORIO", "15/01/2026"),
            _Doc("Respuesta.docx", "DOCX_RESPUESTA", "20/01/2026"),
            _Doc("Fallo.pdf", "PDF_SENTENCIA", "01/02/2026"),
        ]
        case = _Case(1, "2026-00001", docs)
        tl = build_timeline(case)
        positions = tl.positions()
        assert "AUTO_ADMISORIO" in positions
        assert "RESPUESTA" in positions
        assert "FALLO_1ST" in positions
        # Ordenado por fecha
        assert tl.events[0].doc_filename == "AutoAdmite.pdf"
        assert tl.events[-1].doc_filename == "Fallo.pdf"

    def test_caso_incidente_huerfano(self):
        docs = [
            _Doc("SolicitudDesacato.pdf", "PDF_INCIDENTE", "15/04/2026"),
            _Doc("Cumplimiento.docx", "DOCX_CUMPLIMIENTO", "20/04/2026"),
        ]
        case = _Case(2, "2025-00050", docs)
        tl = build_timeline(case)
        assert "INCIDENTE" in tl.positions()
        assert "AUTO_ADMISORIO" not in tl.positions()


class TestCaseClassifier:
    def test_clasifica_tutela(self):
        docs = [_Doc("AutoAdmite.pdf", "PDF_AUTO_ADMISORIO", "")]
        case = _Case(1, "f", docs)
        tl = build_timeline(case)
        c = classify_case(case, tl)
        assert c.origen == "TUTELA"
        assert c.estado_incidente == "N/A"

    def test_clasifica_incidente_huerfano(self):
        docs = [_Doc("SolDesacato.pdf", "PDF_INCIDENTE", "")]
        case = _Case(2, "f", docs)
        tl = build_timeline(case)
        c = classify_case(case, tl)
        assert c.origen == "INCIDENTE_HUERFANO"
        assert c.has_incidente is True
        assert c.estado_incidente == "ACTIVO"

    def test_clasifica_con_sancion(self):
        docs = [
            _Doc("AutoAdmite.pdf", "PDF_AUTO_ADMISORIO", ""),
            _Doc("Sancion.pdf", "PDF_OTRO", "se SANCIONA con arresto"),
        ]
        case = _Case(3, "f", docs)
        tl = build_timeline(case)
        c = classify_case(case, tl)
        assert c.origen == "TUTELA"
        assert c.estado_incidente == "EN_SANCION"

    def test_clasifica_ambiguo(self):
        docs = [_Doc("Email_x.md", "EMAIL_MD", "")]
        case = _Case(4, "f", docs)
        tl = build_timeline(case)
        c = classify_case(case, tl)
        assert c.origen == "AMBIGUO"

    def test_valores_enum_validos(self):
        docs = [_Doc("AutoAdmite.pdf", "PDF_AUTO_ADMISORIO", "")]
        case = _Case(1, "f", docs)
        tl = build_timeline(case)
        c = classify_case(case, tl)
        assert c.origen in CASE_ORIGINS
        assert c.estado_incidente in INCIDENT_STATES
