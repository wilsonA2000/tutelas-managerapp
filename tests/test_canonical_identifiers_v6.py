"""Tests F3: canonical identifiers — Capa 2 del pipeline cognitivo."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.extraction.ir_models import DocumentIR, DocumentZone
from backend.cognition.canonical_identifiers import (
    harvest_identifiers, Identifier, IdentifierSet, ZONE_PRIOR, LR_BASE,
)


def _ir(zones, visual=None):
    return DocumentIR(
        filename="test.pdf", doc_type="PDF_OTRO", priority=5,
        zones=zones, full_text="\n".join(z.text for z in zones),
        visual_signature=visual,
    )


class TestHarvestRad23:
    def test_rad23_en_header_tiene_alta_confianza(self):
        z = DocumentZone(zone_type="HEADER", text="Radicado: 68001400902720260003400")
        s = harvest_identifiers(_ir([z]))
        rads = s.of_kind("rad23")
        assert len(rads) >= 1
        assert rads[0].position_confidence >= 0.85
        assert rads[0].lr >= 50.0

    def test_rad23_en_body_tiene_menor_confianza(self):
        z = DocumentZone(zone_type="BODY", text="en el radicado 68001400902720260003400 se dijo...")
        s = harvest_identifiers(_ir([z]))
        rads = s.of_kind("rad23")
        assert len(rads) >= 1
        assert rads[0].position_confidence < 0.6

    def test_rad_corto_derivado_de_rad23(self):
        z = DocumentZone(zone_type="HEADER", text="68001400902720260003400")
        s = harvest_identifiers(_ir([z]))
        corto = s.of_kind("rad_corto")
        assert any(i.value == "2026-00034" for i in corto)


class TestHarvestSellosRotados:
    def test_rad23_en_visual_rotated_tiene_physical_signal(self):
        visual = {"has_radicador_stamp": True, "has_juzgado_seal": False,
                  "rotated_snippets": ["Radicadora: 12345 Juzgado Primero 68001400902720260003400"]}
        s = harvest_identifiers(_ir([], visual=visual))
        rads = s.of_kind("rad23")
        assert rads
        assert rads[0].physical_signal is True
        assert rads[0].source_zone == "VISUAL_ROTATED"

    def test_sello_radicador_en_rotated(self):
        visual = {"rotated_snippets": ["Radicadora: 54321"]}
        s = harvest_identifiers(_ir([], visual=visual))
        sr = s.of_kind("sello_radicador")
        assert sr
        assert sr[0].value == "54321"
        assert sr[0].physical_signal is True


class TestHarvestOtros:
    def test_cc_en_body(self):
        z = DocumentZone(zone_type="BODY", text="identificado con C.C. 1077467661")
        s = harvest_identifiers(_ir([z]))
        cc = s.of_kind("cc")
        assert cc and cc[0].value == "1077467661"

    def test_forest_en_header(self):
        z = DocumentZone(zone_type="HEADER", text="FOREST No. 3410516")
        s = harvest_identifiers(_ir([z]))
        f = s.of_kind("forest")
        assert f and f[0].value == "3410516"

    def test_duplicados_no_se_agregan(self):
        z1 = DocumentZone(zone_type="HEADER", text="68001400902720260003400")
        z2 = DocumentZone(zone_type="BODY", text="68001400902720260003400")
        s = harvest_identifiers(_ir([z1, z2]))
        rads = s.of_kind("rad23")
        assert len(rads) == 1          # deduplicado por valor normalizado


class TestBestOf:
    def test_best_of_prefiere_mayor_confianza(self):
        z1 = DocumentZone(zone_type="BODY", text="rad 68001400902720260003400 aparece")
        z2 = DocumentZone(zone_type="HEADER", text="68001400902720260003400")
        # Como es el mismo valor, hay solo 1 en items (dedup). Probamos con distintos.
        z3 = DocumentZone(zone_type="HEADER", text="68001400902720260003401")
        s = harvest_identifiers(_ir([z1, z3]))
        best = s.best_of("rad23")
        assert best is not None
        assert best.source_zone == "HEADER"     # mayor confianza


class TestIdentifierSetDict:
    def test_serializable(self):
        z = DocumentZone(zone_type="HEADER", text="Radicado 68001400902720260003400 CC 1234567890")
        s = harvest_identifiers(_ir([z]))
        d = s.to_dict()
        assert "items" in d
        assert any(i["kind"] == "rad23" for i in d["items"])
