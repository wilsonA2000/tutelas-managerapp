"""Tests F4: Bayesian assignment — heurísticas H1-H11 del plan v6.0."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.extraction.ir_models import DocumentIR, DocumentZone
from backend.cognition.bayesian_assignment import (
    infer_assignment, AssignmentEvidence,
    OK_THRESHOLD, NEG_THRESHOLD, DEFAULT_PRIOR,
)


class _Case:
    def __init__(self, **kw):
        self.id = kw.get("id", 1)
        self.radicado_23_digitos = kw.get("radicado_23_digitos", "")
        self.radicado_forest = kw.get("radicado_forest", "")
        self.accionante = kw.get("accionante", "")
        self.accionados = kw.get("accionados", "")
        self.juzgado = kw.get("juzgado", "")
        self.abogado_responsable = kw.get("abogado_responsable", "")
        self.folder_name = kw.get("folder_name", "")
        self.observaciones = kw.get("observaciones", "")


def _ir(zones, visual=None, filename="doc.pdf"):
    return DocumentIR(
        filename=filename, doc_type="PDF_OTRO", priority=5,
        zones=zones, full_text="\n".join(z.text for z in zones),
        visual_signature=visual,
    )


class TestMathBayes:
    def test_prior_sin_evidencia_da_prior(self):
        e = AssignmentEvidence(prior=0.7)
        assert abs(e.posterior() - 0.7) < 1e-9

    def test_lr_grande_empuja_arriba(self):
        e = AssignmentEvidence(prior=0.7)
        e.add("x", 100.0, pro=True)
        assert e.posterior() > 0.99

    def test_lr_pequeno_empuja_abajo(self):
        e = AssignmentEvidence(prior=0.7)
        e.add("x", 0.01, pro=False)
        assert e.posterior() < 0.05


class TestEmailMarkdown:
    def test_email_md_siempre_ok(self):
        case = _Case(radicado_23_digitos="68001400902720260003400")
        ir = _ir([], filename="Email_20260422_xxx.md")
        v = infer_assignment(case, ir)
        assert v.verdict == "OK"
        assert v.posterior > 0.99


class TestH1MembreteInstitucional:
    def test_doc_con_logo_repetido_y_rad_coincidente(self):
        case = _Case(radicado_23_digitos="68001400902720260003400")
        z = DocumentZone(zone_type="HEADER", text="Juzgado Noveno 68001400902720260003400")
        ir = _ir([z], visual={"has_official_logo": True, "institutional_score": 0.55,
                              "rotated_snippets": []})
        v = infer_assignment(case, ir)
        assert v.verdict == "OK"


class TestH2SelloRadicacion:
    def test_rad23_en_sello_rotado(self):
        case = _Case(radicado_23_digitos="68001400902720260003400")
        ir = _ir([], visual={
            "rotated_snippets": ["Radicadora 123 - Juzgado 68001400902720260003400"],
            "has_radicador_stamp": True,
        })
        v = infer_assignment(case, ir)
        assert v.verdict == "OK"
        assert any("sello" in r.lower() or "rotado" in r.lower() for r in v.reasons_for)


class TestH3AbogadoFirma:
    def test_abogado_caso_firma_en_footer(self):
        case = _Case(radicado_23_digitos="68001400902720260003400",
                     abogado_responsable="JUAN DIEGO CRUZ LIZCANO")
        z1 = DocumentZone(zone_type="HEADER", text="Respuesta 68001400902720260003400")
        z2 = DocumentZone(zone_type="FOOTER_TAIL",
                          text="Proyectó: JUAN DIEGO CRUZ LIZCANO CPS")
        ir = _ir([z1, z2])
        v = infer_assignment(case, ir)
        assert v.verdict == "OK"
        assert any("abogado" in r.lower() for r in v.reasons_for)


class TestH4DocDeOtroProceso:
    def test_rad_ajeno_en_header_da_no_pertenece(self):
        case = _Case(radicado_23_digitos="68001400902720260003400")
        z = DocumentZone(zone_type="HEADER", text="68001400902720260009999 OTRO CASO")
        ir = _ir([z])
        v = infer_assignment(case, ir)
        assert v.verdict == "NO_PERTENECE"

    def test_rad_ajeno_en_body_con_match_en_header_sigue_ok(self):
        # Escenario: nuestro rad en header + mención a otro rad en body (cita)
        case = _Case(radicado_23_digitos="68001400902720260003400")
        z1 = DocumentZone(zone_type="HEADER", text="68001400902720260003400")
        z2 = DocumentZone(zone_type="BODY", text="En relación con el proceso 68001400902720260009999...")
        ir = _ir([z1, z2])
        v = infer_assignment(case, ir)
        assert v.verdict == "OK"


class TestSospechosoSinEvidencia:
    def test_sin_ninguna_senal_queda_sospechoso(self):
        case = _Case(radicado_23_digitos="68001400902720260003400")
        z = DocumentZone(zone_type="BODY", text="Este es un documento genérico sin identificadores.")
        ir = _ir([z])
        v = infer_assignment(case, ir)
        # Sin evidencia, el prior 0.70 queda bajo OK_THRESHOLD → SOSPECHOSO
        assert v.verdict == "SOSPECHOSO"
        assert NEG_THRESHOLD < v.posterior < OK_THRESHOLD


class TestCCMatch:
    def test_cc_accionante_coincide(self):
        case = _Case(
            radicado_23_digitos="68001400902720260003400",
            accionante="PAOLA ANDREA GARCIA CC 1077467661",
        )
        z = DocumentZone(zone_type="BODY",
                         text="identificada con C.C. 1077467661 y el rad 68001400902720260003400")
        ir = _ir([z])
        v = infer_assignment(case, ir)
        assert v.verdict == "OK"


class TestReasonsExplicativas:
    def test_verdict_tiene_reasons_serializables(self):
        case = _Case(radicado_23_digitos="68001400902720260003400",
                     accionante="Juan Pérez")
        z = DocumentZone(zone_type="HEADER", text="68001400902720260003400")
        ir = _ir([z])
        v = infer_assignment(case, ir)
        d = v.to_dict()
        assert "verdict" in d
        assert "reasons_for" in d
        assert "posterior" in d
        assert 0 <= d["posterior"] <= 1
