"""Biblioteca centralizada de patrones regex para extracción de datos jurídicos.

Todos los regex de la plataforma en un solo lugar: documentados, testados, reutilizables.
"""

import re
from dataclasses import dataclass


@dataclass
class RegexPattern:
    name: str
    pattern: re.Pattern
    description: str
    test_positive: list[tuple[str, str]]  # (input, expected_match)
    test_negative: list[str]  # inputs that should NOT match


# ============================================================
# RADICADO PATTERNS
# ============================================================

RAD_23_CONTINUOUS = RegexPattern(
    name="radicado_23_continuous",
    pattern=re.compile(r"(68[\d]{17,21})"),
    description="Radicado 23 dígitos sin separadores (ej: 68001400902720260003400)",
    test_positive=[("RAD 68001400902720260003400", "68001400902720260003400")],
    test_negative=["RAD 12345"],
)

RAD_23_WITH_SEPARATORS = RegexPattern(
    name="radicado_23_separators",
    pattern=re.compile(
        r"(68[\d]{3,5}[-\s\.]?\d{2}[-\s\.]?\d{2}[-\s\.]?\d{3}[-\s\.]?\d{4}[-\s\.]?\d{5}[-\s\.]?\d{2})"
    ),
    description="Radicado 23 dígitos con guiones/puntos/espacios",
    test_positive=[
        ("68001-40-09-027-2026-00034-00", "68001-40-09-027-2026-00034-00"),
        ("68.679.40.71.001.2026.00032.00", "68.679.40.71.001.2026.00032.00"),
    ],
    test_negative=["123456789"],
)

RAD_T_FORMAT = RegexPattern(
    name="radicado_t_format",
    pattern=re.compile(r"T[-\s]?(\d{3,5})\s*/\s*(20\d{2})", re.IGNORECASE),
    description="Formato T-00053/2026",
    test_positive=[("T-00053/2026", "00053")],
    test_negative=["T123"],
)

RAD_LABEL = RegexPattern(
    name="radicado_label",
    pattern=re.compile(
        r"(?:RAD|Rad|RADICADO|Radicado)\.?\s*:?\s*#?\s*(?:No\.?\s*)?(20\d{2})[-\s]?0*(\d{2,5})",
        re.IGNORECASE,
    ),
    description="RAD./Radicado No. 2026-00095",
    test_positive=[("RAD. 2026-00095", "2026"), ("Radicado No. 2026-030", "2026")],
    test_negative=["texto sin radicado"],
)

RAD_GENERIC = RegexPattern(
    name="radicado_generic",
    pattern=re.compile(r"(20\d{2})[-\s](\d{2,5})"),
    description="Patrón genérico 20XX-NNNNN (fallback)",
    test_positive=[("caso 2026-00095", "2026")],
    test_negative=["fecha 2026"],
)

# ============================================================
# FOREST PATTERNS (moved from forest_extractor.py)
# ============================================================

FOREST_SPECIFIC = RegexPattern(
    name="forest_specific",
    pattern=re.compile(
        r'(?:El\s+n[uú]mero\s+de\s+radicado\s+es'
        r'|[Cc]on\s+n[uú]mero\s+de\s+radicado'
        r'|radicado\s+(?:y\s+enviado|es))'
        r'\s+(\d{7,13})',
        re.IGNORECASE,
    ),
    description="Frase de tutelas@santander.gov.co: 'El número de radicado es X'",
    test_positive=[("El número de radicado es 20260054965", "20260054965")],
    test_negative=["Radicado judicial 68001400900"],
)

FOREST_KEYWORD = RegexPattern(
    name="forest_keyword",
    pattern=re.compile(r'(?:FOREST|forest|Forest)\s*(?:No\.?\s*)?:?\s*(\d{5,13})'),
    description="Keyword FOREST seguido de número",
    test_positive=[("FOREST: 20260024347", "20260024347"), ("Forest No. 2695882", "2695882")],
    test_negative=["FOREST sin numero"],
)

# ============================================================
# ACCIONANTE PATTERNS
# ============================================================

ACCIONANTE_EXPLICIT = RegexPattern(
    name="accionante_explicit",
    pattern=re.compile(r"(?i)accionante[:\s]+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{5,50})"),
    description="'ACCIONANTE: NOMBRE COMPLETO'",
    test_positive=[("ACCIONANTE: LAURA VIVIANA CHACON ARCE", "LAURA VIVIANA CHACON ARCE")],
    test_negative=["sin accionante aqui"],
)

ACCIONANTE_DEMANDANTE = RegexPattern(
    name="accionante_demandante",
    pattern=re.compile(r"(?i)demandante[:\s]+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{5,50})"),
    description="'DEMANDANTE: NOMBRE'",
    test_positive=[("Demandante: MERLY PINZON GALVIS", "MERLY PINZON GALVIS")],
    test_negative=[],
)

ACCIONANTE_PROMOVIDA = RegexPattern(
    name="accionante_promovida",
    pattern=re.compile(
        r"(?i)promovida?\s+por\s+(?:el señor |la señora )?([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{5,50})"
    ),
    description="'promovida por el señor NOMBRE'",
    test_positive=[("promovida por el señor GABRIEL GARNICA SARMIENTO", "GABRIEL GARNICA SARMIENTO")],
    test_negative=[],
)

# ============================================================
# PERSONERO PATTERN
# ============================================================

PERSONERO_MUNICIPIO = RegexPattern(
    name="personero_municipio",
    pattern=re.compile(
        r'(?i)(?:personero|personera|personería|personeria)\s+'
        r'(?:municipal\s+)?(?:de|del)\s+(?:el\s+)?([A-Za-záéíóúñÁÉÍÓÚÑ\s]{3,30})',
    ),
    description="Extrae municipio de 'Personero Municipal de X'",
    test_positive=[("Personero Municipal de Guavatá", "Guavatá")],
    test_negative=["Juez de Bucaramanga"],
)

# ============================================================
# DOCUMENT CLASSIFICATION
# ============================================================

DOC_AUTO_ADMISORIO = re.compile(r"(?i)(auto\s*avoca|auto\s*admite|admite\s*tutela|avoca)")
DOC_SENTENCIA = re.compile(r"(?i)(sentencia|fallo)")
DOC_IMPUGNACION = re.compile(r"(?i)(impugna)")
DOC_INCIDENTE = re.compile(r"(?i)(incidente|desacato)")

# ============================================================
# ABOGADO PATTERN
# ============================================================

ABOGADO_FOOTER = RegexPattern(
    name="abogado_footer",
    pattern=re.compile(r"(?i)(?:proyect[oó]|elabor[oó]|revis[oó]|aprob[oó])\s*[:\.]\s*(.+?)(?:\n|$)"),
    description="'Proyectó: NOMBRE' en footer de DOCX de respuesta",
    test_positive=[("Proyectó: Juan Diego Cruz Lizcano", "Juan Diego Cruz Lizcano")],
    test_negative=[],
)

# ============================================================
# NORMALIZATION PATTERNS
# ============================================================

LAWYER_CLEANUP = re.compile(r'\s+(CPS|OPS|CONTRATO|CC\.?\s*\d+).*$', re.IGNORECASE)
CITY_CLEANUP = re.compile(r',?\s*(?:Santander|Colombia).*$', re.IGNORECASE)

# ============================================================
# UTILITY: Run all patterns
# ============================================================

ALL_PATTERNS = [
    RAD_23_CONTINUOUS, RAD_23_WITH_SEPARATORS, RAD_T_FORMAT, RAD_LABEL, RAD_GENERIC,
    FOREST_SPECIFIC, FOREST_KEYWORD,
    ACCIONANTE_EXPLICIT, ACCIONANTE_DEMANDANTE, ACCIONANTE_PROMOVIDA,
    PERSONERO_MUNICIPIO, ABOGADO_FOOTER,
]


def validate_all_patterns() -> dict[str, bool]:
    """Self-test: validar todos los patrones contra sus test cases."""
    results = {}
    for pat in ALL_PATTERNS:
        ok = True
        for text_in, expected in pat.test_positive:
            m = pat.pattern.search(text_in)
            if not m:
                ok = False
                break
        for text_in in pat.test_negative:
            m = pat.pattern.search(text_in)
            if m:
                ok = False
                break
        results[pat.name] = ok
    return results
