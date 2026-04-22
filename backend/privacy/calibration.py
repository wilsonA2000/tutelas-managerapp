"""Calibración contextual del detector y gate PII (v5.3.1).

Filtros aprendidos de datos reales (10 casos analizados) que eliminan
falsos positivos de CC_BARE que disparan gate sin necesidad:

- NIT Gobernación y entidades públicas (890201235-6, 900464857-1...).
- Proc # / Folios / Anexos (metadata FOREST interna, no PII).
- Fechas YYYYMMDD embebidas en nombres de archivo (20241206).
- Resolución No., Acuerdo No., Decreto No. (actos administrativos).
- Tarjeta Profesional (T.P. No. XXXXXX).
- Teléfonos fijos con indicativo ((097) XXXXXXX, 60XXXXXXXX).

También aporta detectores adicionales que sí deben capturar:
- CC formato `1.096961643` (un solo punto, común en OCR).
- "Tercero: <N> <NOMBRE>" (terceros internos con CC + nombre).
"""

from __future__ import annotations

import re
from typing import Optional

# ============================================================
# Entidades públicas colombianas cuyo NIT se puede mencionar libremente
# (son información pública registrada en Cámara y Comercio / DIAN).
# ============================================================

PUBLIC_NITS: frozenset[str] = frozenset({
    "890201235",   # Gobernación de Santander
    "890201235-6",
    "900464857",   # SED Bucaramanga
    "800099860",   # ICBF
    "899999090",   # Ministerio de Educación Nacional
    "900058856",   # Nueva EPS
    "900156264",   # Salud Total EPS
    "800130907",   # Sanitas EPS
    "860045904",   # Cafesalud
    "890903407",   # Famisanar
    "805000427",   # Coomeva EPS
    "800088702",   # Medimás EPS
})

# ============================================================
# Contextos negativos: tokens alrededor del número que indican que NO es CC.
# Si cualquiera aparece en los ~30 caracteres previos, skip.
# ============================================================

_NEGATIVE_PREFIX_PATTERNS = [
    re.compile(r"\b(?:Proc(?:eso)?\.?\s*#?\s*|Folios?\s*:|Anexos?\s*:|"
               r"Radicad[oa]\s+Forest\s+(?:No\.?\s*)?|"
               r"forest\s+(?:No\.?\s*)?|proceso\s+forest\s+|"
               r"T\.?P\.?\s*(?:No\.?\s*)?|Tarjeta\s+Profesional\s+(?:No\.?\s*)?|"
               r"Resoluci[oó]n\s+(?:No\.?\s*)?|Acuerdo\s+(?:No\.?\s*)?|"
               r"Decreto\s+(?:No\.?\s*)?|Sentencia\s+(?:No\.?\s*)?|"
               r"Acta\s+(?:No\.?\s*)?|Expediente\s+(?:No\.?\s*)?|"
               r"CSJ\s*|NIT\.?\s*:?|Nit\.?\s*:?\s*|"
               r"c[oó]digo\s+DANE\s+|DANE\s+(?:No\.?\s*)?|"
               r"Indicativo\s+|PBX\s*:?\s*|Extensi[oó]n\s+|Ext\.?\s*|"
               r"folio\s+|hoja\s+|p[aá]gina\s+)", re.IGNORECASE),
]

# ============================================================
# Contextos negativos de sufijo (tokens DESPUÉS del número).
# ============================================================

_NEGATIVE_SUFFIX_PATTERNS = [
    re.compile(r"^\s*(?:\.docx?|\.pdf|\.xlsx?|\.md|\.doc)", re.IGNORECASE),  # nombres de archivo
    re.compile(r"^\s*(?:de\s+(?:20\d{2}|19\d{2}))"),   # "22605 de 2024" → resolución
    re.compile(r"^\s*-\d\b"),                           # NIT formato "890201235-6"
]


def _is_file_date(number: str) -> bool:
    """YYYYMMDD formato (ej. 20241206, 20260414). Dimensión + rango year."""
    if len(number) != 8 or not number.isdigit():
        return False
    year = int(number[:4])
    month = int(number[4:6])
    day = int(number[6:8])
    return 2000 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31


def _is_dotted_date(number: str) -> bool:
    """Fecha DD.MM.YYYY que OCR convierte a `03.006.2026` etc."""
    parts = number.split(".")
    if len(parts) != 3:
        return False
    try:
        d, m, y = int(parts[0]), int(parts[1].lstrip("0") or "0"), int(parts[2])
        return 1 <= d <= 31 and 1 <= m <= 12 and 2000 <= y <= 2099
    except ValueError:
        return False


def _is_public_nit(number: str, text_before: str) -> bool:
    if number in PUBLIC_NITS:
        return True
    # NIT completo con dígito de verificación
    for nit in PUBLIC_NITS:
        if number.startswith(nit):
            return True
    # Contexto "NIT" justo antes
    if re.search(r"\bNIT\.?\s*:?\s*$", text_before, re.IGNORECASE):
        return True
    return False


def is_false_positive_cc(
    number: str,
    text: str,
    start: int,
    end: int,
    window: int = 40,
) -> bool:
    """Decide si un número detectado como posible CC es en realidad un falso positivo.

    Args:
        number: la cadena numérica detectada.
        text: texto completo.
        start, end: offsets del match en el texto.
        window: caracteres de contexto antes/después a inspeccionar.

    Returns:
        True si es falso positivo (NO redactar, NO disparar gate).
    """
    before = text[max(0, start - window):start]
    after = text[end:min(len(text), end + window)]

    # 1. Fecha YYYYMMDD o DD.MM.YYYY
    if _is_file_date(number) or _is_dotted_date(number):
        return True

    # 2. NIT público
    if _is_public_nit(number, before):
        return True

    # 3. Contexto negativo antes (Proc #, Folios, T.P. No., Resolución, etc.)
    for pat in _NEGATIVE_PREFIX_PATTERNS:
        if pat.search(before):
            return True

    # 4. Contexto negativo después (.docx, "de 20XX", dígito de verificación)
    for pat in _NEGATIVE_SUFFIX_PATTERNS:
        if pat.search(after):
            return True

    # 5. Número demasiado corto (< 7 dígitos) para ser CC real
    digits_only = re.sub(r"\D", "", number)
    if len(digits_only) < 7:
        return True

    # 6. Patrón obvio de teléfono fijo con indicativo: (097) 6577768
    full_context = before[-10:] + number + after[:10]
    if re.search(r"\(\d{2,3}\)\s*" + re.escape(number), full_context):
        return True

    return False


# ============================================================
# CC con separador raro (1.XXXXXXXXX — un solo punto)
# ============================================================

CC_SINGLE_DOT_PATTERN = re.compile(
    r"(?:C\.?C\.?|[Cc][eé]dula)[\s:\.]*(?:No\.?\s*)?(\d{1,2}\.\d{9,10})\b",
)

CC_SINGLE_DOT_BARE = re.compile(r"\b1\.\d{9,10}\b")  # NUIP/CC con punto tras 1


def detect_cc_single_dot(text: str) -> list[tuple[int, int, str]]:
    """Detecta CCs con formato `1.096961643` (común en Santander OCR)."""
    spans = []
    for m in CC_SINGLE_DOT_PATTERN.finditer(text):
        spans.append((m.start(1), m.end(1), m.group(1)))
    for m in CC_SINGLE_DOT_BARE.finditer(text):
        # Solo si hay contexto de CC cerca
        before = text[max(0, m.start() - 30):m.start()]
        if re.search(r"(?:C\.?C\.?|c[eé]dula)", before, re.IGNORECASE):
            spans.append((m.start(), m.end(), m.group()))
    return spans


# ============================================================
# "Tercero: <N> <NOMBRE>" — pattern FOREST interno que une CC + nombre
# ============================================================

TERCERO_PATTERN = re.compile(
    r"Tercero\s*:?\s*(\d{6,10})\s+([A-ZÁÉÍÓÚÑ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ]{2,}){1,4})",
)


def detect_tercero_entries(text: str) -> list[tuple[str, str, int, int]]:
    """Detecta 'Tercero: 49736592 OTILIA LUNA LOPEZ' → (cc, nombre, start, end)."""
    results = []
    for m in TERCERO_PATTERN.finditer(text):
        results.append((m.group(1), m.group(2).strip(), m.start(), m.end()))
    return results
