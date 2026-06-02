"""Tests de `_clean_responsable_desacato` (field_extractor v9).

CORRECCIÓN DE DOMINIO 2026-06-02 (Wilson): `responsable_desacato` NO es el abogado
— es la AUTORIDAD/PERSONA NOMBRADA en el incidente (contra quien va el desacato y
sobre quien recaería la sanción): el Gobernador, la Secretaria de Educación, un
rector, etc. El abogado que proyecta la respuesta al desacato va en la casilla
aparte `abogado_incidente`. Antes el helper validaba contra el catálogo de 17
abogados y rechazaba las instituciones — era exactamente al revés.
"""
from backend.v9.field_extractor import _clean_responsable_desacato


def test_secretaria_educacion_normaliza():
    """La Secretaría de Educación (cargo/institución) ES el sancionado → forma canónica."""
    assert _clean_responsable_desacato("Secretaria de Educación de Santander") == "SECRETARÍA DE EDUCACIÓN DE SANTANDER"
    assert _clean_responsable_desacato("SECRETARÍA DE EDUCACIÓN DEPARTAMENTAL DE SANTANDER") == "SECRETARÍA DE EDUCACIÓN DE SANTANDER"


def test_gobernacion_gobernador_normaliza():
    """Gobernación / Gobernador / Departamento → GOBERNACIÓN DE SANTANDER."""
    assert _clean_responsable_desacato("GOBERNACIÓN DE SANTANDER") == "GOBERNACIÓN DE SANTANDER"
    assert _clean_responsable_desacato("el Gobernador de Santander") == "GOBERNACIÓN DE SANTANDER"
    assert _clean_responsable_desacato("DEPARTAMENTO DE SANTANDER") == "GOBERNACIÓN DE SANTANDER"


def test_ministerio_y_otras_entidades_se_conservan():
    """Otras autoridades/entidades requeridas se conservan (no se rechazan)."""
    assert _clean_responsable_desacato("MINISTERIO DE EDUCACIÓN NACIONAL") == "MINISTERIO DE EDUCACIÓN NACIONAL"


def test_nombre_propio_funcionario_se_conserva():
    """Nombre del funcionario/rector sancionado → se conserva en MAYÚSCULAS."""
    assert _clean_responsable_desacato("JUVENAL DÍAZ MATEUS") == "JUVENAL DÍAZ MATEUS"  # Gobernador
    assert _clean_responsable_desacato("Dra. Yaneth Karina Araújo Maestre") == "YANETH KARINA ARAÚJO MAESTRE"


def test_boilerplate_rechazado():
    """Fragmentos del auto sin entidad real → None."""
    assert _clean_responsable_desacato("INCIDENTE DE DESACATO") is None
    assert _clean_responsable_desacato("ACCIONADOS Y VINCULADOS") is None
    assert _clean_responsable_desacato("PREVIA APERTURA FORMAL INCIDENTE DE DESACATO") is None
    assert _clean_responsable_desacato("LAS MENCIONADAS EN EL NUMERAL ANTERIOR QUE") is None
    assert _clean_responsable_desacato("para que cumpla") is None


def test_vacio_y_basura_rechazados():
    assert _clean_responsable_desacato("") is None
    assert _clean_responsable_desacato(None) is None


def test_longitud_fuera_rango():
    """Strings muy cortos (<4 chars) o muy largos (>80 chars) rechazados."""
    assert _clean_responsable_desacato("AB") is None
    assert _clean_responsable_desacato("X" * 90) is None


def test_fragmento_basura_rechazado():
    """Capturas malformadas del regex (solo iniciales/abreviaturas ≤3 letras) → None.
    Caso real c92/c230 (2026-06-02): el regex capturaba 'AL MR. GR'."""
    assert _clean_responsable_desacato("AL MR. GR") is None
    assert _clean_responsable_desacato("MR. GR") is None
    assert _clean_responsable_desacato("S.A. DE C") is None


def test_rol_generico_rechazado():
    """'responsable'/'encargado'/'persona encargada' son boilerplate genérico, no el
    sancionado nombrado → None. El conector líder 'al/el/la' se descarta primero."""
    assert _clean_responsable_desacato("AL RESPONSABLE") is None
    assert _clean_responsable_desacato("EL RESPONSABLE DEL CUMPLIMIENTO") is None
    assert _clean_responsable_desacato("la persona encargada de dar cumplimiento") is None


def test_conector_lider_se_descarta_pero_conserva_nombre():
    """'EL RECTOR ...' conserva el cargo real tras quitar el conector líder."""
    assert _clean_responsable_desacato("EL RECTOR DE LA INSTITUCION") == "RECTOR DE LA INSTITUCION"
    assert _clean_responsable_desacato("MEDARDO MURILLO TIRADO") == "MEDARDO MURILLO TIRADO"
