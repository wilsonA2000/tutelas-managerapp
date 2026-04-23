"""v5.5 tests: FOOTER_TAIL garantizado, analizador visual PDF, patterns nuevos."""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.extraction.ir_builder import _make_footer_tail_zone, _FOOTER_TAIL_CHARS
from backend.extraction.pdf_visual_analyzer import (
    _classify_image, _phash_bytes, analyze_pdf_visual, PDFVisualReport
)
from backend.agent.regex_library import (
    SELLO_RADICADOR, FECHA_RECIBIDO, PROC_GOBERNACION, SELLO_JUZGADO
)


class TestFooterTailZone:
    def test_preserva_firma_abogado_en_doc_largo(self):
        huge = "X" * 200_000 + "\nProyectó: JUAN DIEGO CRUZ LIZCANO\nRevisó: OTRO"
        zone = _make_footer_tail_zone(huge)
        assert zone is not None
        assert zone.zone_type == "FOOTER_TAIL"
        assert "Proyectó: JUAN DIEGO CRUZ LIZCANO" in zone.text
        assert len(zone.text) <= _FOOTER_TAIL_CHARS

    def test_doc_mediano_se_incluye_completo(self):
        # Doc >100 chars (umbral mínimo) pero <4K (no recortado)
        mid = ("Tutela 2026-00001 accionante X. " * 10) + "\nProyectó: Y"
        zone = _make_footer_tail_zone(mid)
        assert zone is not None
        assert zone.text == mid
        assert "Proyectó: Y" in zone.text

    def test_doc_vacio_retorna_none(self):
        assert _make_footer_tail_zone("") is None
        assert _make_footer_tail_zone("    ") is None
        assert _make_footer_tail_zone("xx") is None


class TestVisualClassifier:
    def test_logo_arriba_pequeno(self):
        # logo institucional: top_page + área pequeña + aspecto cercano a cuadrado
        kind = _classify_image(width=50, height=50, page_width=600, page_height=800,
                               bbox=(10, 10, 60, 60), page=1)
        assert kind == "logo"

    def test_watermark_cubre_mitad_pagina(self):
        kind = _classify_image(width=500, height=600, page_width=600, page_height=800,
                               bbox=(50, 100, 550, 700), page=1)
        assert kind == "watermark"

    def test_sello_cuadrado_pequeno_al_final(self):
        kind = _classify_image(width=80, height=80, page_width=600, page_height=800,
                               bbox=(400, 700, 480, 780), page=2)
        assert kind == "sello"

    def test_firma_horizontal_pie_pagina(self):
        kind = _classify_image(width=200, height=50, page_width=600, page_height=800,
                               bbox=(200, 700, 400, 750), page=1)
        assert kind == "firma"


class TestPhashDeterminista:
    def test_mismo_input_mismo_hash(self):
        # Bytes de imagen invalidos: debe caer al fallback md5 y ser estable
        data = b"x" * 1000
        h1 = _phash_bytes(data)
        h2 = _phash_bytes(data)
        assert h1 == h2
        assert len(h1) > 0


class TestAnalyzerTolerante:
    def test_archivo_inexistente_retorna_reporte_vacio(self):
        report = analyze_pdf_visual("/tmp/no_existe_xyz.pdf")
        assert isinstance(report, PDFVisualReport)
        assert report.page_count == 0
        assert report.images_count == 0
        assert report.institutional_score == 0.0


class TestNewPatterns:
    def test_sello_radicador(self):
        assert SELLO_RADICADOR.pattern.search("Radicadora: 12345").group(1) == "12345"
        assert SELLO_RADICADOR.pattern.search("RADICADA EN 987").group(1) == "987"

    def test_fecha_recibido(self):
        m = FECHA_RECIBIDO.pattern.search("Recibido: 15/03/2026")
        assert m and m.group(1) == "15/03/2026"

    def test_proc_gobernacion(self):
        assert PROC_GOBERNACION.pattern.search("Proc. 45678").group(1) == "45678"
        assert PROC_GOBERNACION.pattern.search("PROCESO 123456").group(1) == "123456"

    def test_sello_juzgado(self):
        m = SELLO_JUZGADO.pattern.search("JUZGADO PRIMERO PROMISCUO DE FAMILIA DE BUCARAMANGA")
        assert m and "PROMISCUO" in m.group(1)
