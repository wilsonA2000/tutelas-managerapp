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

        # Fallback final: buscar por filename (auto/admite/avoca) sin importar doc_type
        if self.field_name == "fecha_ingreso":
            _KW = ("auto", "admite", "admis", "avoca")
            for doc in documents:
                fname = (doc.get("filename", "") or "").lower()
                if any(kw in fname for kw in _KW):
                    text = doc.get("text", "") or doc.get("full_text", "")
                    if text:
                        fecha = _extract_fecha_from_text(text)
                        if fecha:
                            return ExtractionResult(
                                value=fecha, confidence=55,
                                source=doc.get("filename", ""),
                                method="regex_filename_fallback",
                                reasoning=f"Fecha de doc con nombre auto/admite: {doc.get('filename', '')}",
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

    @staticmethod
    def _trim_juzgado(juzgado: str) -> str:
        """v9.4: Recorta el nombre del juzgado al final del municipio Santander.

        Soluciona casos como:
          'JUZGADO PRIMERO PROMISCUO MUNICIPAL CIMITARRA SANTANDER ACTA DE REPARTO CIVIL No'
          → 'JUZGADO PRIMERO PROMISCUO MUNICIPAL CIMITARRA SANTANDER'
          'JUZGADO CUARTO PROMISCUO MUNICIPAL DE SAN GIL Veintinueve de febrero...'
          → 'JUZGADO CUARTO PROMISCUO MUNICIPAL DE SAN GIL'
        """
        import unicodedata
        try:
            from backend.cognition.legal_schema import MUNICIPIOS_SANTANDER
        except Exception:
            MUNICIPIOS_SANTANDER = set()

        def _norm(s: str) -> str:
            s2 = unicodedata.normalize("NFD", s.upper())
            return "".join(c for c in s2 if unicodedata.category(c) != "Mn")

        txt_norm = _norm(juzgado)

        # Buscar el primer municipio que aparezca (precedido de espacio)
        # y cortar justo después de él (+ " SANTANDER" si sigue).
        best_end = -1
        for muni in sorted(MUNICIPIOS_SANTANDER, key=len, reverse=True):
            idx = txt_norm.find(" " + muni)
            if idx >= 0:
                end = idx + 1 + len(muni)
                # Verificar que sea palabra completa (no prefijo de otra)
                next_char = txt_norm[end:end+1]
                if next_char in ("", " ", ",", ".", ";", ":"):
                    if best_end == -1 or end < best_end:
                        best_end = end

        if best_end > 0:
            result = juzgado[:best_end].rstrip(" ,.;")
            # Si sigue " SANTANDER" o ", Santander", incluirlo
            rest = juzgado[best_end:].lstrip(" ,")
            if rest[:9].upper().startswith("SANTANDER"):
                # Tomar la palabra "Santander" tal como está en original
                result = result + " " + rest.split()[0].rstrip(",.")
            return result

        # Fallback: cortar en frases típicas de basura post-juzgado
        cuts = re.split(
            r"\s+(?:Buen\s+d[ií]a|Se\s+remite|me\s+permito|no\s+obstante|"
            r"ante\s+la|dentro\s+de\s+la|mediante|Accionante|Accionado|Se[ñn]or|"
            r"ACTA|REPARTO|RADICACI|por\s+considerar|al\s+confirmar|"
            r"le\s+ha|ha\s+compartido|Cod|C[oó]d|NIT|Despacho|Auto|quien|"
            # Números escritos en español (cardinales que indican fecha)
            r"Veint[ie]\w*|Trein\w*|Cuaren\w*|Cincuen\w*|Sesen\w*|Seten\w*|"
            r"Ochen\w*|Noven\w*|Cien\w*|Once|Doce|Trece|Catorce|Quince|"
            r"Dieci\w+|Diecis\w+)",
            juzgado, flags=re.IGNORECASE, maxsplit=1,
        )
        return cuts[0].rstrip(" ,.;")

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
                    juzgado = self._trim_juzgado(juzgado)
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
                    juzgado = self._trim_juzgado(juzgado)
                    return ExtractionResult(
                        value=juzgado, confidence=70,
                        source=doc.get("filename", ""),
                        method="regex_fallback",
                        reasoning="Juzgado en texto plano",
                    )
        return None


# ---------------------------------------------------------------------------
# Juzgado Segunda Instancia Extractor (v9.4.3) — regex complementario
# al legal_schema. Si el documento ya menciona el tribunal explícitamente,
# preferimos esa fuente sobre la derivación.
# ---------------------------------------------------------------------------

class JuzgadoSegundaExtractor(FieldExtractor):
    field_name = "juzgado_2nd"
    prefer_regex = False

    _RE_TRIBUNAL = re.compile(
        r"(?i)("
        r"Tribunal\s+(?:Superior\s+del\s+Distrito\s+Judicial\s+de|Contencioso\s+Administrativo\s+de|Administrativo\s+de)\s+(?:Bucaramanga|San\s+Gil|Santander)"
        r"(?:\s*[\-,]\s*Sala\s+(?:Civil(?:[\s\-]Familia)?|Penal|Laboral|[ÚU]nica))?"
        r")"
    )
    # Captura "Juzgado X del Circuito de [Ciudad]" cuando se cita como 2da instancia
    _RE_CIRCUITO = re.compile(
        r"(?i)(juzgado\s+\w+\s+(?:promiscuo|civil|penal|laboral|administrativo|familia)"
        r"(?:\s+\w+){0,3}\s+del\s+circuito\s+de\s+\w+(?:\s+\w+)?)"
    )

    def extract_regex(self, documents: list[dict], emails: list = None) -> ExtractionResult | None:
        # Buscar primero en documentos típicos de 2da instancia (sentencia, fallo)
        priority_types = ("PDF_SENTENCIA", "PDF_AUTO_ADMISORIO", "DOCX_OTRO")
        candidates: list[tuple[int, str, str]] = []  # (priority, value, source)

        for doc in documents:
            doc_type = doc.get("doc_type", "")
            text = doc.get("text", "") or doc.get("full_text", "")
            if not text:
                continue
            head = text[:5000]

            # Regex 1: Tribunal explícito (alta confianza)
            m = self._RE_TRIBUNAL.search(head)
            if m:
                value = re.sub(r"\s+", " ", m.group(1)).strip(" ,.")
                candidates.append((90 if doc_type in priority_types else 70,
                                    value, doc.get("filename", "")))
                continue

            # Regex 2: Juzgado del Circuito
            m = self._RE_CIRCUITO.search(head)
            if m:
                value = re.sub(r"\s+", " ", m.group(1)).strip(" ,.")
                # Solo si es un doc de 2da o aparece en contexto "segunda instancia"
                if "segunda instancia" in head.lower() or "impugnac" in head.lower():
                    candidates.append((75 if doc_type in priority_types else 50,
                                        value, doc.get("filename", "")))

        if not candidates:
            return None

        # Tomar la candidata de mayor confianza
        candidates.sort(key=lambda c: -c[0])
        priority, value, source = candidates[0]
        # Aplicar trim defensivo
        value = JuzgadoExtractor._trim_juzgado(value)
        return ExtractionResult(
            value=value, confidence=priority,
            source=source, method="ir_regex",
            reasoning=f"Juzgado 2da instancia regex en {source}",
        )


# ---------------------------------------------------------------------------
# Ciudad Extractor (patron personero o header)
# ---------------------------------------------------------------------------

class CiudadExtractor(FieldExtractor):
    field_name = "ciudad"
    prefer_regex = False

    def extract_regex(self, documents: list[dict], emails: list = None) -> ExtractionResult | None:
        # v8.1: validar contra los 87 municipios oficiales de Santander.
        # Antes capturaba frases random como "PODER PÚBLICO", "EDUCACIÓN DE SANTANDER",
        # "la Tarjeta Profesional" porque la regex era demasiado laxa.
        from backend.agent.extractors.municipios_santander import (
            find_municipio_in_text, is_municipio_santander, MUNICIPIOS_SANTANDER,
        )

        # Estrategia 1: buscar municipio mencionado explícitamente en HEADER de sentencia
        # (donde aparece "JUZGADO X DE FLORIDABLANCA" o similar).
        for doc in documents:
            if doc.get("doc_type") not in ("PDF_SENTENCIA", "PDF_AUTO_ADMISORIO"):
                continue
            for z in doc.get("zones", []):
                if not isinstance(z, dict) or z.get("zone_type") != "HEADER":
                    continue
                muni = find_municipio_in_text(z.get("text", "")[:1000])
                if muni:
                    return ExtractionResult(
                        value=muni.title(), confidence=90,
                        source=doc.get("filename", ""),
                        method="ir_header_validated",
                        reasoning=f"Municipio Santander en HEADER de {doc.get('filename', '')}",
                    )

        # Estrategia 2: patrón PERSONERO + validación contra lista
        for doc in documents:
            text = doc.get("text", "") or doc.get("full_text", "")
            if not text:
                continue
            m = PERSONERO_MUNICIPIO.pattern.search(text[:5000])
            if m:
                ciudad = m.group(1).strip()
                ciudad = CITY_CLEANUP.sub("", ciudad).strip()
                ciudad = re.split(
                    r"\s+(?:en\s+|quien|para|por|como|a\s+trav|contra|accionante|demandante)",
                    ciudad, flags=re.IGNORECASE
                )[0].strip(" ,.-")
                if is_municipio_santander(ciudad):
                    return ExtractionResult(
                        value=ciudad.title(), confidence=85,
                        source=doc.get("filename", ""),
                        method="regex_personero_validated",
                        reasoning=f"Personero de {ciudad} en {doc.get('filename', '')}",
                    )

        # Estrategia 3: scan en cuerpo del primer doc buscando municipios mencionados
        for doc in documents[:3]:  # solo primeros 3 docs
            text = (doc.get("text", "") or doc.get("full_text", ""))[:5000]
            muni = find_municipio_in_text(text)
            if muni:
                return ExtractionResult(
                    value=muni.title(), confidence=70,
                    source=doc.get("filename", ""),
                    method="body_municipio_match",
                    reasoning=f"Municipio Santander mencionado en cuerpo: {muni}",
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
