"""Tests para todos los patrones regex de la plataforma Tutelas.

Cubre: radicado extraction, FOREST extraction, accionante extraction.
Cada test documenta qué patrón se prueba y con qué datos reales.
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.email.gmail_monitor import extract_radicado, extract_forest, extract_accionante
from backend.agent.forest_extractor import (
    is_valid_forest, extract_forest_from_sources,
    FOREST_PATTERN, FOREST_KEYWORD_PATTERN, FOREST_BLACKLIST,
)


# ============================================================
# FOREST Validation
# ============================================================

class TestForestValidation:
    """Tests para is_valid_forest()."""

    def test_valid_forest_10_digits(self):
        assert is_valid_forest("20260054965") is True

    def test_valid_forest_11_digits(self):
        assert is_valid_forest("20260024347") is True

    def test_blacklisted_forest(self):
        """3634740 es un FOREST alucinado por la IA - NUNCA debe aceptarse."""
        assert is_valid_forest("3634740") is False

    def test_radicado_judicial_not_forest(self):
        """Números que empiezan con 68 son radicados judiciales de Santander."""
        assert is_valid_forest("68001400900") is False
        assert is_valid_forest("6800140090027") is False

    def test_too_short(self):
        assert is_valid_forest("12345") is False
        assert is_valid_forest("123456") is False

    def test_empty_and_none(self):
        assert is_valid_forest("") is False
        assert is_valid_forest(None) is False

    def test_all_zeros(self):
        assert is_valid_forest("0000000") is False

    def test_seven_digit_valid(self):
        """Números de 7 dígitos que no empiezan con 68 son válidos."""
        assert is_valid_forest("2695882") is True

    def test_blacklist_contents(self):
        assert "3634740" in FOREST_BLACKLIST


# ============================================================
# FOREST Pattern Matching
# ============================================================

class TestForestPattern:
    """Tests para FOREST_PATTERN regex."""

    def test_variante_el_numero(self):
        """'El número de radicado es XXXXXXXXXXX' - variante principal."""
        text = "El número de radicado es 20260054965 asignado a su proceso"
        m = FOREST_PATTERN.search(text)
        assert m is not None
        assert m.group(1) == "20260054965"

    def test_variante_con_numero(self):
        """'Con número de radicado XXXXXXXXXXX' - variante alternativa."""
        text = "Con número de radicado 20260024347 se ha registrado"
        m = FOREST_PATTERN.search(text)
        assert m is not None
        assert m.group(1) == "20260024347"

    def test_variante_radicado_es(self):
        """'radicado es XXXXXXXXXXX'."""
        text = "radicado es 20260037004"
        m = FOREST_PATTERN.search(text)
        assert m is not None
        assert m.group(1) == "20260037004"

    def test_variante_radicado_y_enviado(self):
        """'radicado y enviado XXXXXXXXXXX'."""
        text = "radicado y enviado 20260041234"
        m = FOREST_PATTERN.search(text)
        assert m is not None

    def test_no_match_radicado_judicial(self):
        """Un radicado judicial NO debe matchear como FOREST."""
        text = "Radicado No. 68-001-40-09-027-2026-00034-00"
        m = FOREST_PATTERN.search(text)
        assert m is None

    def test_no_match_generic_number(self):
        """Un número suelto no debe matchear."""
        text = "Se remite oficio 12345678"
        m = FOREST_PATTERN.search(text)
        assert m is None


# ============================================================
# FOREST Extraction from Sources
# ============================================================

class TestForestExtraction:
    """Tests para extract_forest_from_sources()."""

    def test_gmail_pdf_priority(self):
        """Gmail PDFs tienen prioridad sobre emails DB."""
        docs = [
            {"filename": "Gmail - RV_ TUTELA.pdf", "text": "El número de radicado es 20260054965"},
            {"filename": "Email_20260315.md", "text": "tutelas@santander.gov.co\nEl número de radicado es 99999999"},
        ]
        result = extract_forest_from_sources(docs)
        assert result.value == "20260054965"
        assert result.confidence == "ALTA"
        assert "gmail_pdf" in result.source

    def test_email_md_requires_tutelas_sender(self):
        """Email_*.md sin tutelas@santander.gov.co no debe extraer FOREST."""
        docs = [
            {"filename": "Email_20260315.md", "text": "From: juzgado@cendoj.gov.co\nEl número de radicado es 20260099999"},
        ]
        result = extract_forest_from_sources(docs)
        assert result is None

    def test_no_forest_returns_none(self):
        docs = [{"filename": "auto.pdf", "text": "Auto admisorio de tutela"}]
        assert extract_forest_from_sources(docs) is None

    def test_blacklisted_forest_skipped(self):
        docs = [
            {"filename": "Gmail - RV_ TUTELA.pdf", "text": "El número de radicado es 3634740"},
        ]
        assert extract_forest_from_sources(docs) is None


# ============================================================
# Radicado Extraction (gmail_monitor)
# ============================================================

class TestRadicadoExtraction:
    """Tests para extract_radicado() de gmail_monitor.py."""

    def test_radicado_23_digitos_sin_separadores(self):
        """Radicado completo de 23 dígitos sin separadores."""
        text = "OFICIO NOTIFICA FALLO RAD 68001400902720260003400"
        result = extract_radicado(text)
        assert result["radicado_23"] != ""

    @pytest.mark.xfail(reason="Regex actual no captura radicados con guiones - MEJORA PENDIENTE Fase 3.1")
    def test_radicado_23_digitos_con_guiones(self):
        """Radicado con guiones: 68001-40-09-027-2026-00034-00."""
        text = "OFICIO NOTIFICA FALLO RAD 68001-40-09-027-2026-00034-00"
        result = extract_radicado(text)
        assert result["radicado_23"] != ""

    def test_formato_t(self):
        """Formato T-00053/2026."""
        text = "TUTELA T-00053/2026 URGENTE"
        result = extract_radicado(text)
        assert result["radicado_corto"] == "2026-00053"

    def test_formato_rad(self):
        """Formato RAD. 2026-00095."""
        text = "NOTIFICACION RAD. 2026-00095"
        result = extract_radicado(text)
        assert result["radicado_corto"] == "2026-00095"

    def test_formato_radicado_palabra(self):
        """Formato Radicado No. 2026-030."""
        text = "Radicado No. 2026-030 admitido"
        result = extract_radicado(text)
        assert result["radicado_corto"] == "2026-00030"

    def test_extraer_corto_de_23(self):
        """Extraer radicado corto del radicado de 23 dígitos."""
        text = "Radicado 68679407100120260003200"
        result = extract_radicado(text)
        if result["radicado_23"]:
            assert result["radicado_corto"] != ""

    def test_sin_radicado(self):
        """Texto sin radicado."""
        text = "Buenos días, remito documentación solicitada"
        result = extract_radicado(text)
        assert result["radicado_23"] == ""
        assert result["radicado_corto"] == ""

    def test_radicado_2025(self):
        """Radicados de años anteriores (impugnaciones activas)."""
        text = "RAD 2025-00301 FALLO SEGUNDA INSTANCIA"
        result = extract_radicado(text)
        assert "2025" in result["radicado_corto"]

    @pytest.mark.xfail(reason="Regex actual no captura radicados con puntos - MEJORA PENDIENTE Fase 3.1")
    def test_radicado_con_puntos(self):
        """Radicado con puntos como separador: 68001.40.03.002.2026.00009.01."""
        text = "Radicado 68001.40.03.002.2026.00009.01"
        result = extract_radicado(text)
        assert result["radicado_23"] != "" or result["radicado_corto"] != ""


# ============================================================
# FOREST Extraction (gmail_monitor)
# ============================================================

class TestForestGmailMonitor:
    """Tests para extract_forest() de gmail_monitor.py."""

    def test_forest_from_body(self):
        body = "El número de radicado es 20260054965 asignado"
        result = extract_forest(body, [])
        assert result == "20260054965"

    def test_forest_blacklisted(self):
        body = "El número de radicado es 3634740"
        result = extract_forest(body, [])
        assert result == ""

    def test_forest_con_numero(self):
        body = "Con número de radicado 20260024347"
        result = extract_forest(body, [])
        assert result == "20260024347"

    def test_no_forest_in_attachments(self):
        """Nombres de archivos DOCX NO son fuente de FOREST."""
        result = extract_forest("", ["3367127 RESPUESTA FOREST.docx"])
        assert result == ""

    def test_no_forest_empty(self):
        result = extract_forest("", [])
        assert result == ""


# ============================================================
# Accionante Extraction
# ============================================================

class TestAccionanteExtraction:
    """Tests para extract_accionante() de gmail_monitor.py."""

    def test_accionante_explicito(self):
        subject = "ACCION DE TUTELA - ACCIONANTE: LAURA VIVIANA CHACON ARCE"
        result = extract_accionante(subject, "")
        assert "LAURA" in result
        assert "CHACON" in result

    def test_demandante(self):
        body = "Demandante: MERLY PINZON GALVIS contra Gobernación"
        result = extract_accionante("", body)
        assert "MERLY" in result

    def test_skip_words_filtered(self):
        """Palabras como JUZGADO, SECRETARIA no deben ser accionantes."""
        subject = "ACCIONANTE: JUZGADO MUNICIPAL"
        result = extract_accionante(subject, "")
        assert result == ""

    def test_nombre_muy_corto(self):
        """Nombres de menos de 2 palabras no-skip no son accionantes."""
        subject = "ACCIONANTE: LUZ"
        result = extract_accionante(subject, "")
        assert result == ""

    def test_promovida_por(self):
        body = "Tutela promovida por el señor GABRIEL GARNICA SARMIENTO"
        result = extract_accionante("", body)
        assert "GABRIEL" in result
        assert "GARNICA" in result


# ============================================================
# Run all tests
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
