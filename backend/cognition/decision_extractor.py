"""Extractor de decisión del juez: CONCEDE / NIEGA / IMPROCEDENTE / PARCIAL.

Opera sobre la zona 'resuelve' o 'concede_niega' del documento. Emula cómo
un abogado localiza el fallo: busca las palabras clave "RESUELVE", después
enumera "PRIMERO:", "SEGUNDO:", y extrae el verbo principal (TUTELAR,
AMPARAR, NEGAR, DECLARAR IMPROCEDENTE).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.cognition.zone_classifier import DocZones


DECISION_VERBS: dict[str, list[re.Pattern]] = {
    "CONCEDE PARCIALMENTE": [
        re.compile(r"\bCONCEDE\s+PARCIAL(?:MENTE)?\b", re.IGNORECASE),
        re.compile(r"\bTUTELAR\s+PARCIAL(?:MENTE)?\b", re.IGNORECASE),
        re.compile(r"\bAMPARAR\s+PARCIAL(?:MENTE)?\b", re.IGNORECASE),
    ],
    "CONCEDE": [
        # Formas estándar (infinitivo)
        re.compile(r"\b(?:TUTELAR|AMPARAR|CONCEDER(?:SE)?|PROTEGE(?:R|RSE)|RECONOCER)\b", re.IGNORECASE),
        # Formas imperativas en fallos (TUTÉLESE, AMPÁRESE, CONCÉDASE)
        re.compile(r"\b(?:TUT[ÉE]LESE|AMP[ÁA]RESE|CONC[ÉE]DASE|PROTEJASE)\b", re.IGNORECASE),
        # Reflexivo
        re.compile(r"\bse\s+(?:concede|tutela|ampara|protege)\b", re.IGNORECASE),
    ],
    "NIEGA": [
        re.compile(r"\b(?:NEGAR|NI[ÉE]GASE|NI[ÉE]GUESE|DENEGAR|DENI[ÉE]GASE|DESESTIMAR)\b", re.IGNORECASE),
        re.compile(r"\bno\s+amparar\b|\bno\s+tutelar\b", re.IGNORECASE),
    ],
    "IMPROCEDENTE": [
        re.compile(r"\bDECLARAR\s+IMPROCEDENTE\b|\bIMPROCEDENTE\s+la\s+(?:acci[oó]n|tutela)\b", re.IGNORECASE),
        re.compile(r"\bSIN\s+LUGAR\b|\bcarencia\s+actual\s+de\s+objeto\b|\bhecho\s+superado\b", re.IGNORECASE),
    ],
}


SECOND_INSTANCE_VERBS: dict[str, list[re.Pattern]] = {
    "CONFIRMA": [re.compile(r"\bCONFIRMAR(?:SE)?\b|\bCONFIRMA\b", re.IGNORECASE)],
    "REVOCA": [re.compile(r"\bREVOCAR(?:SE)?\b|\bREVOCA\b", re.IGNORECASE)],
    "MODIFICA": [re.compile(r"\bMODIFICAR(?:SE)?\b|\bMODIFICA\b", re.IGNORECASE)],
}


DATE_PATTERNS = [
    re.compile(r"\b(\d{1,2})\s+de\s+([a-zñáéíóú]+)\s+de\s+(\d{4})", re.IGNORECASE),
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})"),
    re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{4})"),
]

# Patrones específicos de fecha de fallo (alta confianza)
# "proferido el X", "mediante fallo del X", "sentencia de fecha X"
FALLO_DATE_ANCHORS = [
    re.compile(
        r"(?:profer[ií]d[oa]|pronunciad[oa]|dictad[oa]|emitid[oa])\s+"
        r"(?:el\s+d[ií]a\s+|el\s+)?"
        r"(\d{1,2}\s+de\s+[a-zñáéíóú]+(?:\s+de\s+)?\s*\d{4}|\d{1,2}[/\-]\d{1,2}[/\-]\d{4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:sentencia|fallo|auto|providencia)\s+(?:de\s+fecha\s+|del\s+|de\s+)"
        r"(\d{1,2}\s+de\s+[a-zñáéíóú]+(?:\s+de\s+)?\s*\d{4}|\d{1,2}[/\-]\d{1,2}[/\-]\d{4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"mediante\s+(?:fallo|sentencia|auto)\s+(?:del?\s+)"
        r"(\d{1,2}\s+de\s+[a-zñáéíóú]+(?:\s+de\s+)?\s*\d{4}|\d{1,2}[/\-]\d{1,2}[/\-]\d{4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"fecha\s+(?:de\s+)?(?:la\s+)?(?:sentencia|fallo|decisi[oó]n)\s*[:.\-]?\s*"
        r"(\d{1,2}\s+de\s+[a-zñáéíóú]+(?:\s+de\s+)?\s*\d{4}|\d{1,2}[/\-]\d{1,2}[/\-]\d{4})",
        re.IGNORECASE,
    ),
    # Fecha al cierre del documento: "Dada en X el D de M de YYYY" (típico auto/sentencia)
    re.compile(
        r"(?:Dad[oa]\s+(?:en\s+[A-Za-zñáéíóú]+(?:\s+[A-Za-zñáéíóú]+)*\s+)?el\s+)"
        r"(\d{1,2}\s+de\s+[a-zñáéíóú]+\s+de\s+\d{4})",
        re.IGNORECASE,
    ),
]

_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


@dataclass
class Decision:
    sentido: str = ""           # CONCEDE / NIEGA / IMPROCEDENTE / CONCEDE PARCIALMENTE
    fecha: str = ""             # DD/MM/YYYY
    segunda_instancia: str = "" # CONFIRMA / REVOCA / MODIFICA (si aplica)
    fecha_segunda: str = ""
    impugnacion: str = ""       # SI / NO
    quien_impugno: str = ""     # Accionante / Accionado
    confidence: float = 0.0
    source_snippet: str = ""


def _normalize_date(match: re.Match) -> str:
    """DD/MM/YYYY normalizado desde un match de DATE_PATTERNS."""
    g = match.groups()
    if len(g) != 3:
        return ""
    if g[1].isalpha():
        d = int(g[0]); mo = _MONTHS.get(g[1].lower(), 0); y = int(g[2])
        if mo == 0:
            return ""
        return f"{d:02d}/{mo:02d}/{y:04d}"
    d = int(g[0]); mo = int(g[1]); y = int(g[2])
    return f"{d:02d}/{mo:02d}/{y:04d}"


def _nearest_date(text: str, offset: int, window: int = 500) -> str:
    """Fecha más cercana a un offset (preferencia por fechas ancladas a 'proferido/fallo')."""
    # 1. Primero buscar anchors explícitos (alta confianza)
    anchored = _find_anchored_fallo_date(text, offset, window * 3)
    if anchored:
        return anchored
    # 2. Fallback: fecha más cercana por distancia
    start = max(0, offset - window)
    end = min(len(text), offset + window)
    region = text[start:end]
    best = ""
    best_dist = 10**9
    for pat in DATE_PATTERNS:
        for m in pat.finditer(region):
            date = _normalize_date(m)
            if not date:
                continue
            dist = abs((start + m.start()) - offset)
            if dist < best_dist:
                best_dist = dist
                best = date
    return best


def _find_anchored_fallo_date(text: str, offset: int, window: int = 3000) -> str:
    """Busca fechas con ancla explícita ('proferido el', 'fallo de fecha') en TODO el texto.

    Los anchors son de muy alta confianza: si aparecen en cualquier parte del
    documento, es casi seguro que refieren a la fecha del fallo. La distancia
    al offset de RESUELVE se usa solo para desempate.
    """
    best = ""
    best_score = 10**9
    for pat in FALLO_DATE_ANCHORS:
        for m in pat.finditer(text):
            raw = m.group(1)
            normalized = _parse_flex_date(raw)
            if not normalized:
                continue
            # Score: distancia al offset (menor = mejor)
            dist = abs(m.start() - offset)
            if dist < best_score:
                best_score = dist
                best = normalized
    return best


def _parse_flex_date(raw: str) -> str:
    """Parsea '6 de abril de 2026' o '07/04/2026' a DD/MM/YYYY."""
    raw = re.sub(r"\s+", " ", raw.strip())
    # Formato verbal
    m = re.match(r"(\d{1,2})\s+de\s+([a-zñáéíóú]+)(?:\s+de\s+)?\s*(\d{4})", raw, re.IGNORECASE)
    if m:
        d = int(m.group(1))
        mo = _MONTHS.get(m.group(2).lower(), 0)
        y = int(m.group(3))
        if mo:
            return f"{d:02d}/{mo:02d}/{y:04d}"
    # Numérico
    m = re.match(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", raw)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{d:02d}/{mo:02d}/{y:04d}"
    return ""


def extract_decision(text: str, zones: DocZones | None = None) -> Decision:
    """Extrae la decisión del juez del texto de una sentencia."""
    if not text:
        return Decision()
    dec = Decision()

    # 1. Sentido del fallo en zona "resuelve" o cercana
    resuelve_start = None
    if zones and zones.has("resuelve"):
        s, e = zones.zones["resuelve"]
        resuelve_start = s
    else:
        m = re.search(r"\bR\s*E\s*S\s*U\s*E\s*L\s*V\s*E\b", text, re.IGNORECASE)
        if m:
            resuelve_start = m.start()

    # Buscar verbo de decisión. Si hay RESUELVE, priorizar región después de él.
    # Si hay "PRIMERO:" o "PRIMERO.-" dentro de la zona RESUELVE, buscar después.
    search_region = text[resuelve_start:] if resuelve_start else text

    # Restringir a la parte tras "PRIMERO" (el primer numeral del fallo)
    primero_m = re.search(r"\bPRIMERO\b\s*[\.\-:]", search_region, re.IGNORECASE)
    if primero_m and primero_m.start() < 500:
        # PRIMERO aparece cerca del inicio de RESUELVE → usar como punto de corte
        search_region = search_region[primero_m.start():]

    # Buscar todos los verbos y tomar el primero en orden de aparición.
    # PARCIAL tiene prioridad solo si aparece ANTES que otros (caso raro).
    candidates: list[tuple[int, str]] = []
    for sentido, pats in DECISION_VERBS.items():
        for pat in pats:
            m = pat.search(search_region)
            if m:
                candidates.append((m.start(), sentido))
                break
    if candidates:
        candidates.sort()  # el primero que aparezca gana (es PRIMERO: en el fallo)
        offset_rel, sentido = candidates[0]
        # Si "CONCEDE PARCIALMENTE" aparece cerca (±200 chars) de CONCEDE, preferir PARCIAL
        for off, s in candidates:
            if s == "CONCEDE PARCIALMENTE" and abs(off - offset_rel) < 200:
                sentido = "CONCEDE PARCIALMENTE"
                offset_rel = off
                break
        dec.sentido = sentido
        dec.confidence = 0.85
        offset_abs = (resuelve_start or 0) + offset_rel
        dec.fecha = _nearest_date(text, offset_abs)
        dec.source_snippet = text[max(0, offset_abs - 80):offset_abs + 80]

    # 2. Segunda instancia
    for sentido, pats in SECOND_INSTANCE_VERBS.items():
        for pat in pats:
            m = pat.search(text)
            if m:
                dec.segunda_instancia = sentido
                dec.fecha_segunda = _nearest_date(text, m.start())
                break
        if dec.segunda_instancia:
            break

    # 3. Impugnación
    if re.search(r"\b(?:se\s+)?IMPUGN(?:A|ACI[ÓO]N)\b", text, re.IGNORECASE):
        dec.impugnacion = "SI"
        # quien: accionante o accionado
        m = re.search(r"impugn(?:a|ó|ación)\s+(?:el\s+|la\s+)?(accionante|accionado|tutelante|demandado|Secretar[íi]a|Gobernaci[óo]n)", text, re.IGNORECASE)
        if m:
            dec.quien_impugno = m.group(1).capitalize()
    elif dec.sentido:
        dec.impugnacion = "NO"

    return dec
