"""Tests del grounding anti-sobre-etiqueta de `_ground_speculative_derechos`
(backend/v9/field_extractor).

El Qwen3-4B local tiende a ALUCINAR derechos "raros" (INTIMIDAD/HABEAS_DATA/
MINIMO_VITAL/SEGURIDAD_SOCIAL) que la demanda no invoca (medido 2026-06-02: ~50%
de los cambios de derecho del 4B eran sobre-etiqueta). El grounding determinista
los descarta SALVO que el texto los evidencie; los derechos "core" pasan intactos."""
from backend.v9.field_extractor import _ground_speculative_derechos


def test_especulativo_sin_evidencia_se_descarta():
    # INTIMIDAD propuesto por el LLM pero el texto solo habla de educación.
    assert _ground_speculative_derechos(
        ["EDUCACION", "INTIMIDAD"],
        "el menor requiere docente para garantizar su educacion inclusiva",
    ) == ["EDUCACION"]


def test_especulativo_con_evidencia_se_conserva():
    assert _ground_speculative_derechos(
        ["EDUCACION", "INTIMIDAD"],
        "se vulnera su derecho a la intimidad y buen nombre",
    ) == ["EDUCACION", "INTIMIDAD"]


def test_minimo_vital_requiere_evidencia():
    assert _ground_speculative_derechos(["SALUD", "MINIMO_VITAL"], "requiere atencion en salud") == ["SALUD"]
    assert _ground_speculative_derechos(
        ["SALUD", "MINIMO_VITAL"], "el no pago afecta su minimo vital y subsistencia"
    ) == ["SALUD", "MINIMO_VITAL"]


def test_seguridad_social_evidenciada_por_pension():
    assert _ground_speculative_derechos(
        ["TRABAJO", "SEGURIDAD_SOCIAL"], "solicita el reconocimiento de su pension de jubilacion"
    ) == ["TRABAJO", "SEGURIDAD_SOCIAL"]


def test_habeas_data_por_datos_personales():
    assert _ground_speculative_derechos(
        ["PETICION", "HABEAS_DATA"], "tratamiento indebido de sus datos personales"
    ) == ["PETICION", "HABEAS_DATA"]
    assert _ground_speculative_derechos(["PETICION", "HABEAS_DATA"], "no contestaron su derecho de peticion") == ["PETICION"]


def test_core_nunca_se_filtra():
    core = ["EDUCACION", "SALUD", "VIDA", "TRABAJO", "PETICION", "DEBIDO_PROCESO", "IGUALDAD"]
    assert _ground_speculative_derechos(core, "texto sin ninguna keyword") == core


def test_acentos_y_mayusculas_se_normalizan():
    # El texto trae tildes/mayúsculas; el grounding folds antes de comparar.
    assert _ground_speculative_derechos(
        ["VIDA", "MINIMO_VITAL"], "Afecta su MÍNIMO VITAL de manera grave"
    ) == ["VIDA", "MINIMO_VITAL"]
