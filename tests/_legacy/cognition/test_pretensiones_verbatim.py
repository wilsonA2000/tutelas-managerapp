"""Tests v9.4 — Pretensiones VERBATIM (transcripción literal).

Wilson requirió: "las pretensiones deben ser transcritas tal cual, no resumidas,
no parafraseadas". Esta suite verifica que build_pretensiones:
1. Copia literal del escrito de tutela
2. Captura desde header "PRETENSIONES" hasta el siguiente header
3. NO trunca a 220 chars (límite nuevo: 4000)
4. NO inventa paráfrasis si no hay sección clara
"""
from backend.cognition.narrative_builder import build_pretensiones


def _empty_actors():
    """Mock mínimo de ActorSet."""
    class _A:
        accionados = []
        accionante = None
    return _A()


def test_captura_seccion_pretensiones_clara():
    """Texto con sección clara → captura literal."""
    full = """
    HECHOS
    Primero. La accionante labora como docente desde 2020.
    Segundo. El día 12 de marzo solicitó traslado.

    PRETENSIONES
    PRIMERA: Tutelar el derecho fundamental a la salud y la educación de la accionante.
    SEGUNDA: Ordenar a la Secretaría de Educación de Santander que proceda con el traslado.
    TERCERA: Condenar en costas a la entidad accionada.

    FUNDAMENTOS DE DERECHO
    Constitución Política, art. 86.
    """
    result = build_pretensiones(_empty_actors(), "EDUCACION", full, "traslado docente")
    assert "PRIMERA" in result
    assert "SEGUNDA" in result
    assert "TERCERA" in result
    assert "Tutelar el derecho fundamental" in result
    # NO debe contener el siguiente header
    assert "FUNDAMENTOS DE DERECHO" not in result
    assert "Constitución Política" not in result


def test_no_inventa_si_no_hay_seccion():
    """Sin sección PRETENSIONES → vacío, NO paráfrasis fallback."""
    full = "Texto cualquiera sin la sección esperada. La accionante solicita amparo."
    result = build_pretensiones(_empty_actors(), "EDUCACION", full, "traslado docente")
    assert result == ""


def test_no_trunca_pretensiones_largas():
    """Pretensiones de 1500 chars → NO se truncan a 220."""
    pretens_largas = "PRIMERA: " + ("Tutelar derechos fundamentales " * 50) + "."
    full = f"PRETENSIONES\n{pretens_largas}\nHECHOS\nbla bla"
    result = build_pretensiones(_empty_actors(), "", full, "")
    assert len(result) > 1000
    assert "PRIMERA" in result


def test_respeta_limite_max_4000():
    """Bloque > 4000 chars → trunca con elipsis."""
    pretens_enorme = "PRIMERA: " + ("Que se ordene a la entidad " * 500)
    full = f"PRETENSIONES\n{pretens_enorme}"
    result = build_pretensiones(_empty_actors(), "", full, "")
    assert len(result) <= 4001  # +1 por elipsis
    assert result.endswith("…") or len(result) <= 4000


def test_captura_con_numeracion_decimal():
    """Pretensiones con 1., 2., 3. (no PRIMERA/SEGUNDA)."""
    full = """
    PRETENSIONES:
    1. Amparar el derecho fundamental a la salud.
    2. Ordenar a la accionada cubrir el tratamiento.
    3. Condenar en costas.

    HECHOS
    Texto siguiente
    """
    result = build_pretensiones(_empty_actors(), "SALUD", full, "tratamiento")
    assert "1. Amparar" in result
    assert "2. Ordenar" in result
    assert "3. Condenar" in result
    assert "HECHOS" not in result


def test_no_contiene_paraphrase_que_se_ordene():
    """v9.4: la versión vieja generaba 'Que se ordene...' como fallback. NO debe
    aparecer cuando no hay sección. El campo queda vacío para revisión humana."""
    full = "Documento con texto sin sección de pretensiones identificable."
    result = build_pretensiones(_empty_actors(), "EDUCACION", full, "traslado docente")
    # Antes (v8.1): retornaba "Que se ordene el traslado docente..."
    # Ahora (v9.4): retorna ""
    assert "Que se ordene" not in result
    assert result == ""
