"""Tests del fix 2026-06-02: `_extract_radicado_23` acepta radicados impresos con
SOLO 21 dígitos (juzgado12 + año4 + consecutivo5) cuando el auto omite el recurso
final "00" de 1ra instancia. Casos reales: c532 (Personería Chipatá) y c524 (Milena
Moreno Ruiz) quedaban con rad23=None porque el doc imprime el recurso como "–T" o lo
omite.
"""
from backend.v9.regex_pass import _extract_radicado_23


def test_chipata_21_digitos_sufijo_T():
    # "681794089001 – 2026 – 00053–T" → 21 díg + sufijo Tutela; recurso "00" implícito.
    txt = "JUZGADO PROMISCUO. RADICADO No. 681794089001 – 2026 – 00053–T JUZGADO"
    assert _extract_radicado_23(txt) == "68179408900120260005300"


def test_milena_21_digitos_sin_recurso():
    # "680014088011-2026-00099" → 21 díg pegados + guion, sin recurso.
    txt = "Notificación accion de tutela 680014088011-2026-00099 Juzgado Once Penal"
    assert _extract_radicado_23(txt) == "68001408801120260009900"


def test_21_digitos_con_ancla_folder():
    txt = "RADICADO No. 681794089001 – 2026 – 00053–T"
    assert _extract_radicado_23(txt, anchor=("2026", "00053")) == "68179408900120260005300"


def test_23_digitos_normal_no_regresion():
    assert _extract_radicado_23("Radicado 68001408801320260012000 admite") == "68001408801320260012000"


def test_recurso_real_01_se_preserva():
    # Si el doc SÍ trae el recurso (01 impugnación), NO se pisa con 00.
    txt = "rad 68001-40-09-024-2026-00055-01 impugnacion"
    assert _extract_radicado_23(txt) == "68001400902420260005501"


def test_basura_no_produce_rad():
    assert _extract_radicado_23("codigo 68ABC no es radicado") is None


def test_21_digitos_que_no_inicia_68_rechazado():
    assert _extract_radicado_23("telefono 123456789012345678901 fin") is None
