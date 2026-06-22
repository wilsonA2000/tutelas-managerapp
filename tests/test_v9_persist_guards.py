"""Tests que FIJAN como invariante cada guard de persist.py (de-sobreingeniería Fase 5).

Cada guard de persist.py codifica una regla jurídica/de-datos aprendida en producción.
Antes vivían como "folklore" (parche sin test). Aquí cada uno queda blindado por un test
nombrado: si alguien lo borra/cambia por error, el test lo caza. Complementa los guards
ya cubiertos en test_v9_persist_sticky.py (STICKY, INCIDENTE, API-authoritative, fecha
coherente).
"""
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.v9.persist import (
    _is_hallucinated, _merge_observaciones, _date_out_of_range,
    _RECOMPUTE_FIELDS, _DATE_YEAR_BOUNDS, _LATE_ACTUATION_FIELDS,
)


# ── Guard: _is_hallucinated (rechaza relleno inventado por el LLM) ──────────────
def test_hallucinated_rechaza_frases_relleno():
    for v in ("no disponible", "N/A", "Sin Determinar", "DESCONOCIDO", "  no aplica  "):
        assert _is_hallucinated(v), f"{v!r} debería marcarse alucinación"

def test_hallucinated_acepta_valores_reales():
    for v in ("MATRICULA", "JUZGADO PRIMERO PENAL", "2026-00044", "SALUD - VIDA"):
        assert not _is_hallucinated(v)

def test_hallucinated_vacio_no_es_alucinacion():
    assert not _is_hallucinated("")


# ── Guard: _merge_observaciones (append-only de flags auto-detectados) ──────────
def test_obs_current_vacio_toma_new():
    assert _merge_observaciones("", "Agente oficioso: Juan") == "Agente oficioso: Juan"

def test_obs_new_vacio_no_toca():
    assert _merge_observaciones("texto previo", "") is None

def test_obs_append_flag_auto_nuevo():
    out = _merge_observaciones("Historia previa.", "Sujeto de especial protección: menor de edad")
    assert out == "Historia previa.\nSujeto de especial protección: menor de edad"

def test_obs_no_duplica_flag_existente():
    cur = "Sujeto de especial protección: menor de edad"
    assert _merge_observaciones(cur, cur) is None

def test_obs_texto_libre_no_auto_no_se_appendea():
    # Texto que NO empieza con un prefijo auto-detectado no se mezcla (es manual).
    assert _merge_observaciones("Historia.", "Comentario libre del abogado") is None


# ── Guard: _date_out_of_range (F7 — cota de año por campo, relativa al rad) ─────
def test_f7_sin_rad_year_no_filtra():
    assert _date_out_of_range("fecha_fallo_1st", "13/03/2026", None) is False

def test_f7_campo_sin_cota_no_filtra():
    assert _date_out_of_range("accionante", "cualquier", 2026) is False

def test_f7_fallo_anterior_a_radicacion_fuera_de_rango():
    # un "fallo" datado 2024 en una tutela radicada 2026 = fecha citada mal tomada
    assert _date_out_of_range("fecha_fallo_1st", "10/05/2024", 2026) is True

def test_f7_fallo_dentro_de_ventana_ok():
    assert _date_out_of_range("fecha_fallo_1st", "13/03/2026", 2026) is False
    assert _date_out_of_range("fecha_fallo_1st", "13/03/2027", 2026) is False  # rad+1

def test_f7_actuacion_tardia_anos_despues_es_valida():
    # fecha_respuesta 2026 sobre tutela radicada 2022: NO se rechaza (fix casos 395/11)
    assert "fecha_respuesta" in _LATE_ACTUATION_FIELDS
    assert _date_out_of_range("fecha_respuesta", "01/02/2026", 2022) is False

def test_f7_actuacion_tardia_futura_se_rechaza():
    futuro = datetime.now().year + 5
    assert _date_out_of_range("fecha_respuesta", f"01/02/{futuro}", 2022) is True


# ── Guard: _RECOMPUTE_FIELDS (estado es DERIVADO — se recomputa, no fill-only) ──
def test_estado_en_recompute_fields():
    # estado depende de sentido/impugnacion/incidente; debe recomputarse aunque ya
    # tenga valor (a diferencia de la política first-writer-wins del resto de campos).
    assert "estado" in _RECOMPUTE_FIELDS

def test_date_year_bounds_cubre_los_campos_fecha():
    # Cota de seguridad: todos los campos fecha del cuadro tienen bound F7 definido.
    for f in ("fecha_ingreso", "fecha_fallo_1st", "fecha_respuesta", "fecha_fallo_2nd",
              "fecha_apertura_incidente"):
        assert f in _DATE_YEAR_BOUNDS
