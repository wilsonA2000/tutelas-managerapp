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
        # Separadores: guion ASCII (-), en-dash (\u2013), em-dash (\u2014), punto, espacios.
        # Dos formatos reconocidos:
        #  (a) 7 bloques: NNNNN-NN-NN-NNN-YYYY-NNNNN-NN (Santander canonico)
        #  (b) 4 bloques: NNNNNNNNNNNN-YYYY-NNNNN-NN (bloque compuesto 12d primero)
        # [-\s\.\u2013\u2014]* con * permite multiples separadores (ej: " \u2013 ").
        r"(68[\d]{3,5}[-\s\.\u2013\u2014]?\d{2}[-\s\.\u2013\u2014]?\d{2}[-\s\.\u2013\u2014]?\d{3}[-\s\.\u2013\u2014]?\d{4}[-\s\.\u2013\u2014]?\d{5}[-\s\.\u2013\u2014]?\d{2}"
        r"|68[\d]{10}[-\s\.\u2013\u2014]*\d{4}[-\s\.\u2013\u2014]*\d{5}[-\s\.\u2013\u2014]*\d{2})"
    ),
    description="Radicado 23 dígitos con guiones/puntos/espacios/dashes-unicode",
    test_positive=[
        ("68001-40-09-027-2026-00034-00", "68001-40-09-027-2026-00034-00"),
        ("686694089001 \u2013 2026 \u2013 00060 \u2013 00", "686694089001 \u2013 2026 \u2013 00060 \u2013 00"),
        ("686694089001-2026-00060-00", "686694089001-2026-00060-00"),
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
    # F1 (v5.0): separador obligatorio guion/dash + negative lookahead que impide FOREST (>5 digitos contiguos)
    # Acepta: "RAD. 2026-00095", "Radicado No. 2026-030", "Radicado: 2026-00115", "RAD 2026-00057"
    # Rechaza: "numero de radicado 20260066132" (FOREST 11d), "radicado 20260069467" (FOREST)
    pattern=re.compile(
        r"(?:RAD\.?|RADICADO(?:\s+No\.?|\s*:)|Rad(?:icado)?\.|Rad(?:icado)?:)"
        r"\s*#?\s*(?:No\.?\s*)?"
        r"(20\d{2})[-\u2013\u2014/]\s*0*(\d{2,5})(?!\d)",
        re.IGNORECASE,
    ),
    description="RAD./Radicado No./Radicado: 2026-00095 con separador guion obligatorio",
    test_positive=[
        ("RAD. 2026-00095", "00095"),
        ("Radicado No. 2026-030", "030"),
        ("RADICADO: 2026-00115", "00115"),
        ("Rad. 2026-00057", "00057"),
    ],
    test_negative=[
        "texto sin radicado",
        "numero de radicado 20260066132",  # FOREST 11d (B1)
        "Con numero de radicado 20260066132",  # FOREST 11d (B1)
        "con número de radicado 20260069467",  # FOREST 11d (B1)
        "radicado 20260066132",  # FOREST 11d (B1)
    ],
)

RAD_GENERIC = RegexPattern(
    name="radicado_generic",
    # F1 (v5.0): negative lookahead agregado para rechazar FOREST continuo (20260066132)
    pattern=re.compile(r"(20\d{2})[-\u2013\u2014]\s*0*(\d{2,5})(?!\d)"),
    description="Patrón genérico 20XX-NNNNN con separador obligatorio (fallback)",
    test_positive=[("caso 2026-00095", "00095"), ("ref 2026-030 ok", "030")],
    test_negative=[
        "fecha 2026",
        "radicado 20260066132",  # FOREST 11d (B1)
        "20260069467",  # FOREST continuo (B1)
    ],
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

# ============================================================
# v5.2 FORENSIC PATTERNS (emulan proceso cognitivo humano)
# ============================================================

# Cédula de ciudadanía — el identificador MÁS CONFIABLE para matching
CC_ACCIONANTE = RegexPattern(
    name="cc_accionante",
    pattern=re.compile(
        r"(?:C\.?C\.?|[Cc][eé]dula(?:\s+de\s+[Cc]iudadan[íi]a)?|"
        r"[Ii]dentificad[oa]\s+con\s+(?:documento|c[eé]dula)(?:\s+de\s+ciudadan[íi]a)?)"
        r"[\s:\.]*(?:No\.?\s*)?(\d{6,10})(?!\d)",
        re.IGNORECASE,
    ),
    description="Cédula de ciudadanía colombiana (6-10 digitos)",
    test_positive=[
        ("C.C. 1077467661", "1077467661"),
        ("identificada con documento: 91071881", "91071881"),
        ("cédula de ciudadanía No. 1005461409", "1005461409"),
    ],
    test_negative=["telefono 3204992211"],
)

# Tutela en línea (número del sistema judicial colombiano)
TUTELA_ONLINE_NO = RegexPattern(
    name="tutela_online_no",
    pattern=re.compile(
        r"Tutela\s+(?:en\s+L[íi]nea\s+)?(?:con\s+n[úu]mero\s+|No\.?\s*)(\d{7,8})",
        re.IGNORECASE,
    ),
    description="Número de tutela en línea generado por apptutelasbga (7-8 dígitos)",
    test_positive=[
        ("Tutela en Línea con número 3645440", "3645440"),
        ("Generación de Tutela en línea No 3722226", "3722226"),
    ],
    test_negative=["Tutela 2026-00057"],
)

# Acta de reparto civil
ACTA_REPARTO_NO = RegexPattern(
    name="acta_reparto_no",
    pattern=re.compile(
        r"ACTA\s+DE\s+REPARTO(?:\s+\w+)?\s+No\.?\s*(\d+)",
        re.IGNORECASE,
    ),
    description="Número de acta de reparto (ACTA DE REPARTO CIVIL No. 148)",
    test_positive=[("ACTA DE REPARTO CIVIL No. 148", "148")],
    test_negative=[],
)

# Expediente disciplinario
EXPEDIENTE_DISCIPLINARIO = RegexPattern(
    name="expediente_disciplinario",
    pattern=re.compile(r"Expediente\s+(?:No\.?\s*)?(\d{3,4}[-–]\d{2})", re.IGNORECASE),
    description="Expediente disciplinario (formato 160-25)",
    test_positive=[("Expediente No. 160-25", "160-25")],
    test_negative=[],
)

# NUIP menor (Registro Civil)
NUIP_MENOR = RegexPattern(
    name="nuip_menor",
    pattern=re.compile(r"(?:RC|Registro\s+Civil)\s+(?:No\.?\s*)?(\d{10,11})", re.IGNORECASE),
    description="NUIP de menor (Registro Civil 10-11 dígitos)",
    test_positive=[("Registro Civil No. 1130104808", "1130104808")],
    test_negative=[],
)

ALL_PATTERNS = [
    RAD_23_CONTINUOUS, RAD_23_WITH_SEPARATORS, RAD_T_FORMAT, RAD_LABEL, RAD_GENERIC,
    FOREST_SPECIFIC, FOREST_KEYWORD,
    ACCIONANTE_EXPLICIT, ACCIONANTE_DEMANDANTE, ACCIONANTE_PROMOVIDA,
    PERSONERO_MUNICIPIO, ABOGADO_FOOTER,
    CC_ACCIONANTE, TUTELA_ONLINE_NO, ACTA_REPARTO_NO, EXPEDIENTE_DISCIPLINARIO, NUIP_MENOR,
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
