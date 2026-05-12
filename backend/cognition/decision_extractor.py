# LEGACY v8 — pipeline cognitivo sin uso desde v9; candidato a borrado en Fase 8 (ver backend/cognition/__init__.py).
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
        dec.quien_impugno = _detect_quien_impugno(text)
    elif dec.sentido:
        dec.impugnacion = "NO"

    return dec


# ─── v9.4.5: Extractores específicos para campos <50% cobertura ──────

# Entidades públicas que suelen ser ACCIONADO
ENTIDADES_PUBLICAS_PATTERN = re.compile(
    r"\b(?:Secretar[íi]a|Gobernaci[óo]n|Alcald[íi]a|Ministerio|"
    r"Departamento\s+de\s+Santander|Ente\s+Territorial|"
    r"Gobierno|Procuradur[íi]a|Defensor[íi]a|Instituto)\b",
    re.IGNORECASE,
)

# Patrón "X impugna/impugnó" capturando el sujeto (~50 chars antes)
IMPUGNADOR_PATTERN = re.compile(
    r"([^.\n]{5,120}?)\s+impugn(?:[oó]|a|aci[oó]n)\s+(?:el\s+fallo|la\s+(?:tutela|sentencia|decisi[oó]n))",
    re.IGNORECASE,
)


def _detect_quien_impugno(text: str) -> str:
    """v9.4.5: detecta ACCIONANTE/ACCIONADO/MINISTERIO_PUBLICO en texto.

    Busca patrón "X impugna el fallo" y clasifica X según contenga entidad
    pública (ACCIONADO) o nombre propio (ACCIONANTE).
    """
    head = text[:8000]  # los autos de impugnación citan al impugnador en cabeza
    for m in IMPUGNADOR_PATTERN.finditer(head):
        sujeto = m.group(1).strip()
        if ENTIDADES_PUBLICAS_PATTERN.search(sujeto):
            return "ACCIONADO"
        # Si el sujeto contiene nombre propio (mayúsculas iniciales o cédula)
        if re.search(r"\b[A-ZÁÉÍÓÚÑ]{2,}\s+[A-ZÁÉÍÓÚÑ]{2,}", sujeto) or "tutelante" in sujeto.lower() or "accionante" in sujeto.lower():
            return "ACCIONANTE"
    # Fallback: ministerio público / agente oficioso
    if re.search(r"\b(?:Personero|Defensor\s+del\s+Pueblo|Procurador|Ministerio\s+P[úu]blico)\b", head, re.IGNORECASE):
        return "MINISTERIO_PUBLICO"
    return ""


# Patrón FOREST radicado típico
FOREST_PATTERN = re.compile(r"\b(\d{6,8})\b")  # 6-8 dígitos


def extract_forest_impugnacion(text: str, filename: str = "") -> str:
    """v9.4.5 + audit 2026-05-03: extrae FOREST de docs de impugnación / 2da instancia.

    Audit empírico identificó marker DOMINANTE en corpus SED Santander:
    "Con número de radicado NNNNNNNNNNN" (11 dígitos) en email automático
    de "Dirección de Atención al Ciudadano Gobernación de Santander" que
    notifica recepción de auto de impugnación.

    Cobertura esperada: 7/7 (100%) en docs que tengan ese email.
    """
    if not text:
        return ""
    text_head = text[:8000]

    # Pattern dominante del corpus (audit 2026-05-03):
    # "...recibido y enviado a TUTELAS GOBERNACION/EDUCACION, para lo
    #  pertinente. Con número de radicado [11 DÍGITOS]"
    # FOREST típico: 11 dígitos empezando con año (20XX).
    # Endurecido para descartar prefijos rad_23 que también tienen 11+ dígitos.
    m_corpus = re.search(
        r"Con\s+n[uú]mero\s+de\s+radicado\s+(20\d{8,13})",
        text_head, re.IGNORECASE,
    )
    if m_corpus:
        return m_corpus.group(1)

    # Fallback v9.4.5: si el doc indica 2da instancia, buscar patrones genéricos
    fn_lower = filename.lower()
    is_2da = (
        "impugna" in fn_lower or "impugnacion" in fn_lower or
        "segunda" in fn_lower or "tribunal" in fn_lower or
        re.search(r"\b(?:fallo\s+de\s+)?segunda\s+instancia|tribunal\s+(?:superior|administrativo)",
                  text_head, re.IGNORECASE)
    )
    if not is_2da:
        return ""
    m = re.search(
        r"(?:radicado|radicaci[oó]n|FOREST|n[uú]mero\s+de\s+proceso)\s*[:.\-]?\s*(\d{6,12})",
        text_head, re.IGNORECASE,
    )
    if m:
        return m.group(1)
    return ""


# Patrones para responsable_desacato — v9.4.7 (auditoría exhaustiva muestras SED)
RESPONSABLE_DESACATO_PATTERNS = [
    # "APERTURAR ... contra el señor [NOMBRE], identificado con C.C."
    re.compile(
        r"APERTURAR[^.]{0,200}?contra\s+(?:el\s+(?:se[ñn]ora?|doctora?|dr\.?|dra\.?)\s+)?"
        r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\.\s]{8,80}?)"
        r",?\s*identificad[oa]",
        re.IGNORECASE,
    ),
    # "REQUERIR a [NOMBRE] para que..."
    re.compile(
        r"REQUERIR\s+a\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\.\s]{8,80}?)\s+"
        r"(?:para\s+que|en\s+su\s+calidad|en\s+calidad)",
        re.IGNORECASE,
    ),
    # v9.4.7: "DECLARAR que los señores X, en su calidad de Y" (auto sanción)
    re.compile(
        r"DECLARAR\s+que\s+(?:los?\s+(?:se[ñn]ores?|se[ñn]ora|doctora?)\s+)?"
        r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\.\s]{8,150}?)"
        r",?\s+en\s+(?:su\s+)?(?:calidad|condici[oó]n)\s+de",
        re.IGNORECASE,
    ),
    # v9.4.7: "INAPLICACION ... al señor X, en su calidad de" (auto inaplicación)
    re.compile(
        r"(?:al?\s+(?:se[ñn]ora?|doctora?))\s+"
        r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\.\s]{8,80}?)"
        r",?\s+en\s+(?:su\s+)?(?:calidad|condici[oó]n)\s+de",
        re.IGNORECASE,
    ),
    # v9.4.7: "INCIDENTANDO: NOMBRE/ENTIDAD" (header de auto)
    re.compile(
        r"INCIDENTAND[OA]\s*[:.\-]\s*"
        r"([A-ZÁÉÍÓÚÑa-záéíóúñ][A-ZÁÉÍÓÚÑa-záéíóúñ\.\s,–\-]{8,120}?)"
        r"(?:\s*\n|\s+ACCION|\s+RADICA|\s+CONSTANCIA|\.)",
        re.IGNORECASE,
    ),
    # "incidente de desacato contra [NOMBRES o ENTIDAD]" (auto apertura)
    re.compile(
        r"incidente\s+de\s+desacato\s+contra\s+"
        r"(?:el\s+(?:se[ñn]ora?|doctora?)\s+)?"
        r"([A-ZÁÉÍÓÚÑa-záéíóúñ][A-ZÁÉÍÓÚÑa-záéíóúñ\.\s,–\-]{10,150}?)"
        r"(?:,?\s+(?:identificad[oa]|en\s+(?:su|calidad)|en\s+raz[oó]n)|,?\s*\.)",
        re.IGNORECASE | re.DOTALL,
    ),
    # Patrón fallback antiguo
    re.compile(
        r"(?:funcionari[oa]\s+(?:incidentad[oa]|sancionad[oa]|requerid[oa]))\s*[:.\-]?\s+"
        r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{8,80})",
        re.IGNORECASE,
    ),
    # B.2 (2026-05-03): "REQUERIRÁ a la Dra. NAME - CARGO" (futuro)
    # — pre-incidente, AutoRequierePrevioApertura. Caso real 123.
    re.compile(
        r"(?:se\s+)?REQUERIR(?:Á|ÁS|ÁN|IÓ|IDO|IDA|SE)\s+a\s+"
        r"(?:la?\s+)?(?:Dra?\.?|Dr\.?|señora?|señor)?\s*"
        r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\.\s]{8,80}?)"
        r"\s*[\-–—]\s*(?:SECRETARIA?|GOBERNADOR|DIRECTOR|JEFE|COORDINADOR|FUNCIONARIO)",
        re.IGNORECASE,
    ),
    # B.2: "VINCULAR / VINCULA al señor NAME" (auto vinculación al incidente)
    re.compile(
        r"VINCULAR?\s+(?:al?\s+(?:señora?|doctora?|Dra?\.?|Dr\.?))?\s*"
        r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\.\s]{8,80}?)"
        r"(?:,\s*identificad|,?\s+en\s+(?:su|calidad)|\s*[\-–—]\s*(?:SECRETARIA?|GOBERNADOR|DIRECTOR))",
        re.IGNORECASE,
    ),
    # B.2: "ORDENAR a NAME, en su calidad de" (auto orden cumplimiento)
    re.compile(
        r"ORDENAR\s+a\s+(?:la?\s+)?(?:Dra?\.?|Dr\.?|señora?|señor)?\s*"
        r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\.\s]{8,80}?)"
        r"\s*(?:,\s*en\s+(?:su|calidad)|\s*[\-–—]\s*(?:SECRETARIA?|GOBERNADOR|DIRECTOR))",
        re.IGNORECASE,
    ),
    # B.2: "EXHORTAR a NAME, ..."
    re.compile(
        r"EXHORTAR\s+a\s+(?:la?\s+)?(?:Dra?\.?|Dr\.?|señora?|señor)?\s*"
        r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\.\s]{8,80}?)"
        r"\s*(?:,\s*en\s+(?:su|calidad)|\s*[\-–—]\s*(?:SECRETARIA?|GOBERNADOR|DIRECTOR)|\s+para\s+que)",
        re.IGNORECASE,
    ),
    # CORRECCIÓN audit 2026-05-03: en el corpus SED, responsable_desacato es el
    # abogado/persona DESIGNADA del equipo Apoyo Jurídico para gestionar la
    # respuesta al proceso. El marcador real es "PROYECTÓ: [NOMBRE]" en la
    # Carta de Respuesta SED (mayor cobertura: 5/16 con este pattern).
    re.compile(
        r"PROYECT[ÓO]\s*[:.\-]?\s*"
        r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\.\s]{8,80}?)"
        r"(?:\s*[\-–—]\s*(?:ABOGAD[OA]|CONTRATISTA|ESP|GRUPO|APOYO)|\s*\.|\s*\n|\s+APROB[ÓO])",
        re.IGNORECASE,
    ),
    # "Proyecto: NOMBRE. Abogado Esp-Contratista DAF" (variante sin tilde)
    # Requiere ≥2 palabras capitalizadas tras ":" para evitar matchear
    # "Proyecto de inversión alguna" (caso real ruidoso descubierto en audit).
    re.compile(
        r"(?:^|\n)\s*Proyect[oó]\s*[:.\-]\s*"
        r"([A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ\.]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ\.]+){1,5})"
        r"\s*(?:[\.,\n]|\s+(?:Abogad|Esp|Contratista|DAF|Director))",
        re.MULTILINE,
    ),
    # Fallback: "APROBÓ: NOMBRE" cuando PROYECTÓ no aparece
    re.compile(
        r"APROB[ÓO]\s*[:.\-]?\s*"
        r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\.\s]{8,80}?)"
        r"(?:\s*[\-–—]\s*(?:L[IÍ]DER|JEFE|COORDINADOR|DIRECTOR)|\s*\.|\s*\n)",
        re.IGNORECASE,
    ),
]

# Roles/frases genéricas que NO son nombres (filtros de salida)
RESPONSABLE_BLACKLIST = {
    "PARTE INCIDENTADA", "INCIDENTADO", "INCIDENTADA",
    "EL FUNCIONARIO", "EL DEPARTAMENTO", "EL SEÑOR",
    "QUIEN", "SECRETARI", "GOBERNADOR",
    # B.2 (2026-05-03): genéricos adicionales
    "LA ACCIONADA", "EL ACCIONADO", "LA ACCIONANTE", "EL ACCIONANTE",
    "LA TUTELANTE", "EL TUTELANTE", "LA DEMANDADA", "EL DEMANDADO",
    "LA AUTORIDAD", "EL AUTORIDAD", "LA ENTIDAD",
}

# Audit empírico 2026-05-03: palabras stop que indican que el match es una
# frase descriptiva, no un nombre propio. Si el resultado contiene CUALQUIERA
# de estas, descartar (caso real: "de inversión alguna radicado por el Municipio").
RESPONSABLE_STOP_WORDS = {
    "inversión", "inversion", "proceso", "municipio", "expediente",
    "certificado", "certificados", "disponibilidad", "presupuesto",
    "decreto", "ley", "constitución", "constitucion", "sentencia",
    "auto", "fallo", "tutela", "incidente", "desacato",
    "respectivos", "respectiva", "alguna", "ninguna", "presente",
    "anterior", "siguiente", "mediante", "conforme", "fundamental",
    "fundamentales", "presupuestal", "judicial", "judiciales",
}

# B.2 (2026-05-03): prefijos honoríficos a stripear del comienzo del nombre.
_RESPONSABLE_PREFIX_RE = re.compile(
    r"^(?:la?\s+|el\s+)?(?:dra?\.?|dr\.?|doctora?|señora?|señor)\s*\.?\s*",
    re.IGNORECASE,
)


def extract_responsable_desacato(text: str) -> str:
    """v9.4.6 + B.2: extrae nombre del funcionario público sancionado en incidente.

    Busca patrones reales SED Santander:
      - 'APERTURAR ... contra el señor X, identificado con C.C.'
      - 'REQUERIR a X para que en su calidad de Y'
      - 'REQUERIRÁ a la Dra. X - SECRETARIA' (futuro, B.2)
      - 'VINCULAR al señor X, identificado' (B.2)
      - 'incidente de desacato contra X' (entidad o nombre)
    """
    if not text:
        return ""
    head = text[:8000]
    for pat in RESPONSABLE_DESACATO_PATTERNS:
        m = pat.search(head)
        if m:
            name = re.sub(r"\s+", " ", m.group(1)).strip(" ,.;:")
            # B.2: strip prefijos honoríficos al comienzo
            name = _RESPONSABLE_PREFIX_RE.sub("", name).strip(" ,.;:")
            # Validaciones
            if len(name) < 8 or len(name) > 150:
                continue
            upper = name.upper().strip()
            # Filtrar genéricos exactos o casi exactos
            if upper in RESPONSABLE_BLACKLIST:
                continue
            if upper in ("LA PARTE INCIDENTADA", "EL INCIDENTADO", "LA INCIDENTADA",
                          "PARTE INCIDENTADA", "QUIEN", "EL FUNCIONARIO"):
                continue
            # Audit 2026-05-03: rechazar si contiene stop words descriptivas
            words_lower = name.lower().split()
            if any(w in RESPONSABLE_STOP_WORDS for w in words_lower):
                continue
            # Audit 2026-05-03: requerir al menos 2 palabras tipo nombre propio
            # (cada palabra inicia con mayúscula y tiene ≥3 chars).
            cap_words = [w for w in name.split()
                          if len(w) >= 3 and w[0].isupper()]
            if len(cap_words) < 2:
                continue
            return name
    return ""


# Patrones para decision_incidente — v9.4.6 (basados en autos reales SED)
# La sección RESUELVE PRIMERO suele tener un verbo imperativo + acción concreta.
DECISION_INCIDENTE_VERBOS = (
    "REQUERIR", "APERTURAR", "ADELANTAR", "SANCIONAR", "IMPONER",
    "DECLARAR", "ARCHIVAR", "COMPULSAR", "EXHORTAR", "REMITIR",
    "DECRETAR", "ORDENAR", "RECHAZAR", "NEGAR", "ABSTENERSE",
    "CERRAR", "CONFIRMAR", "REVOCAR", "MODIFICAR",
)
_VERBOS_RE = "|".join(DECISION_INCIDENTE_VERBOS)

DECISION_INCIDENTE_PATTERNS = [
    # v9.4.7: "RESUELVE PRIMERO: VERBO ..." multi-línea (autos reales tienen \n)
    re.compile(
        rf"RESUELVE\s*[:.]?\s*PRIMERO\s*[:.]?\s*"
        rf"(({_VERBOS_RE})\b[^.]{{10,400}}\.)",
        re.IGNORECASE | re.DOTALL,
    ),
    # PRIMERO: VERBO (multi-línea, con o sin RESUELVE)
    re.compile(
        rf"(?:^|\n)\s*PRIMERO\s*[:.]\s*"
        rf"(({_VERBOS_RE})\b[^.]{{10,400}}\.)",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    ),
    # "han incurrido en Desacato" → declaración explícita de desacato
    re.compile(
        r"((?:han|ha)\s+incurrid[oa]\s+en\s+(?:Desacato|incumplimiento)[^.]{0,300}\.)",
        re.IGNORECASE | re.DOTALL,
    ),
    # "Sanciona con N días de arresto"
    re.compile(
        r"(SANCIONA(?:R)?\s+[^.]{5,200}?\d+\s+d[íi]as?\s+de\s+arresto[^.]{0,100}\.)",
        re.IGNORECASE | re.DOTALL,
    ),
    # "Declara terminado / cumplido"
    re.compile(
        r"(DECLAR[AE]\s+(?:el\s+)?(?:cumplimiento|terminad[oa]|terminaci[oó]n)[^.]{0,200}\.)",
        re.IGNORECASE | re.DOTALL,
    ),
    # "Archiva por cumplimiento / hecho superado"
    re.compile(
        r"(ARCHIV[AE]R?\s+(?:el\s+(?:incidente|desacato))?\s*"
        r"(?:por\s+)?(?:cumplimiento|carencia\s+actual\s+de\s+objeto|hecho\s+superado)[^.]{0,100}\.)",
        re.IGNORECASE | re.DOTALL,
    ),
    # B.3 (2026-05-03): "REQUIERE PREVIO APERTURA FORMAL DE INCIDENTE" — auto pre-incidente
    re.compile(
        r"(REQUIE?RE?\s+PREVIO\s+APERTURA\s+(?:FORMAL\s+)?(?:DEL?\s+)?INCIDENTE\s+(?:DE\s+)?DESACATO[^.]{0,200})",
        re.IGNORECASE | re.DOTALL,
    ),
    # B.3: "VINCULA / VINCULAR ... al incidente" — auto vinculación
    re.compile(
        r"(VINCUL(?:AR|A|ANDO|ESE)\s+(?:al?\s+)?[^.]{5,250}?(?:al\s+(?:tr[áa]mite\s+)?incident\w*|al\s+contradictorio)[^.]{0,100}\.)",
        re.IGNORECASE | re.DOTALL,
    ),
    # B.3: "ADMITE / ADMITIR incidente" — apertura formal
    re.compile(
        r"(ADMIT(?:E|IR|ASE|IDO)\s+(?:el\s+)?(?:tr[áa]mite\s+)?(?:del?\s+)?incidente\s+(?:de\s+)?desacato[^.]{0,200}\.)",
        re.IGNORECASE | re.DOTALL,
    ),
    # B.3: "CONCEDE / NIEGA / CONFIRMA / REVOCA impugnación o sanción" — fallos de impugnación que reemplazan decisión incidente
    re.compile(
        r"((?:CONCEDE|NIEGA|CONFIRMA|REVOCA|MODIFICA)\s+(?:la\s+|el\s+|parcialmente\s+)?"
        r"(?:impugnaci[oó]n|sanci[oó]n|sentencia|incidente|desacato|fallo)[^.]{0,250}\.)",
        re.IGNORECASE | re.DOTALL,
    ),
    # B.3: "ORDENAR dar inicio al trámite de Cumplimiento"
    re.compile(
        r"(ORDENAR\s+dar\s+inicio\s+al\s+tr[áa]mite\s+(?:de\s+)?(?:cumplimiento|incident\w*|desacato)[^.]{0,250}\.)",
        re.IGNORECASE | re.DOTALL,
    ),
    # v9.4.7: "INAPLICACION DE LAS SANCIONES"
    re.compile(
        r"(INAPLICACI[OÓ]N\s+DE\s+LAS\s+SANCIONES[^.]{0,200}\.)",
        re.IGNORECASE | re.DOTALL,
    ),
    # v9.4.7: "ABSTENERSE de continuar"
    re.compile(
        r"(ABSTENERSE\s+(?:de\s+)?(?:continuar|sancionar|imponer)[^.]{0,150}\.)",
        re.IGNORECASE | re.DOTALL,
    ),
    # v9.4.7: "REVOCA la sanción"
    re.compile(
        r"(REVOC[AE]R?\s+(?:la\s+)?(?:sanci[oó]n|decisi[oó]n)[^.]{0,150}\.)",
        re.IGNORECASE | re.DOTALL,
    ),
    # v9.4.7: "CONFIRMA la sanción"
    re.compile(
        r"(CONFIRM[AE]R?\s+(?:la\s+)?(?:sanci[oó]n|decisi[oó]n|auto)[^.]{0,150}\.)",
        re.IGNORECASE | re.DOTALL,
    ),
]


def extract_decision_incidente(text: str) -> str:
    """v9.4.6: síntesis de la decisión sobre el incidente de desacato.

    Busca la sección RESUELVE/DECIDE y extrae el primer verbo imperativo
    (REQUERIR, APERTURAR, SANCIONAR, ARCHIVAR, etc.) con su complemento.
    """
    if not text:
        return ""
    # v9.4.7: aumentar ventana porque autos reales son más largos
    head = text[:12000]
    # Priorizar zona RESUELVE
    m = re.search(r"\b(?:RESUELVE|DECIDE|DECISI[ÓO]N)\b", head, re.IGNORECASE)
    region = head[m.start():] if m else head
    region = region[:6000]
    for pat in DECISION_INCIDENTE_PATTERNS:
        m2 = pat.search(region)
        if m2:
            decision = m2.group(1) if m2.groups() else m2.group(0)
            # Limpieza: colapsar whitespace + quitar saltos de tabla/header en el medio
            decision = re.sub(r"\s+", " ", decision).strip(" ,.;-:")
            if len(decision) >= 15:
                return decision[:400]
    return ""
