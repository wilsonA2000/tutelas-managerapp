"""Extractores de campos mecanicos usando zonas IR.

Estos extractores trabajan sobre DocumentZone en vez de texto plano,
aprovechando la estructura detectada por fitz (fuentes, posiciones, zonas).
"""

import re
import unicodedata
from backend.agent.extractors.base import FieldExtractor, ExtractionResult
from backend.agent.regex_library import (
    ACCIONANTE_EXPLICIT, ACCIONANTE_DEMANDANTE, ACCIONANTE_PROMOVIDA,
    PERSONERO_MUNICIPIO, ABOGADO_FOOTER, CITY_CLEANUP,
)


# ---------------------------------------------------------------------------
# Fecha Extractor (generico, configurable por doc_type)
# ---------------------------------------------------------------------------

_MESES = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
    "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
    "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
}

_RE_FECHA_ESCRITA = re.compile(
    r"(\d{1,2})\s*(?:\(\w+\))?\s*(?:d[eí]as?\s+)?(?:del?\s+mes\s+de\s+)?"
    r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)"
    r"\s+(?:del?\s+)?(?:a[ñn]o\s+)?(?:dos\s+mil\s+veinti\w+|\(?(20\d{2})\)?)",
    re.IGNORECASE,
)
_RE_FECHA_NUM = re.compile(r"(\d{1,2})[/\-](\d{1,2})[/\-](20\d{2})")


def _extract_fecha_from_text(text: str) -> str | None:
    """Extraer fecha DD/MM/YYYY de texto."""
    m = _RE_FECHA_ESCRITA.search(text)
    if m:
        dia = m.group(1).zfill(2)
        mes = _MESES.get(m.group(2).lower(), "00")
        anio = m.group(3) if m.group(3) else "2026"
        return f"{dia}/{mes}/{anio}"
    m = _RE_FECHA_NUM.search(text)
    if m:
        return f"{m.group(1).zfill(2)}/{m.group(2).zfill(2)}/{m.group(3)}"
    return None


class FechaExtractor(FieldExtractor):
    """Extractor de fechas configurable por tipo de documento y zona."""

    def __init__(self, field_name: str, target_doc_types: list[str], target_zones: list[str] = None):
        self.field_name = field_name
        self.prefer_regex = True
        self._target_doc_types = target_doc_types
        self._target_zones = target_zones or ["DATES", "HEADER", "BODY"]

    def extract_regex(self, documents: list[dict], emails: list = None) -> ExtractionResult | None:
        # Buscar en zonas IR primero
        for doc in documents:
            doc_type = doc.get("doc_type", "")
            if doc_type not in self._target_doc_types:
                continue
            zones = doc.get("zones", [])
            for z in zones:
                if not isinstance(z, dict):
                    continue
                if z.get("zone_type") not in self._target_zones:
                    continue
                # Intentar metadata parseada primero
                meta = z.get("metadata", {})
                if meta.get("fecha_parsed"):
                    return ExtractionResult(
                        value=meta["fecha_parsed"], confidence=90,
                        source=doc.get("filename", ""),
                        method="ir_zone",
                        reasoning=f"Fecha de zona {z.get('zone_type')} en {doc.get('filename', '')}",
                    )
                # Fallback a regex sobre texto de la zona
                fecha = _extract_fecha_from_text(z.get("text", ""))
                if fecha:
                    return ExtractionResult(
                        value=fecha, confidence=80,
                        source=doc.get("filename", ""),
                        method="regex_zone",
                        reasoning=f"Fecha regex en zona {z.get('zone_type')}",
                    )

        # Fallback: buscar en texto plano de docs del tipo correcto
        for doc in documents:
            doc_type = doc.get("doc_type", "")
            if doc_type not in self._target_doc_types:
                continue
            text = doc.get("text", "") or doc.get("full_text", "")
            if text:
                fecha = _extract_fecha_from_text(text)
                if fecha:
                    return ExtractionResult(
                        value=fecha, confidence=65,
                        source=doc.get("filename", ""),
                        method="regex_fallback",
                        reasoning=f"Fecha regex en texto plano de {doc.get('filename', '')}",
                    )
        return None

    def validate(self, value: str, context: dict = None) -> tuple[bool, str]:
        m = re.match(r"(\d{2})/(\d{2})/(20\d{2})", value)
        if not m:
            return False, f"Formato invalido: {value}"
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1 <= d <= 31 and 1 <= mo <= 12 and 2020 <= y <= 2030):
            return False, f"Fecha fuera de rango: {value}"
        return True, "OK"


# ---------------------------------------------------------------------------
# Juzgado Extractor (zona HEADER, fuente grande)
# ---------------------------------------------------------------------------

class JuzgadoExtractor(FieldExtractor):
    field_name = "juzgado"
    prefer_regex = False  # IA puede complementar si regex no encuentra

    _RE_JUZGADO = re.compile(
        r"(?i)(juzgado\s+\w+\s+(?:\w+\s+){0,5}"
        r"(?:civil|penal|promiscuo|laboral|familia|ejecuci[oó]n|peque[ñn]as?\s+causas)"
        r"(?:\s+(?:y\s+)?(?:\w+\s+){0,4})?(?:de|del)\s+[\w\sáéíóúñÁÉÍÓÚÑ,]+)"
    )

    def extract_regex(self, documents: list[dict], emails: list = None) -> ExtractionResult | None:
        # Priorizar zona HEADER de auto admisorio
        for doc in documents:
            doc_type = doc.get("doc_type", "")
            if doc_type not in ("PDF_AUTO_ADMISORIO", "PDF_SENTENCIA"):
                continue
            for z in doc.get("zones", []):
                if not isinstance(z, dict):
                    continue
                if z.get("zone_type") != "HEADER":
                    continue
                m = self._RE_JUZGADO.search(z.get("text", ""))
                if m:
                    juzgado = m.group(1).strip()
                    juzgado = re.sub(r"\s+", " ", juzgado).strip(" ,.")
                    # Truncar en frases que ya no son parte del nombre del juzgado
                    juzgado = re.split(
                        r"\s+(?:le\s+ha|ha\s+compartido|Cod|C[oó]d|NIT|Despacho|Auto|RADICACI|quien)",
                        juzgado, flags=re.IGNORECASE
                    )[0].strip(" ,.")
                    return ExtractionResult(
                        value=juzgado, confidence=90,
                        source=doc.get("filename", ""),
                        method="ir_header",
                        reasoning=f"Juzgado en HEADER de {doc.get('filename', '')}",
                    )

        # Fallback texto plano
        for doc in documents:
            text = doc.get("text", "") or doc.get("full_text", "")
            if text:
                m = self._RE_JUZGADO.search(text[:3000])
                if m:
                    juzgado = re.sub(r"\s+", " ", m.group(1)).strip(" ,.")
                    juzgado = re.split(
                        r"\s+(?:le\s+ha|ha\s+compartido|Cod|C[oó]d|NIT|Despacho|Auto|RADICACI|quien)",
                        juzgado, flags=re.IGNORECASE
                    )[0].strip(" ,.")
                    return ExtractionResult(
                        value=juzgado, confidence=70,
                        source=doc.get("filename", ""),
                        method="regex_fallback",
                        reasoning="Juzgado en texto plano",
                    )
        return None


# ---------------------------------------------------------------------------
# Ciudad Extractor (patron personero o header)
# ---------------------------------------------------------------------------

class CiudadExtractor(FieldExtractor):
    field_name = "ciudad"
    prefer_regex = False

    def extract_regex(self, documents: list[dict], emails: list = None) -> ExtractionResult | None:
        # Buscar patron personero en cualquier documento
        for doc in documents:
            text = doc.get("text", "") or doc.get("full_text", "")
            if not text:
                continue
            m = PERSONERO_MUNICIPIO.pattern.search(text[:5000])
            if m:
                ciudad = m.group(1).strip()
                ciudad = CITY_CLEANUP.sub("", ciudad).strip()
                # Truncar en palabras que no son parte del nombre de la ciudad
                ciudad = re.split(
                    r"\s+(?:en\s+|quien|para|por|como|a\s+trav|contra|accionante|demandante)",
                    ciudad, flags=re.IGNORECASE
                )[0].strip(" ,.-")
                if len(ciudad) >= 3:
                    return ExtractionResult(
                        value=ciudad, confidence=85,
                        source=doc.get("filename", ""),
                        method="regex_personero",
                        reasoning=f"Ciudad de patron personero en {doc.get('filename', '')}",
                    )

        # Buscar en zona HEADER de sentencia
        for doc in documents:
            if doc.get("doc_type") not in ("PDF_SENTENCIA", "PDF_AUTO_ADMISORIO"):
                continue
            for z in doc.get("zones", []):
                if not isinstance(z, dict) or z.get("zone_type") != "HEADER":
                    continue
                # Patron "DE BUCARAMANGA", "DE FLORIDABLANCA"
                m = re.search(r"(?i)(?:DE|DEL)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ\s]{3,25}?)(?:\s*$|\s+C[oó]d)", z.get("text", ""))
                if m:
                    ciudad = m.group(1).strip()
                    if len(ciudad) >= 3:
                        return ExtractionResult(
                            value=ciudad, confidence=75,
                            source=doc.get("filename", ""),
                            method="ir_header",
                            reasoning=f"Ciudad en HEADER de {doc.get('filename', '')}",
                        )
        return None


# ---------------------------------------------------------------------------
# Enum Extractors (SI/NO por presencia de documentos)
# ---------------------------------------------------------------------------

class ImpugnacionExtractor(FieldExtractor):
    field_name = "impugnacion"
    prefer_regex = True

    def extract_regex(self, documents: list[dict], emails: list = None) -> ExtractionResult | None:
        for doc in documents:
            doc_type = doc.get("doc_type", "")
            if doc_type in ("PDF_IMPUGNACION", "DOCX_IMPUGNACION"):
                return ExtractionResult(
                    value="SI", confidence=90,
                    source=doc.get("filename", ""),
                    method="doc_presence",
                    reasoning=f"Doc tipo {doc_type} encontrado",
                )
            fn = doc.get("filename", "").lower()
            if "impugn" in fn or "concede impugnacion" in fn:
                return ExtractionResult(
                    value="SI", confidence=85,
                    source=doc.get("filename", ""),
                    method="filename",
                    reasoning="Palabra 'impugn' en nombre de archivo",
                )
        return ExtractionResult(
            value="NO", confidence=60,
            source="doc_analysis",
            method="absence",
            reasoning="No se encontro documento de impugnacion",
        )


class IncidenteExtractor(FieldExtractor):
    field_name = "incidente"
    prefer_regex = True

    def extract_regex(self, documents: list[dict], emails: list = None) -> ExtractionResult | None:
        for doc in documents:
            doc_type = doc.get("doc_type", "")
            if doc_type in ("PDF_INCIDENTE", "DOCX_DESACATO"):
                return ExtractionResult(
                    value="SI", confidence=90,
                    source=doc.get("filename", ""),
                    method="doc_presence",
                    reasoning=f"Doc tipo {doc_type} encontrado",
                )
            fn = doc.get("filename", "").lower()
            if "desacato" in fn or "incidente" in fn:
                return ExtractionResult(
                    value="SI", confidence=85,
                    source=doc.get("filename", ""),
                    method="filename",
                    reasoning="Palabra 'desacato/incidente' en nombre de archivo",
                )
        return ExtractionResult(
            value="NO", confidence=60,
            source="doc_analysis",
            method="absence",
            reasoning="No se encontro documento de incidente/desacato",
        )


# ---------------------------------------------------------------------------
# Sentido Fallo Extractor (busca en zona RESOLUTION)
# ---------------------------------------------------------------------------

_RE_CONCEDE = re.compile(
    r"(?i)(conceder|se\s+concede|amparar|se\s+ampara|tutelar|se\s+tutela"
    r"|concede\s+parcialmente|ampara\s+parcialmente)"
)
_RE_IMPROCEDENTE = re.compile(
    r"(?i)(declarar\s+improcedente|improcedente|rechazar\s+por\s+improcedente)"
)
_RE_NIEGA = re.compile(
    r"(?i)(negar|se\s+niega|no\s+(?:ha\s+)?lugar|desestimar)"
)


class SentidoFalloExtractor(FieldExtractor):
    """Extrae sentido del fallo de zona RESOLUTION de sentencias."""

    def __init__(self, field_name: str, target_doc_types: list[str]):
        self.field_name = field_name
        self.prefer_regex = False  # IA complementa
        self._target_doc_types = target_doc_types

    def extract_regex(self, documents: list[dict], emails: list = None) -> ExtractionResult | None:
        for doc in documents:
            if doc.get("doc_type") not in self._target_doc_types:
                continue
            # Priorizar zona RESOLUTION
            for z in doc.get("zones", []):
                if not isinstance(z, dict) or z.get("zone_type") != "RESOLUTION":
                    continue
                text = z.get("text", "")
                if _RE_CONCEDE.search(text):
                    if "parcial" in text.lower():
                        return ExtractionResult(
                            value="CONCEDE PARCIALMENTE", confidence=85,
                            source=doc.get("filename", ""),
                            method="ir_resolution",
                            reasoning="Concede parcialmente en zona RESUELVE",
                        )
                    return ExtractionResult(
                        value="CONCEDE", confidence=85,
                        source=doc.get("filename", ""),
                        method="ir_resolution",
                        reasoning="Concede/Ampara en zona RESUELVE",
                    )
                if _RE_IMPROCEDENTE.search(text):
                    return ExtractionResult(
                        value="IMPROCEDENTE", confidence=85,
                        source=doc.get("filename", ""),
                        method="ir_resolution",
                        reasoning="Improcedente en zona RESUELVE",
                    )
                if _RE_NIEGA.search(text):
                    return ExtractionResult(
                        value="NIEGA", confidence=85,
                        source=doc.get("filename", ""),
                        method="ir_resolution",
                        reasoning="Niega en zona RESUELVE",
                    )

        # Fallback: buscar en nombre del archivo
        for doc in documents:
            if doc.get("doc_type") not in self._target_doc_types:
                continue
            fn = doc.get("filename", "").lower()
            if "concede" in fn:
                return ExtractionResult(
                    value="CONCEDE", confidence=70,
                    source=doc.get("filename", ""),
                    method="filename",
                    reasoning="'concede' en nombre de archivo",
                )
            if "niega" in fn:
                return ExtractionResult(
                    value="NIEGA", confidence=70,
                    source=doc.get("filename", ""),
                    method="filename",
                    reasoning="'niega' en nombre de archivo",
                )
        return None

    def validate(self, value: str, context: dict = None) -> tuple[bool, str]:
        valid = {"CONCEDE", "NIEGA", "IMPROCEDENTE", "CONCEDE PARCIALMENTE"}
        v = value.upper().strip()
        if v in valid:
            return True, "OK"
        return False, f"Valor invalido: {value}. Validos: {valid}"


# ---------------------------------------------------------------------------
# Accionante Extractor (zonas PARTIES)
# ---------------------------------------------------------------------------

class AccionanteExtractor(FieldExtractor):
    field_name = "accionante"
    prefer_regex = False  # IA complementa para casos complejos

    def extract_regex(self, documents: list[dict], emails: list = None) -> ExtractionResult | None:
        # Priorizar zona PARTIES de auto admisorio / sentencia
        for doc in documents:
            if doc.get("doc_type") not in ("PDF_AUTO_ADMISORIO", "PDF_SENTENCIA"):
                continue
            for z in doc.get("zones", []):
                if not isinstance(z, dict) or z.get("zone_type") != "PARTIES":
                    continue
                text = z.get("text", "")
                # Patron explicito
                for pat in [ACCIONANTE_EXPLICIT.pattern, ACCIONANTE_DEMANDANTE.pattern, ACCIONANTE_PROMOVIDA.pattern]:
                    m = pat.search(text)
                    if m:
                        nombre = m.group(1).strip()
                        nombre = re.sub(r"\s+", " ", nombre).strip(" ,.-")
                        # Truncar en palabras clave que indican fin del nombre
                        nombre = re.split(
                            r"\s+(?:Accionad[oa]s?|Contra|Demandad[oa]|VS\.?|Vinculad[oa]s?|Vs|contra|en\s+calidad)\b",
                            nombre, flags=re.IGNORECASE
                        )[0].strip(" ,.-")
                        if len(nombre) >= 5:
                            return ExtractionResult(
                                value=nombre, confidence=85,
                                source=doc.get("filename", ""),
                                method="ir_parties",
                                reasoning=f"Accionante en zona PARTIES de {doc.get('filename', '')}",
                            )
        return None
