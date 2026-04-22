"""Zone classifier: identifica secciones de un documento jurídico colombiano.

Emula lo que un abogado (o un LLM) hace al leer un auto/sentencia: localiza
rápidamente "aquí están las partes", "aquí están los hechos", "aquí es lo
que decide el juez". Las zonas guían a los extractores posteriores para
buscar cada campo en el lugar correcto.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# Marcadores de zona. Cada uno define (regex de apertura, peso de confianza).
# Se procesan en orden; la primera aparición marca el inicio de esa zona.
ZONE_MARKERS: dict[str, list[re.Pattern]] = {
    "encabezado": [
        re.compile(r"\b(?:Juzgado|Tribunal|Corte)\b.*?\b(?:de|del)\b", re.IGNORECASE | re.DOTALL),
        re.compile(r"^.{0,200}Radicado\s+(?:No\.?\s*)?\d", re.IGNORECASE | re.DOTALL),
    ],
    "partes": [
        re.compile(r"(?:ACCIONANTE|DEMANDANTE|TUTELANTE)\s*[:.\-]", re.IGNORECASE),
        re.compile(r"(?:ACCIONAD[OA]S?|DEMANDAD[OA]S?|ACCIONAD[OA])\s*[:.\-]", re.IGNORECASE),
    ],
    "hechos": [
        re.compile(r"\b(?:HECHOS?|ANTECEDENTES?|SÍNTESIS\s+DE\s+LOS\s+HECHOS)\b\s*[:.\-]", re.IGNORECASE),
        re.compile(r"PRIMER[OA]?\s*[\.\-]", re.IGNORECASE),
    ],
    "pretensiones": [
        re.compile(r"\b(?:PRETENSIONES|SOLICITA|PIDE|PRETENDE)\b\s*[:.\-]?", re.IGNORECASE),
        re.compile(r"\b(?:solicito|pido)\b\s+al\s+(?:despacho|honorable)", re.IGNORECASE),
    ],
    "derechos_invocados": [
        re.compile(r"derechos?\s+(?:fundamentales?|constitucionales?)\s+(?:invocados?|alegados?|vulnerados?)", re.IGNORECASE),
        re.compile(r"(?:invocando|alegando)\s+(?:la\s+)?vulneraci[oó]n\s+de", re.IGNORECASE),
    ],
    "admite": [
        re.compile(r"\bADM[ÍI]TASE\b", re.IGNORECASE),
        re.compile(r"\bad?m[ií]tase\s+esta\s+acci[oó]n\b", re.IGNORECASE),
    ],
    "resuelve": [
        re.compile(r"\bR\s*E\s*S\s*U\s*E\s*L\s*V\s*E\b", re.IGNORECASE),
        re.compile(r"^\s*(?:PRIMERO|SEGUNDO)\s*[:.\-]", re.MULTILINE),
        re.compile(r"\bFALLA\b|\bFALLO\b", re.IGNORECASE),
    ],
    "concede_niega": [
        re.compile(r"\b(?:CONCEDE[SRN]?|NI[ÉE]GA[SE]?|IMPROCEDENTE|CONCEDE\s+PARCIAL)\b", re.IGNORECASE),
        re.compile(r"\b(?:TUTELAR|AMPARAR|DENEGAR|DENIEGA)\b", re.IGNORECASE),
    ],
    "impugnacion": [
        re.compile(r"\b(?:IMPUGNACI[ÓO]N|APELACI[ÓO]N)\b", re.IGNORECASE),
        re.compile(r"(?:segunda\s+instancia|ad\s+quem)", re.IGNORECASE),
    ],
    "desacato": [
        re.compile(r"\b(?:incidente\s+de\s+)?(?:DESACATO|DESACATA)\b", re.IGNORECASE),
        re.compile(r"Auto\s+(?:de\s+)?apertura.*?desacato", re.IGNORECASE | re.DOTALL),
    ],
    "notifica": [
        re.compile(r"\bNOTIF[ÍI]QUESE\b", re.IGNORECASE),
        re.compile(r"\bC[ÚU]MPLASE\b", re.IGNORECASE),
    ],
}


@dataclass
class DocZones:
    """Rangos [start, end) de cada zona detectada en el texto."""
    zones: dict[str, tuple[int, int]] = field(default_factory=dict)
    text_length: int = 0

    def has(self, zone: str) -> bool:
        return zone in self.zones

    def get_text(self, zone: str, source: str) -> str:
        if zone not in self.zones:
            return ""
        s, e = self.zones[zone]
        return source[s:e]

    def which_zone(self, offset: int) -> str | None:
        """Retorna la zona que contiene un offset dado."""
        for name, (s, e) in self.zones.items():
            if s <= offset < e:
                return name
        return None


def classify_zones(text: str) -> DocZones:
    """Identifica las zonas presentes en un documento jurídico.

    Implementación: busca cada marcador; si matchea, ese punto es el inicio
    de la zona. El final es el inicio de la siguiente zona (o fin de texto).
    """
    if not text:
        return DocZones()

    hits: list[tuple[int, str]] = []
    for zone_name, patterns in ZONE_MARKERS.items():
        for pat in patterns:
            m = pat.search(text)
            if m:
                hits.append((m.start(), zone_name))
                break  # un marcador por zona es suficiente

    hits.sort(key=lambda t: t[0])
    zones = {}
    for i, (start, name) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        # Si la zona ya existe (raro), quedarse con la primera.
        if name not in zones:
            zones[name] = (start, end)

    return DocZones(zones=zones, text_length=len(text))
