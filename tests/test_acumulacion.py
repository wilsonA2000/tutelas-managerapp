"""Tests de detección de acumulaciones procesales (backend/email/acumulacion.py).

Casos derivados de la acumulación real del Juzgado 01 Promiscuo Municipal de Hato
(radicados 2025-00045 Méndez / 00046 Hernández / 00047 Cala), donde el sistema
viejo perdía el radicado "desnudo" 00047 y nunca creaba el caso de Liliana.
"""
from backend.email.acumulacion import (
    AcumulacionEvidence,
    analyze_docs,
    harvest_accionantes,
    harvest_rad_accionante_pairs,
    harvest_rads_corto,
    has_acumulacion_signal,
    name_key,
)


# ── harvest_rads_corto ──────────────────────────────────────────────────────

def test_harvest_enumeracion_con_rad_desnudo():
    """El bug raíz: '...2025-00046 y 00047' debe rendir los 3 radicados."""
    s = "RADICADOS 2025-00045, 2025-00046 y 00047 ACUMULADOS"
    assert harvest_rads_corto(s) == ["2025-00045", "2025-00046", "2025-00047"]


def test_harvest_todos_explicitos():
    s = "se acumulan 2025-00045 y 2025-00046"
    assert harvest_rads_corto(s) == ["2025-00045", "2025-00046"]


def test_harvest_rad_corto_4_digitos():
    """'2025-0047' (4 díg) se normaliza a 5."""
    assert harvest_rads_corto("TUTELA 2025-0047") == ["2025-00047"]


def test_harvest_ignora_sufijo_instancia():
    """'2025-00047-00' no debe producir '2025-00047' + un rad espurio del '-00'."""
    assert harvest_rads_corto("RADICADO: 2025-00047-00") == ["2025-00047"]


def test_harvest_no_captura_numeros_sueltos():
    """Un número suelto sin año ni enumeración no es radicado (oficio 405)."""
    assert harvest_rads_corto("Adjunto el OFICIO 405 de la fecha") == []


def test_harvest_no_hereda_si_lejos():
    """Secuencia desnuda lejos de un rad explícito NO hereda el año."""
    s = "2025-00045 ... (texto largo de más de treinta caracteres aquí) ... y 99999"
    assert harvest_rads_corto(s) == ["2025-00045"]


def test_harvest_vacio():
    assert harvest_rads_corto("") == []
    assert harvest_rads_corto(None) == []


# ── harvest_rad_accionante_pairs ────────────────────────────────────────────

SENT_LILIANA = (
    "ACCIÓN DE TUTELA\n"
    "RADICADO: 2025-00047-00\n"
    "ACCIONANTE: LILIANA PATRICIA CALA CALA\n"
    "ACCIONADO: SECRETARIA DE EDUCACION DE SANTANDER Y OTROS\n"
)


def test_pairs_sentencia_individual():
    pairs = harvest_rad_accionante_pairs(SENT_LILIANA)
    assert pairs == [("2025-00047", "LILIANA PATRICIA CALA CALA")]


def test_pairs_sentencia_conjunta():
    """Tres encabezados concatenados (PDF conjunto) → 3 pares correctos."""
    conjunta = (
        "RADICADO: 2025-00045-00\nACCIONANTE: MARIA PAULA MENDEZ RAMIREZ\nACCIONADO: SED\n"
        "RADICADO: 2025-00046-00\nACCIONANTE: GILMA LUCIA HERNANDEZ BERNAL\nACCIONADO: SED\n"
        "RADICADO: 2025-00047-00\nACCIONANTE: LILIANA PATRICIA CALA CALA\nACCIONADO: SED\n"
    )
    pairs = dict(harvest_rad_accionante_pairs(conjunta))
    assert pairs["2025-00045"] == "MARIA PAULA MENDEZ RAMIREZ"
    assert pairs["2025-00046"] == "GILMA LUCIA HERNANDEZ BERNAL"
    assert pairs["2025-00047"] == "LILIANA PATRICIA CALA CALA"


def test_accionante_en_cuerpo():
    body = "incidente de desacato promovido por la accionante LILIANA PATRICIA CALA CALA."
    names = harvest_accionantes(body)
    assert any(name_key(n) == name_key("LILIANA PATRICIA CALA CALA") for n in names)


# ── señal de acumulación ────────────────────────────────────────────────────

def test_signal_verbo():
    assert has_acumulacion_signal("se ordena la acumulación de los expedientes")
    assert has_acumulacion_signal("RADICADOS 2025-00045, 2025-00046 y 00047 ACUMULADOS")
    assert has_acumulacion_signal("ACUMÚLESE la presente acción")  # acento en la 5ª letra
    assert has_acumulacion_signal("ACÚMULESE la presente acción")  # variante ortográfica


def test_signal_filename():
    assert has_acumulacion_signal("", "AutoAcumulaTutelas.pdf")


def test_no_signal():
    assert not has_acumulacion_signal("Notificación de sentencia de tutela", "fallo.pdf")


# ── analyze_docs (integración pura) ─────────────────────────────────────────

def test_analyze_detecta_acumulacion_hato():
    """Simula los docs reales del caso 397: 3 sentencias + correo de acumulación."""
    docs = [
        {"id": 1, "filename": "SENTENCIA hato maria paula.pdf",
         "text": "RADICADO: 2025-00045-00\nACCIONANTE: MARIA PAULA MENDEZ RAMIREZ\n"},
        {"id": 2, "filename": "014 SENTENCIA gilma lucia.pdf",
         "text": "RADICADO: 2025-00046-00\nACCIONANTE: GILMA LUCIA HERNANDEZ BERNAL\n"},
        {"id": 3, "filename": "SENTENCIA liliana patricia.pdf",
         "text": "RADICADO: 2025-00047-00\nACCIONANTE: LILIANA PATRICIA CALA CALA\n"},
        {"id": 4, "filename": "Email_RADICADOS_ACUMULADOS.md",
         "text": "RESPUESTA REQUERIMIENTO RADICADOS 2025-00045, 2025-00046 y 00047 ACUMULADOS"},
    ]
    ev = analyze_docs(docs)
    assert ev.is_acumulacion
    assert set(ev.rads) == {"2025-00045", "2025-00046", "2025-00047"}
    assert ev.pairs["2025-00047"] == "LILIANA PATRICIA CALA CALA"
    assert ev.signal  # el correo trae el verbo "ACUMULADOS"


def test_analyze_acumulacion_por_nombres_sin_verbo():
    """Sin verbo explícito, ≥2 accionantes distintos con rads distintos → acumulación."""
    docs = [
        {"id": 1, "filename": "s1.pdf", "text": "RADICADO: 2025-00045-00\nACCIONANTE: MARIA PAULA MENDEZ RAMIREZ\n"},
        {"id": 2, "filename": "s2.pdf", "text": "RADICADO: 2025-00047-00\nACCIONANTE: LILIANA PATRICIA CALA CALA\n"},
    ]
    ev = analyze_docs(docs)
    assert not ev.signal
    assert ev.is_acumulacion


def test_analyze_caso_simple_no_es_acumulacion():
    """Un solo accionante, un solo radicado → NO acumulación."""
    docs = [
        {"id": 1, "filename": "fallo.pdf",
         "text": "RADICADO: 2026-00100-00\nACCIONANTE: JUAN PEREZ\nNotificación de sentencia"},
    ]
    ev = analyze_docs(docs)
    assert not ev.is_acumulacion


def test_name_key_normaliza_tildes():
    assert name_key("GILMA LUCÍA HERNÁNDEZ") == name_key("gilma lucia hernandez")
