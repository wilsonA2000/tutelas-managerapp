"""Regresión de los 5 fixes de calidad de ingesta (2026-05-25).

Surgieron de una ingesta real supervisada (35 correos):
  #2 accionante basura ("PERO QUE FUE RADICADA" del asunto)
  #3 F7 rechazaba fecha_respuesta/incidente de 2026 en tutelas de 2022
  #4 rad23 guardado con guiones (formato no canónico)
(#1 orden cronológico y #5 OCR de escaneados se validan en integración.)
"""
from backend.email.gmail_monitor import extract_accionante
from backend.email.rad_utils import normalize_rad23
from backend.v9.field_extractor import _looks_like_name
from backend.v9.persist import _date_out_of_range


# ── #2 accionante basura ─────────────────────────────────────────────────────

def test_accionante_rechaza_conectores_basura():
    g = extract_accionante(
        "RV: NOTIFICACIÓN AUTO AVOCA ACCIÓN DE TUTELA 2026-00116",
        "la presente accion promovida por PERO QUE FUE RADICADA en el juzgado")
    assert g == ""


def test_accionante_acepta_nombre_real():
    n = extract_accionante("", "accionante: MARIA PAULA MENDEZ RAMIREZ identificada con CC 123")
    assert n == "MARIA PAULA MENDEZ RAMIREZ"


def test_accionante_trunca_en_stop_token():
    n = extract_accionante("", "demandante: JUAN PEREZ GOMEZ ANTE el juzgado promiscuo")
    assert n == "JUAN PEREZ GOMEZ"


def test_v9_looks_like_name_rechaza_conectores():
    # El extractor v9 (field_extractor) es OTRA autoridad: debe rechazar la MISMA basura.
    assert _looks_like_name("PERO QUE FUE RADICADA") is False
    assert _looks_like_name("JUAN PEREZ GOMEZ") is True


# ── #3 F7: actuaciones tardías ───────────────────────────────────────────────

def test_f7_respuesta_anios_despues_es_valida():
    # tutela 2022, respuesta 2026 (incidente reactivado) → NO se rechaza
    assert _date_out_of_range("fecha_respuesta", "14/05/2026", 2022) is False


def test_f7_incidente_anios_despues_es_valido():
    assert _date_out_of_range("fecha_apertura_incidente", "08/05/2026", 2022) is False


def test_f7_fallo_citado_de_otro_anio_se_rechaza():
    # fecha de fallo de 2024 en un caso 2026 = fecha citada mal tomada → se rechaza
    assert _date_out_of_range("fecha_fallo_1st", "01/01/2024", 2026) is True


def test_f7_fecha_anterior_a_radicacion_se_rechaza():
    # nada antecede a la radicación
    assert _date_out_of_range("fecha_apertura_incidente", "01/01/2021", 2022) is True


def test_f7_fecha_futura_absurda_se_rechaza():
    assert _date_out_of_range("fecha_respuesta", "01/01/2099", 2022) is True


# ── #4 rad23 normalización a continuo ────────────────────────────────────────

def test_rad23_normaliza_guiones_a_continuo():
    assert normalize_rad23("680014003016-2026-00381-00") == "68001400301620260038100"
    assert len(normalize_rad23("680014003016-2026-00381-00")) == 23


# ── DeepSeek desconectado salvo flag explícito ───────────────────────────────

def test_deepseek_gateado_tras_flag(monkeypatch):
    """Con V9_LLM_API_KEY pero SIN V9_ALLOW_DEEPSEEK, los clientes de extracción
    NO usan DeepSeek (key inerte). Con el flag, se reactiva."""
    import importlib
    monkeypatch.setenv("V9_LLM_API_KEY", "sk-test")
    monkeypatch.delenv("V9_ALLOW_DEEPSEEK", raising=False)
    import backend.v9.llm_gap_fill as g
    import backend.extraction.ai_extractor as a
    importlib.reload(g); importlib.reload(a)
    assert g._LLM_API_KEY == "" and a._LLM_API_KEY == ""  # desconectado
    monkeypatch.setenv("V9_ALLOW_DEEPSEEK", "true")
    importlib.reload(g); importlib.reload(a)
    assert g._LLM_API_KEY == "sk-test" and a._LLM_API_KEY == "sk-test"  # reactivado
    # restaurar estado limpio para otros tests
    monkeypatch.delenv("V9_LLM_API_KEY", raising=False)
    monkeypatch.delenv("V9_ALLOW_DEEPSEEK", raising=False)
    importlib.reload(g); importlib.reload(a)
