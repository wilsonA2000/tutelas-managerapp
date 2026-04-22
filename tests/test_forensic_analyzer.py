"""Tests v5.2 forensic analyzer — emulación mecánica de análisis cognitivo."""

import pytest


class TestDocumentClassification:
    """Etapa 2: clasificación por contenido (no por nombre)."""

    def test_email_outlook_tutela_online(self):
        from backend.services.forensic_analyzer import classify_by_content
        text = """Outlook
RV: Generación de Tutela en línea No 3645440
Desde apptutelasbga@cendoj.ramajudicial.gov.co
Se ha registrado la Tutela en Línea con número 3645440"""
        types = classify_by_content(text)
        assert types[0][0] == "EMAIL_OUTLOOK_TUTELA_ONLINE"

    def test_escrito_tutela(self):
        from backend.services.forensic_analyzer import classify_by_content
        text = """Señor
JUEZ DE TUTELA (REPARTO)
E. S. D

ACCIONANTE: ALIS YURLEDYS MORENO MORENO
ACCIONADA: SECRETARIA DE EDUCACIÓN"""
        types = classify_by_content(text)
        assert types[0][0] == "ESCRITO_TUTELA"

    def test_acta_reparto(self):
        from backend.services.forensic_analyzer import classify_by_content
        text = """ACTA DE REPARTO CIVIL No. 148
En la fecha son sometidos a reparto los procesos
REPARTIDO AL JUZGADO 2 PROMISCUO MUNICIPAL"""
        types = classify_by_content(text)
        assert types[0][0] == "ACTA_REPARTO"

    def test_scan_sin_texto(self):
        from backend.services.forensic_analyzer import classify_by_content
        assert classify_by_content("")[0][0] == "SCAN_SIN_TEXTO"
        assert classify_by_content("   \n  ")[0][0] == "SCAN_SIN_TEXTO"


class TestIdentifierExtraction:
    """Etapa 4: extracción de TODOS los identificadores numéricos."""

    def test_extract_cc(self):
        from backend.services.forensic_analyzer import extract_all_identifiers
        text = "ALIS YURLEDYS identificada con C.C. 1077467661 de Colombia"
        ids = extract_all_identifiers(text)
        assert "1077467661" in ids.get("cc_accionante", [])

    def test_extract_tutela_online(self):
        from backend.services.forensic_analyzer import extract_all_identifiers
        text = "Se ha registrado la Tutela en Línea con número 3722226"
        ids = extract_all_identifiers(text)
        assert "3722226" in ids.get("tutela_online", [])

    def test_extract_nuip_menor(self):
        from backend.services.forensic_analyzer import extract_all_identifiers
        text = "menor JUIETA JIMÉNEZ PEÑA, identificada con Registro Civil No. 1130104808"
        ids = extract_all_identifiers(text)
        assert "1130104808" in ids.get("nuip_menor", [])

    def test_extract_multiple_types(self):
        from backend.services.forensic_analyzer import extract_all_identifiers
        text = """EDGAR DIAZ VARGAS, CC 91071881
        Tutela en Línea No 3645440
        Expediente No. 160-25"""
        ids = extract_all_identifiers(text)
        assert "91071881" in ids.get("cc_accionante", [])
        assert "3645440" in ids.get("tutela_online", [])
        assert "160-25" in ids.get("expediente_disciplinario", [])


class TestEntityExtraction:
    """Etapa 3: extracción de accionante/accionado/juzgado/ciudad."""

    def test_accionante_explicit(self):
        from backend.services.forensic_analyzer import extract_entities
        text = "ACCIONANTE: ALIS YURLEDYS MORENO MORENO\nTIPO Y NÚMERO DE IDENTIFICACIÓN: C.C. 1077467661"
        ents = extract_entities(text, "ESCRITO_TUTELA")
        assert "MORENO" in (ents.get("accionante") or "")
        assert "ALIS" in (ents.get("accionante") or "")

    def test_accionante_online(self):
        from backend.services.forensic_analyzer import extract_entities
        text = "Accionante: EDGAR DIAZ VARGAS Identificado con documento: 91071881"
        ents = extract_entities(text, "EMAIL_OUTLOOK_TUTELA_ONLINE")
        assert "EDGAR DIAZ" in (ents.get("accionante") or "")

    def test_ciudad_tutela_online(self):
        from backend.services.forensic_analyzer import extract_entities
        text = "Lugar donde se interpone la tutela.\nDepartamento: SANTANDER.\nCiudad: ENCINO"
        ents = extract_entities(text, "EMAIL_OUTLOOK_TUTELA_ONLINE")
        assert "ENCINO" in (ents.get("ciudad") or "")


class TestFolderCorrelation:
    """Etapa 5: correlación de archivos de una carpeta."""

    def test_series_detection(self):
        from backend.services.folder_correlator import detect_series_prefix
        filenames = ["001_EscritoTutela.pdf", "002_Anexos.pdf", "003_ActaReparto.pdf"]
        series = detect_series_prefix(filenames)
        assert "serie_3dig" in series
        assert len(series["serie_3dig"]) == 3


class TestRegexLibraryExtensions:
    """Validar que los 5 patterns nuevos de regex_library.py funcionan."""

    def test_cc_accionante(self):
        from backend.agent.regex_library import CC_ACCIONANTE
        for t, expected in [("C.C. 1077467661", "1077467661"),
                            ("identificada con documento: 91071881", "91071881"),
                            ("cédula de ciudadanía No. 1005461409", "1005461409")]:
            m = CC_ACCIONANTE.pattern.search(t)
            assert m, f"Sin match en: {t!r}"
            assert m.group(1) == expected

    def test_tutela_online_no(self):
        from backend.agent.regex_library import TUTELA_ONLINE_NO
        m = TUTELA_ONLINE_NO.pattern.search("Tutela en Línea con número 3645440")
        assert m and m.group(1) == "3645440"

    def test_nuip_menor(self):
        from backend.agent.regex_library import NUIP_MENOR
        m = NUIP_MENOR.pattern.search("Registro Civil No. 1130104808")
        assert m and m.group(1) == "1130104808"

    def test_all_regex_lib_patterns_pass(self):
        from backend.agent.regex_library import validate_all_patterns
        results = validate_all_patterns()
        failed = [n for n, ok in results.items() if not ok]
        assert not failed, f"Fallos: {failed}"
