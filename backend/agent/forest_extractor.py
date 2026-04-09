"""Extracción de FOREST desde múltiples fuentes con validación.

FOREST es el número de radicado interno del sistema FOREST de la Gobernación
de Santander. Es un número de 7-13 dígitos que SOLO proviene de correos de
tutelas@santander.gov.co con frases específicas.

Fuentes (en orden de prioridad):
1. Gmail PDFs guardados en carpeta (frase "El número de radicado es X")
2. Emails en la DB (body_preview con patrón específico)
3. Archivos Email_*.md en la carpeta (body completo de correos)
"""

import re
from dataclasses import dataclass


# Blacklist de números que NO son FOREST reales
FOREST_BLACKLIST = {"3634740"}

# Patrón principal: frase de tutelas@santander.gov.co
FOREST_PATTERN = re.compile(
    r'(?:El\s+n[uú]mero\s+de\s+radicado\s+es'
    r'|[Cc]on\s+n[uú]mero\s+de\s+radicado'
    r'|radicado\s+(?:y\s+enviado|es)'
    r'|[Ee]l\s+radicado\s+es'
    r'|[Rr]adicado\s+interno:?\s*'
    r'|[Nn][uú]mero\s+de\s+radicaci[oó]n:?\s*'
    r'|[Rr]ef\.?\s*:?\s*#?\s*)'
    r'\s*(\d{7,13})',
    re.IGNORECASE,
)

# Patrón secundario: keyword FOREST seguido de número
FOREST_KEYWORD_PATTERN = re.compile(
    r'(?:FOREST|forest|Forest)\s*(?:No\.?\s*)?:?\s*(\d{5,13})'
)

# Patrón genérico: cualquier número de 7-11 dígitos (fallback)
FOREST_GENERIC_PATTERN = re.compile(r'\b(\d{7,11})\b')


@dataclass
class ForestResult:
    """Resultado de extracción de FOREST."""
    value: str
    source: str
    confidence: str  # ALTA, MEDIA, BAJA


def is_valid_forest(num: str) -> bool:
    """Validar que un número candidato sea un FOREST real."""
    if not num or num in FOREST_BLACKLIST:
        return False
    digits = re.sub(r'\D', '', num)
    if len(digits) < 7:
        return False
    # Los radicados judiciales empiezan por 68 (código Santander)
    if digits.startswith('68'):
        return False
    if digits == '0' * len(digits):
        return False
    return True


def extract_forest_from_sources(
    doc_texts: list[dict],
    case_emails: list = None,
) -> ForestResult | None:
    """Extraer FOREST desde múltiples fuentes en orden de prioridad.

    Args:
        doc_texts: Lista de dicts con keys "filename" y "text" (documentos del caso)
        case_emails: Lista de objetos Email de la DB (con .body_preview, .subject)

    Returns:
        ForestResult con el FOREST encontrado, o None si no se encontró.
    """
    case_emails = case_emails or []

    # FUENTE 1: Gmail PDFs guardados como documentos en la carpeta
    result = _extract_from_gmail_pdfs(doc_texts)
    if result:
        return result

    # FUENTE 2: Emails en la DB (body_preview)
    result = _extract_from_email_db(case_emails)
    if result:
        return result

    # FUENTE 3: Archivos Email_*.md en la carpeta
    result = _extract_from_email_md(doc_texts)
    if result:
        return result

    return None


def _extract_from_gmail_pdfs(doc_texts: list[dict]) -> ForestResult | None:
    """Fuente 1: Gmail PDFs guardados en la carpeta del caso."""
    for doc_info in doc_texts:
        filename = doc_info.get("filename", "")
        text = doc_info.get("text", "")
        if not filename.upper().startswith("GMAIL") and "GMAIL" not in filename.upper():
            continue
        match = FOREST_PATTERN.search(text)
        if match and is_valid_forest(match.group(1)):
            return ForestResult(
                value=match.group(1),
                source=f"gmail_pdf/{filename}",
                confidence="ALTA",
            )
    return None


def _extract_from_email_db(case_emails: list) -> ForestResult | None:
    """Fuente 2: Emails en la DB (body_preview + subject)."""
    for em in case_emails:
        body = getattr(em, 'body_preview', '') or ''
        subject = getattr(em, 'subject', '') or ''
        em_id = getattr(em, 'id', '')

        # Patrón específico de tutelas@santander.gov.co
        match = FOREST_PATTERN.search(body)
        if match and is_valid_forest(match.group(1)):
            return ForestResult(
                value=match.group(1),
                source=f"email_db/{subject or em_id}",
                confidence="ALTA",
            )

        # Fallback: números genéricos de 7-11 dígitos en body
        candidates = FOREST_GENERIC_PATTERN.findall(body)
        for c in candidates:
            if is_valid_forest(c):
                return ForestResult(
                    value=c,
                    source=f"email_db/{subject or em_id}",
                    confidence="MEDIA",
                )

        # Fallback 2: keyword FOREST en subject o body
        combined = subject + " " + body
        if "FOREST" in combined.upper():
            forests = FOREST_KEYWORD_PATTERN.findall(combined)
            for f in forests:
                if is_valid_forest(f):
                    return ForestResult(
                        value=f,
                        source=f"email_forest_keyword/{subject or em_id}",
                        confidence="MEDIA",
                    )

    return None


def _extract_from_email_md(doc_texts: list[dict]) -> ForestResult | None:
    """Fuente 3: Archivos Email_*.md en la carpeta del caso."""
    for doc_info in doc_texts:
        filename = doc_info.get("filename", "")
        text = doc_info.get("text", "")
        if not filename.startswith("Email_"):
            continue
        # Solo confiar si el email es de tutelas@santander.gov.co
        if "tutelas@santander" not in text.lower():
            continue
        match = FOREST_PATTERN.search(text)
        if match and is_valid_forest(match.group(1)):
            return ForestResult(
                value=match.group(1),
                source=f"email_md/{filename}",
                confidence="ALTA",
            )
    return None
