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
        # v5.4.3: secuencia mínimo 3 dígitos (con marcador "RAD" hay contexto)
        r"(20\d{2})[-\u2013\u2014/]\s*0*(\d{3,5})(?!\d)",
        re.IGNORECASE,
    ),
    description="RAD./Radicado No./Radicado: 2026-00095 con separador guion obligatorio",
    test_positive=[
        ("RAD. 2026-00095", "00095"),
        ("Radicado No. 2026-030", "030"),  # 3d ok con marcador RAD
        ("RADICADO: 2026-00115", "00115"),
        ("Rad. 2026-00057", "00057"),
        ("Rad. 2026-10021", "10021"),  # 5d completo (caso Ronald Diaz)
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
    # v5.4.3: secuencia exige EXACTAMENTE 5 dígitos (era {2,5} → causaba zfill
    # bug: "2026-1002" capturaba "1002" → rad_corto "2026-01002" cuando el
    # rad23 oficial tenía secuencia "10021"). El shape canónico colombiano de
    # rad_corto es 5 dígitos. Como fallback sin marcador "RAD", ser estricto.
    pattern=re.compile(r"(20\d{2})[-\u2013\u2014](\d{5})(?!\d)"),
    description="Patrón genérico 20XX-NNNNN con secuencia estricta de 5 dígitos (fallback)",
    test_positive=[("caso 2026-00095", "00095"), ("ref 2026-10021 ok", "10021")],
    test_negative=[
        "fecha 2026",
        "radicado 20260066132",  # FOREST 11d (B1)
        "20260069467",  # FOREST continuo (B1)
        "caso 2026-1002",  # 4 dígitos — era el bug, ahora rechazado
        "ref 2026-030 ok",  # 3 dígitos — ambiguo, rechazado
    ],
)

# v6.0.1: Pattern para "YYYY NNNNN" / "YYYYNNNNN" continuos (sin separador)
# Común en subjects: "RAD 202600026", "TUTELA 202600069". Exige exactamente 5d
# de secuencia con word boundary para rechazar FOREST (11-13d totales).
RAD_CONTINUOUS_SHORT = RegexPattern(
    name="radicado_continuous_short",
    pattern=re.compile(r"\b(20\d{2})(\d{5})\b(?!\d)"),
    description="Continuo YYYYNNNNN sin separador (9 dígitos exactos, fallback extra)",
    test_positive=[
        ("RAD 202600026", "00026"),
        ("TUTELA 202600069", "00069"),
        ("ACCION DE TUTELA 202600059 URGENTE", "00059"),
    ],
    test_negative=[
        "20260066132",  # FOREST 11d (word-boundary + no-digit rechazará)
        "202600069467",  # FOREST 12d
        "texto 2026 solo",
    ],
)

# v6.0.1: Pattern para 3-4 dígitos con marcador JUDICIAL AMPLIADO
# Captura marcador ANTES o DESPUÉS del radicado corto (ambos órdenes).
# Markers: TUTELA|FALLO|OFICIO|SENTENCIA|ACCION|NOTIFIC|CUMPL|IMPUG|INCIDENTE|
#          REQUERIM|RESPUESTA|CONTEST|DESACATO|ADMIT|VINCULA|TRASLADO
# Separador flexible (.{0,40}?) para aceptar "INCIDENTE DESACATO 2025-0020".
_JUDICIAL_MARKERS = (
    r"TUTELA|FALLO|OFICIO|SENTENCIA|ACCI[OÓ]N\s+DE\s+TUTELA"
    r"|NOTIFIC\w*|CUMPLIM\w*|IMPUGN\w*|INCIDENTE|REQUERIM\w*"
    r"|RESPUESTA|CONTEST\w*|TRASLADO|VINCULA\w*|DESACATO|ADMIT\w*"
)
RAD_JUDICIAL_CONTEXT = RegexPattern(
    name="radicado_judicial_context",
    pattern=re.compile(
        r"(?:"
        # Orden A: MARKER ... 2026-007
        rf"(?:{_JUDICIAL_MARKERS}).{{0,40}}?(20\d{{2}})[-\u2013\u2014/]\s*0*(\d{{3,4}})(?!\d)"
        r"|"
        # Orden B: 2026-258 ... MARKER
        rf"(20\d{{2}})[-\u2013\u2014/]\s*0*(\d{{3,4}})(?!\d).{{0,40}}?(?:{_JUDICIAL_MARKERS})"
        r")",
        re.IGNORECASE | re.DOTALL,
    ),
    description="Rad corto 3-4d con marcador judicial antes o después (zfill a 5d)",
    test_positive=[
        ("Oficio cumplimiento fallo 2026-007", "007"),
        ("RESPUESTA REQUERIMIENTO 2025-127", "127"),
        ("RV: RESPUESTA ACCIÓN DE TUTELA 2026-108", "108"),
        ("AUTO INCIDENTE DESACATO 2025-0020", "0020"),
        ("RV: 2026-258 NOTIFICACIÓN FALLO DE TUTELA", "258"),
    ],
    test_negative=[
        "caso 2026-007 ref",  # sin marker judicial
        "factura 2026-030",
    ],
)

# v6.0.1: Pattern para rad_corto con 6 dígitos (strip leading zero → 5d)
# Casos como "contestación tutela 2026-000115" o "RAD 2026-000058"
# donde el escritor usó 6 dígitos por error. Aceptamos y normalizamos.
RAD_SIX_DIGITS = RegexPattern(
    name="radicado_six_digits",
    pattern=re.compile(r"(20\d{2})[-\u2013\u2014](0\d{5})(?!\d)"),
    description="Rad corto con 6d (solo si empieza con 0, strip → 5d)",
    test_positive=[
        ("contestación tutela 2026-000115", "000115"),
        ("RAD 2026-000058", "000058"),
    ],
    test_negative=[
        "FOREST 2026-100115",  # no empieza con 0, es otra cosa
        "2026-100000",  # no strippable
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

# ============================================================
# v5.5 SELLO / WATERMARK PATTERNS (aparecen en zonas VISUAL y FOOTER_TAIL)
# ============================================================

SELLO_RADICADOR = RegexPattern(
    name="sello_radicador",
    pattern=re.compile(
        r"(?:radicad[oa]ra?|RADICADA?\s+EN|sello\s+de\s+radicaci[oó]n)"
        r"[\s:.\-]*(\d{3,6})",
        re.IGNORECASE,
    ),
    description="Número de sello de radicación (sello rotado en esquina)",
    test_positive=[
        ("Radicadora: 12345", "12345"),
        ("RADICADA EN 987", "987"),
    ],
    test_negative=[],
)

FECHA_RECIBIDO = RegexPattern(
    name="fecha_recibido",
    pattern=re.compile(
        r"(?:recibid[oa]|fecha\s+de\s+recibo|recepci[oó]n)"
        r"[\s:.\-]*(\d{1,2}[/\-]\d{1,2}[/\-](?:20)?\d{2,4})",
        re.IGNORECASE,
    ),
    description="Fecha de recepción en sello del juzgado",
    test_positive=[
        ("Recibido: 15/03/2026", "15/03/2026"),
        ("Fecha de recibo 03-04-26", "03-04-26"),
    ],
    test_negative=[],
)

PROC_GOBERNACION = RegexPattern(
    name="proc_gobernacion",
    pattern=re.compile(
        r"(?:Proc|PROC|Proceso|PROCESO)\.?\s*(?:No\.?\s*)?(\d{4,7})",
    ),
    description="Número Proc interno de la Gobernación (watermark DOCX)",
    test_positive=[("Proc. 45678", "45678"), ("PROCESO 123456", "123456")],
    test_negative=[],
)

SELLO_JUZGADO = RegexPattern(
    name="sello_juzgado",
    pattern=re.compile(
        r"(?i)(?:JUZGADO|TRIBUNAL)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{3,40}(?:\s+DE\s+[A-ZÁÉÍÓÚÑ\s]+)?)",
    ),
    description="Identificación de juzgado en sello (texto rotado o header)",
    test_positive=[
        ("JUZGADO PRIMERO PROMISCUO DE FAMILIA DE BUCARAMANGA", "PRIMERO PROMISCUO DE FAMILIA DE BUCARAMANGA"),
    ],
    test_negative=[],
)

ALL_PATTERNS = [
    RAD_23_CONTINUOUS, RAD_23_WITH_SEPARATORS, RAD_T_FORMAT, RAD_LABEL, RAD_GENERIC,
    FOREST_SPECIFIC, FOREST_KEYWORD,
    ACCIONANTE_EXPLICIT, ACCIONANTE_DEMANDANTE, ACCIONANTE_PROMOVIDA,
    PERSONERO_MUNICIPIO, ABOGADO_FOOTER,
    CC_ACCIONANTE, TUTELA_ONLINE_NO, ACTA_REPARTO_NO, EXPEDIENTE_DISCIPLINARIO, NUIP_MENOR,
    SELLO_RADICADOR, FECHA_RECIBIDO, PROC_GOBERNACION, SELLO_JUZGADO,
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
