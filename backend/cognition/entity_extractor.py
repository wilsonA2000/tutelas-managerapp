"""Entity extractor con roles: accionante/accionado/vinculado/juez/abogado.

No se limita a encontrar nombres — infiere el rol legal de cada uno
basado en la zona del documento donde aparece y los verbos contextuales.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.cognition.zone_classifier import DocZones


# Marcadores de rol por contexto explícito
ROLE_PATTERNS: dict[str, re.Pattern] = {
    "ACCIONANTE": re.compile(
        r"(?:ACCIONANTE|TUTELANTE|DEMANDANTE|accionante|tutelante|demandante)\s*[:.\-]\s*([A-ZÁÉÍÓÚÑa-záéíóúñ\s]+?)(?:\s{2,}|\n|,|\.|\b(?:C\.?C|ced)|$)",
        re.MULTILINE,
    ),
    "ACCIONADO": re.compile(
        r"(?:ACCIONAD[OA]S?|DEMANDAD[OA]S?)\s*[:.\-]?\s*([A-ZÁÉÍÓÚ\s\-]+?)(?:\s{2,}|\n|VINCULAD|$)",
    ),
    "VINCULADO": re.compile(
        r"(?:VINCULAD[OA]S?)\s*[:.\-]?\s*([A-ZÁÉÍÓÚ\s\-]+?)(?:\s{2,}|\n|$)",
    ),
    "JUEZ": re.compile(
        r"\b(?:Juez|Juzgado\s+(?:del|de)?\s*(?:\w+\s+){0,4}(?:a\s+cargo\s+de)?)\s*[:.\-]?\s*([A-ZÁÉÍÓÚ][A-ZÁÉÍÓÚ\s]{3,})",
        re.IGNORECASE,
    ),
    "ABOGADO_PROYECTO": re.compile(
        r"(?:Proyect[oó]|Elabor[oó]|Redact[oó])\s*[:.\-]?\s*([A-ZÁÉÍÓÚ][A-ZÁÉÍÓÚa-záéíóúñ\s]{3,})",
    ),
}

# Prefijos/sufijos que deben recortarse del nombre capturado (ruido)
_NAME_STOP_WORDS = {
    "DE", "DEL", "LA", "LAS", "LOS", "EL", "Y", "A", "AL",
    "ACCIONANTE", "ACCIONADO", "ACCIONADA", "VINCULADO", "VINCULADA",
    "TUTELANTE", "DEMANDANTE", "DEMANDADO", "DEMANDADA",
    "IDENTIFICAD", "CEDULA", "CÉDULA", "CC", "C.C",
}

# Instituciones públicas conocidas (accionados recurrentes).
# Poblado desde catálogo scripts/catalog_variants.py sobre 394 casos reales.
KNOWN_INSTITUTIONS = {
    # Educación (dominante en corpus ~60%)
    "SECRETARIA DE EDUCACION",
    "SECRETARÍA DE EDUCACIÓN",
    "SECRETARIA DE EDUCACION DE SANTANDER",
    "SECRETARÍA DE EDUCACIÓN DE SANTANDER",
    "SECRETARIA DE EDUCACION DEPARTAMENTAL",
    "SECRETARIA DE EDUCACION MUNICIPAL",
    "SECRETARIA DE EDUCACION DE BUCARAMANGA",
    "MINISTERIO DE EDUCACION",
    "MINISTERIO DE EDUCACIÓN NACIONAL",
    "INSTITUCION EDUCATIVA",
    "COLEGIO",
    # Gobernación / alcaldías
    "GOBERNACION DE SANTANDER",
    "GOBERNACIÓN DE SANTANDER",
    "ALCALDIA MUNICIPAL",
    "ALCALDÍA MUNICIPAL",
    "ALCALDIA DE BUCARAMANGA",
    # Protección NNA
    "ICBF",
    "INSTITUTO COLOMBIANO DE BIENESTAR FAMILIAR",
    # Salud / EPS
    "NUEVA EPS",
    "SALUD TOTAL EPS",
    "SALUD TOTAL",
    "SANITAS EPS",
    "SANITAS",
    "COOMEVA EPS",
    "MEDIMAS",
    "MEDIMÁS",
    "CAFESALUD",
    "FAMISANAR",
    "FAMISANAR EPS",
    "COMPENSAR",
    "COMPENSAR EPS",
    # Otros frecuentes
    "FONDO NACIONAL DEL AHORRO",
    "FONDO DE PRESTACIONES SOCIALES DEL MAGISTERIO",
    "FOMAG",
    "COLPENSIONES",
    "MINISTERIO DE HACIENDA",
    "MINISTERIO DE SALUD",
    "SUPERINTENDENCIA DE SALUD",
    "SUPERSALUD",
    # Añadidos desde active learning (20260421)
    "SIMAT",
    "PROCURADURIA GENERAL DE SANTANDER",
    "PROCURADURÍA GENERAL DE SANTANDER",
    "PROCURADURIA GENERAL DE LA NACION",
    "PROCURADURÍA GENERAL DE LA NACIÓN",
    "ADRES",
    "ADMINISTRADORA DE LOS RECURSOS DEL SISTEMA GENERAL",
    "DEFENSORIA DEL PUEBLO",
    "DEFENSORÍA DEL PUEBLO",
    "PERSONERIA MUNICIPAL",
    "PERSONERÍA MUNICIPAL",
}


@dataclass
class Actor:
    role: str                       # ACCIONANTE / ACCIONADO / VINCULADO / JUEZ / ABOGADO / MENOR
    name: str                       # nombre completo o nombre institucional
    source_zone: str | None = None  # zona donde se detectó
    cc: str | None = None           # cédula si se puede vincular
    confidence: float = 0.5


@dataclass
class ActorSet:
    accionantes: list[Actor] = field(default_factory=list)
    accionados: list[Actor] = field(default_factory=list)
    vinculados: list[Actor] = field(default_factory=list)
    juez: Actor | None = None
    abogado_responsable: Actor | None = None
    menores: list[Actor] = field(default_factory=list)

    def all_names(self) -> list[str]:
        out = [a.name for a in self.accionantes + self.accionados + self.vinculados + self.menores]
        if self.juez:
            out.append(self.juez.name)
        if self.abogado_responsable:
            out.append(self.abogado_responsable.name)
        return out


_SPURIOUS_STARTERS = {
    "NO", "OBSTANTE", "MEDIANTE", "SIN", "EMBARGO", "POR", "LO", "TANTO",
    "ADEM[AÁ]S", "ASIMISMO", "EN", "EL", "LA", "LOS", "LAS",
}


def _clean_name(raw: str) -> str:
    raw = re.sub(r"\s+", " ", raw).strip(" ,.;:-\n\t")
    # Filtrar cabeceras/stopwords al inicio/final
    words = raw.split()
    while words and words[0].upper().strip(".") in _NAME_STOP_WORDS.union(_SPURIOUS_STARTERS):
        words = words[1:]
    while words and words[-1].upper().strip(".") in _NAME_STOP_WORDS:
        words = words[:-1]
    name = " ".join(words)
    # Evitar que capturemos texto demasiado corto o números
    if len(name) < 5 or re.search(r"\d", name):
        return ""
    # Rechazar si empieza con conectores típicos de frase
    if words and words[0].upper() in _SPURIOUS_STARTERS:
        return ""
    return name


_INST_PREFIXES = re.compile(r"^\s*(?:a\s+la\s+|al\s+|a\s+los?\s+|de\s+la\s+|del\s+|la\s+|el\s+|y\s+|e\s+|la\s+|el\s+)", re.IGNORECASE)


def _split_institutions(raw: str) -> list[str]:
    """Divide 'SED - MINEDU - GOB' en instituciones, limpiando ruido."""
    if not raw:
        return []
    # Normalizar saltos de línea y múltiples espacios
    raw = re.sub(r"\s+", " ", raw)
    parts = re.split(r"\s*[-–,]\s*|\s+Y\s+|\s+y\s+(?=[A-ZÁÉÍÓÚ])", raw)
    out = []
    for p in parts:
        p = _INST_PREFIXES.sub("", p).strip(" .,\t\n")
        # Rechazar fragmentos absurdos (OCR truncated: "dicción", "ismo", etc.)
        if len(p) < 4 or not any(c.isalpha() for c in p):
            continue
        # Rechazar si no tiene al menos 2 palabras o 6 caracteres + mayúscula
        if len(p) < 6 and " " not in p:
            continue
        out.append(p.upper())
    # Dedup preservando orden
    seen = set()
    dedup = []
    for x in out:
        if x not in seen:
            seen.add(x)
            dedup.append(x)
    return dedup


def _detect_minor(text: str, accionante_name: str) -> list[Actor]:
    """Busca patrones `agente oficios[oa] de su hij[oa] <NOMBRE>` y similares."""
    actors = []
    # Patrón unificado: nombre completo = 2+ palabras en mayúscula (con saltos de línea OK)
    NAMECAP = r"([A-ZÁÉÍÓÚ][A-ZÁÉÍÓÚ\.]+(?:\s+[A-ZÁÉÍÓÚ][A-ZÁÉÍÓÚ\.]+){1,6})"
    patterns = [
        re.compile(rf"agente\s+oficios[oa]\s+(?:de\s+)?su\s+hij[oa]\s+{NAMECAP}"),
        re.compile(rf"representante\s+legal\s+(?:del?\s+)?menor\s+{NAMECAP}"),
        re.compile(rf"su\s+hij[oa]\s+(?:menor\s+(?:de\s+edad\s+)?)?{NAMECAP}"),
        re.compile(rf"(?:del?\s+|de\s+la\s+)?menor(?:\s+de\s+edad)?\s+{NAMECAP}"),
    ]
    seen = set()
    for pat in patterns:
        for m in pat.finditer(text):
            name = _clean_name(m.group(1))
            if name and name not in seen and name != accionante_name:
                seen.add(name)
                actors.append(Actor(role="MENOR", name=name, source_zone="hechos", confidence=0.8))
    return actors


def extract_actors(text: str, zones: DocZones | None = None) -> ActorSet:
    """Extrae el conjunto de actores del documento con sus roles.

    Estrategia:
    1. Buscar marcadores explícitos (ACCIONANTE:, ACCIONADO:, etc.) en toda la zona.
    2. Si no hay, buscar patrones narrativos ("interpuesta por X contra Y").
    3. Detectar menores por vínculo ("agente oficiosa de su hija <NOMBRE>").
    4. Fallback: primer nombre propio en zona "admite" ≈ accionante.
    """
    result = ActorSet()
    if not text:
        return result

    # 1. Patrones narrativos para accionante
    accionante_patterns = [
        # "interpuesta por X contra Y" — forma clásica
        re.compile(r"interpuest[ao]?\s+por\s+([A-ZÁÉÍÓÚ][A-ZÁÉÍÓÚ\s]+?)(?:\s+(?:como|contra|en\s+nombre|,|$))"),
        # "ADMÍTASE ... interpuesta por X como agente oficios[ao]..."
        re.compile(r"ADM[ÍI]TASE\s+(?:esta\s+)?acci[oó]n\s+interpuest[ao]?\s+por\s+([A-ZÁÉÍÓÚ][A-ZÁÉÍÓÚ\s]+?)(?:\s+(?:como|en|contra|,))"),
        # "La accionante X identificada..."
        re.compile(r"(?:La\s+accionante|El\s+accionante|accionante)\s+(?:se[ñn]or[a]?\s+)?([A-ZÁÉÍÓÚ][A-ZÁÉÍÓÚa-záéíóúñ\s]+?)(?:,|\s+identificad|\s+act[uú]a|\s+interpone)"),
    ]
    for pat in accionante_patterns:
        m = pat.search(text)
        if m:
            acc_name = _clean_name(m.group(1))
            if acc_name and len(acc_name) > 5:
                result.accionantes.append(Actor(role="ACCIONANTE", name=acc_name, confidence=0.85, source_zone="admite"))
                break

    # 1b. Patrón "contra X - Y - Z" (accionados) separado
    m = re.search(
        r"(?:contra|dem[áa]ndase\s+a|dese\s+traslado\s+al?\s+(?:representante\s+legal\s+de\s+)?(?:la\s+|el\s+)?)"
        r"([A-ZÁÉÍÓÚ][A-ZÁÉÍÓÚ\s\-]+?)(?:\.|,\s+por|,\s+respecto|\s+y\s+|\s*$)",
        text, re.IGNORECASE,
    )
    if m:
        for inst in _split_institutions(m.group(1)):
            if len(inst) >= 4 and not any(a.name == inst for a in result.accionados):
                result.accionados.append(Actor(role="ACCIONADO", name=inst, confidence=0.7))

    # 1c. Vinculados: múltiples patrones
    # "vincúlese a X, Y, Z"
    # "TRASLADO al representante legal de la X y Y"
    # "vincular a X como tercero interesado"
    # "DE OFICIO VINCÚLESE a X"
    vinc_patterns = [
        re.compile(
            r"(?:vinc[úu]lese|vincular\s+de\s+oficio|vincular\s+como\s+tercero[s]?)"
            r"\s*(?:de\s+oficio\s+)?"
            r"(?:a\s+la?\s+|al?\s+)?"
            r"([^.]{10,600}?)"
            r"(?:\.|\bNotif[íi]quese|\bC[úu]mplase|\bAnexos|\bRequi[ée]rase)",
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            r"(?:DE\s+OFICIO\s+)?VIN[CÚU]ULESE\s+(?:a\s+)?([^.]{10,500})",
            re.IGNORECASE | re.DOTALL,
        ),
    ]
    for pat in vinc_patterns:
        m = pat.search(text)
        if m:
            raw = m.group(1)
            # Normalizar saltos de línea y expansión
            raw = re.sub(r"\s+", " ", raw)
            # Dividir por comas, "Y" mayúscula, guiones
            for inst in re.split(r"\s*[,\-–]\s*|\s+Y\s+|\s+y\s+(?=[A-ZÁÉÍÓÚ])", raw):
                cleaned = _INST_PREFIXES.sub("", inst).strip(" .,\t\n").upper()
                # Rechazar fragmentos pequeños o con verbos
                if len(cleaned) < 5:
                    continue
                if re.match(r"^(?:REMITASE|REMITA|REPRESENTANTE|LEGAL|PARA\s+QUE)", cleaned):
                    continue
                if not any(a.name == cleaned for a in result.vinculados):
                    result.vinculados.append(Actor(role="VINCULADO", name=cleaned, confidence=0.7))
            break

    # 2. Marcadores explícitos ACCIONANTE:/ACCIONADO:
    for role, pat in ROLE_PATTERNS.items():
        for m in pat.finditer(text):
            raw_name = m.group(1)
            if role == "ACCIONADO":
                for inst in _split_institutions(raw_name):
                    if not any(a.name == inst for a in result.accionados):
                        result.accionados.append(Actor(role=role, name=inst, confidence=0.8))
            elif role == "VINCULADO":
                for inst in _split_institutions(raw_name):
                    if not any(a.name == inst for a in result.vinculados):
                        result.vinculados.append(Actor(role=role, name=inst, confidence=0.75))
            elif role == "ACCIONANTE":
                name = _clean_name(raw_name)
                if name and not any(a.name == name for a in result.accionantes):
                    result.accionantes.append(Actor(role=role, name=name, confidence=0.9))
            elif role == "JUEZ":
                name = _clean_name(m.group(1))
                if name and not result.juez:
                    result.juez = Actor(role=role, name=name, confidence=0.7)
            elif role == "ABOGADO_PROYECTO":
                name = _clean_name(m.group(1))
                if name:
                    result.abogado_responsable = Actor(role="ABOGADO", name=name, confidence=0.9)

    # 3. Menores
    acc_name = result.accionantes[0].name if result.accionantes else ""
    for minor in _detect_minor(text, acc_name):
        if not any(m.name == minor.name for m in result.menores):
            result.menores.append(minor)

    # 4. Instituciones públicas reconocidas (fallback para accionado)
    if not result.accionados:
        text_up = text.upper()
        for inst in KNOWN_INSTITUTIONS:
            if inst in text_up:
                result.accionados.append(Actor(role="ACCIONADO", name=inst, confidence=0.6))
                break

    # 5. Fallback NER spaCy: si no se detectó accionante, intentar con spaCy
    if not result.accionantes:
        try:
            from backend.cognition.ner_spacy import extract_persons
            persons = extract_persons(text[:20000])  # primeros 20K chars
            # Filtrar: el primer PERSON en los primeros 2000 chars suele ser accionante
            for p in persons[:5]:
                if p.start > 2000:
                    break
                cleaned = _clean_name(p.text)
                if cleaned and len(cleaned) >= 8:  # mínimo 2 palabras
                    result.accionantes.append(
                        Actor(role="ACCIONANTE", name=cleaned,
                              confidence=0.65, source_zone="ner_spacy")
                    )
                    break
        except Exception:
            pass

    return result
