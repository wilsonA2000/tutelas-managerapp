"""Tests de `_extract_abogado_footer` (regex_pass) — fix 2026-06-02.

Estructura del footer de respuesta SED (de arriba abajo):
  YANETH KARINA ARAUJO MAESTRE / SECRETARIA DE EDUCACIÓN   ← titular
  PROYECTÓ/ELABORO <ABOGADO>-ABOGADO GRUPO DE APOYO ...     ← REDACTOR = abogado_responsable
  APROBÓ:/REVISÓ: <COORDINADORA> - COORDINADORA ...         ← supervisora (NUNCA es el abogado)

Bugs corregidos:
1. El redactor se escribe SIN dos-puntos ("PROYECTÓ VICTOR...") pero el supervisor CON
   ("APROBÓ: MARIA..."). El regex exigía ':' → solo capturaba a la supervisora.
2. Había un fallback que devolvía a la supervisora cuando no se hallaba redactor → la
   Dra. María Cristina (coordinadora que firma TODAS las respuestas) se atribuía el caso.
"""
from backend.v9.regex_pass import _extract_abogado_footer
from backend.v9.field_extractor import _RE_EXT_ABOG


def test_externo_nombre_adyacente_a_rol_se_captura():
    # Abogado externo CPS: nombre INMEDIATAMENTE seguido del rol → se captura.
    for txt in [
        "Proyectó: Jaime Iván Restrepo Gómez – Abogado Contratista Externo SED",
        "Proyectó: Jorge Andrés Contreras / Abogado CPS",
        "Elaboró: Laura Marcela Camelo Montagut - Contratista Grupo de Apoyo Jurídico",
    ]:
        m = _RE_EXT_ABOG.search(txt)
        assert m, txt
        assert len(m.group(1).split()) >= 2


def test_externo_prosa_no_se_captura():
    # "proyectó <prosa>" sin rol adyacente → NO se captura (evita basura como
    # "CELEBRADA CON EL", "ES REMITIDO A LA", "OBTENER VIABILIDAD").
    for txt in [
        "se proyectó CELEBRADA CON EL contrato de obra para el colegio",
        "el oficio es remitido a la dependencia para lo pertinente",
        "se proyectó obtener viabilidad técnica y financiera del proyecto",
    ]:
        assert _RE_EXT_ABOG.search(txt) is None, txt


def test_redactor_sin_colon_gana_a_supervisor_con_colon():
    txt = (
        "YANETH KARINA ARAUJO MAESTRE\nSECRETARIA DE EDUCACIÓN\n"
        "ELABORO VICTOR COLMENARES-ABOGADO  ESPECIALISTA GRUPO DE APOYO JURÍDICO.\n"
        "APROBÓ: MARIA CRISTINA VILLAMIZAR SCHILLER- COORDINADORA GRUPO DE APOYO JURIDICO."
    )
    assert _extract_abogado_footer(txt) == "VICTOR COLMENARES"


def test_proyecto_sin_colon():
    txt = ("Cordialmente,\nYANETH KARINA ARAUJO MAESTRE\nSECRETARIA DE EDUCACIÓN\n"
           "PROYECTÓ VICTOR COLMENARES-ABOGADO GRUPO DE APOYO JURÍDICO.\n"
           "APROBÓ:  MARIA CRISTINA VILLAMIZAR SCHILLER- COORDINADORA.")
    assert _extract_abogado_footer(txt) == "VICTOR COLMENARES"


def test_solo_supervisor_devuelve_none():
    # Sin redactor: la coordinadora (Revisó/Aprobó) NUNCA se devuelve.
    txt = ("YANETH KARINA ARAUJO MAESTRE\nSECRETARIA DE EDUCACIÓN\n"
           "REVISÓ: MARIA CRISTINA VILLAMIZAR SCHILLER- COORDINADORA.")
    assert _extract_abogado_footer(txt) is None


def test_proyecto_con_colon_clasico_sigue_funcionando():
    txt = ("Atentamente,\nProyectó: Jhon Alexander Bohorquez Camargo\n"
           "Revisó: Maria Cristina Villamizar")
    assert _extract_abogado_footer(txt) == "JHON ALEXANDER BOHORQUEZ CAMARGO"


def test_no_captura_prosa_proyecto_minuscula():
    # "proyectó la respuesta..." NO es una firma → no se captura (valor empieza minúscula).
    txt = "En el presente escrito se proyectó la respuesta de fondo a la tutela."
    assert _extract_abogado_footer(txt) is None
