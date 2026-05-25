"""Detección y resolución de acumulaciones procesales en la ingesta (v9.2).

Una acumulación procesal ocurre cuando un juez junta varias tutelas (radicados y
accionantes distintos) en un solo trámite —típicamente para un incidente de
desacato conjunto—. Los documentos llegan por correo, a veces TODOS en un solo
email (un PDF de sentencia por accionante) y a veces en correos/threads separados.

Problema que resuelve (auditoría caso Hato 2025-00045/46/47, 2026-05-25):
  1. El extractor de radicados perdía los "desnudos" en enumeraciones:
     "RADICADOS 2025-00045, 2025-00046 y 00047" → capturaba solo 045 y 046.
  2. El detector de acumulaciones (`scripts/detect_acumulaciones.py`) era post-hoc,
     solo veía rad-21 con despacho de 12 dígitos (no el corto "2025-00047-00" de
     los encabezados de sentencia), y NUNCA creaba el caso hermano faltante.
  3. No había enrutamiento por-adjunto: la "SENTENCIA liliana patricia.pdf" caía
     en el caso de María Paula junto con las otras dos.

Este módulo expone funciones PURAS (sin DB, sin I/O) para cosechar radicados y
pares radicado↔accionante desde texto, más un detector de señal de acumulación.
La resolución con efectos (crear casos hermanos, enrutar docs, registrar el
vínculo RECTOR/ACUMULADO) vive en `backend/email/acumulacion_resolver.py`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# ── Radicado corto explícito: "AAAA-NNNNN" (3-5 dígitos, separador obligatorio) ──
# Tolera guion normal, en-dash, em-dash y slash. El (?!\d) evita comerse parte de
# un rad-23 continuo. El año debe ser 20xx.
_RX_RAD_EXPLICIT = re.compile(r"(20\d{2})\s*[-–—/]\s*0*(\d{3,5})(?!\d)")

# Secuencia "desnuda" en una enumeración: precedida por conector (, / y / e / and)
# Ej: "...2025-00046 y 00047" → captura "00047" para heredar el año del rad previo.
# El doble lookahead evita capturar el AÑO de un rad explícito siguiente
# (",  2025-00046" no debe rendir "2025") ni partir un rad-23 continuo.
_RX_BARE_SEQ = re.compile(
    r"(?:,|;|\sy\s|\se\s|\sand\s)\s*0*(\d{4,5})(?!\s*[-–—/]\s*\d)(?!\d)",
    re.IGNORECASE,
)

# Encabezado de sentencia/auto: "RADICADO: 2025-00047-00" + "ACCIONANTE: <NOMBRE>"
_RX_RADICADO_LABEL = re.compile(
    r"RADICADO\s*[:#]?\s*(?:N[°ºo.]*\s*)?([0-9\-–—/.\s]{6,40})", re.IGNORECASE
)
_RX_ACCIONANTE_LABEL = re.compile(
    r"ACCIONANTE\s*[:#]?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ.\s]{5,70}?)\s*"
    r"(?:\n|ACCIONAD|VINCULAD|C\.?C\.?|CC\.|CÉDULA|IDENTIFICAD|$)",
    re.IGNORECASE,
)
# "promovido por la accionante LILIANA PATRICIA CALA CALA" (cuerpo del correo)
_RX_ACCIONANTE_BODY = re.compile(
    r"promovid[oa]\s+por\s+(?:el|la)\s+accionante\s+"
    r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ.\s]{5,70}?)\s*(?:[.,;\n]|$)",
    re.IGNORECASE,
)

# Señal fuerte de acumulación (mismo léxico que scripts/detect_acumulaciones.py)
_RX_ACUMULA_VERBO = re.compile(
    r"\b(?:AC[UÚ]M[UÚ]L[EÉ]N?SE|"
    r"se\s+acumula[nr]?|se\s+ordena\s+(?:la\s+)?acumulaci[oó]n|"
    r"ACUMULAR\s+(?:la|las|el)\s+(?:acci[oó]n|tutela|expediente|incidente)|"
    r"ORDENAR\s+(?:LA\s+)?ACUMULACI[ÓO]N|"
    r"(?:expediente|radicado)[s]?\s+.{0,40}?acumulad[ao]s?|"
    r"tutela[s]?\s+acumulada[s]?|radicados?\s+acumulados?)\b",
    re.IGNORECASE,
)
_RX_ACUMULA_FILE = re.compile(
    r"(?i)(?:AcumulaTutela|Auto[\s_]?Acumula|Acumulaci[oó]n|Acumula\d+[\-_]\d+)"
)

_MAX_BARE_GAP = 30  # chars máximos entre el fin de un rad explícito y el conector


def _norm_seq(seq_raw: str) -> str | None:
    """Normaliza una secuencia cruda (3-6 díg) a 5 dígitos canónicos, o None."""
    if len(seq_raw) == 6 and seq_raw.startswith("0"):
        seq_raw = seq_raw.lstrip("0") or "0"
    if not (3 <= len(seq_raw) <= 5):
        return None
    return seq_raw.zfill(5)


def harvest_rads_corto(text: str | None) -> list[str]:
    """Cosecha TODOS los radicados cortos 'AAAA-NNNNN' de un texto.

    A diferencia de `rad_utils.canonical_rad_corto` (que devuelve UNO), captura
    enumeraciones completas, incluidos los radicados "desnudos" que heredan el
    año del radicado explícito anterior:

        "RADICADOS 2025-00045, 2025-00046 y 00047 ACUMULADOS"
            → ['2025-00045', '2025-00046', '2025-00047']

    Conservador: una secuencia desnuda solo se acepta si va precedida por un
    conector (',', ' y ', ' e ') y hay un radicado explícito que termina a lo
    sumo `_MAX_BARE_GAP` chars antes. Devuelve lista única, en orden de aparición.
    """
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    # 1) Radicados explícitos (con año) — registrar también su año y posición fin.
    explicit_spans: list[tuple[int, int, str]] = []  # (start, end, year)
    for m in _RX_RAD_EXPLICIT.finditer(text):
        year, seq = m.group(1), _norm_seq(m.group(2))
        explicit_spans.append((m.start(), m.end(), year))
        if not seq:
            continue
        rad = f"{year}-{seq}"
        if rad not in seen:
            seen.add(rad)
            out.append(rad)
    if not explicit_spans:
        return out
    # 2) Secuencias desnudas en enumeración → heredan el año del rad explícito previo.
    for m in _RX_BARE_SEQ.finditer(text):
        conn_start = m.start()
        # rad explícito cuyo fin esté inmediatamente antes del conector
        prev_year = None
        for s, e, year in explicit_spans:
            if e <= conn_start and (conn_start - e) <= _MAX_BARE_GAP:
                prev_year = year  # el más cercano por la izquierda
        if not prev_year:
            continue
        seq = _norm_seq(m.group(1))
        if not seq:
            continue
        rad = f"{prev_year}-{seq}"
        if rad not in seen:
            seen.add(rad)
            out.append(rad)
    return out


def _clean_name(raw: str) -> str:
    """Normaliza un nombre de accionante: colapsa espacios, quita saltos/cola."""
    name = re.sub(r"\s+", " ", (raw or "").strip(" .,:\n\r\t"))
    return name.upper()


def name_key(name: str | None) -> str:
    """Clave normalizada (sin tildes, sin dobles espacios) para comparar nombres."""
    if not name:
        return ""
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = re.sub(r"[^A-Za-z0-9 ]", " ", n)
    n = re.sub(r"\s+", " ", n).strip().upper()
    return n


def harvest_rad_accionante_pairs(text: str | None) -> list[tuple[str, str]]:
    """Empareja RADICADO↔ACCIONANTE desde encabezados de sentencia/auto.

    Aprovecha el patrón canónico de los fallos:
        RADICADO: 2025-00047-00
        ACCIONANTE: LILIANA PATRICIA CALA CALA

    Empareja cada etiqueta ACCIONANTE con la etiqueta RADICADO inmediatamente
    anterior (la más cercana por la izquierda). Devuelve [(rad_corto, nombre)].
    """
    if not text:
        return []
    rad_marks: list[tuple[int, str]] = []  # (pos, rad_corto)
    for m in _RX_RADICADO_LABEL.finditer(text):
        rads = harvest_rads_corto(m.group(1))
        if rads:
            rad_marks.append((m.start(), rads[0]))
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for m in _RX_ACCIONANTE_LABEL.finditer(text):
        name = _clean_name(m.group(1))
        if len(name) < 6:
            continue
        # rad más cercano por la izquierda
        rad = None
        for pos, r in rad_marks:
            if pos <= m.start():
                rad = r
        if not rad:
            continue
        key = (rad, name_key(name))
        if key in seen:
            continue
        seen.add(key)
        pairs.append((rad, name))
    return pairs


def harvest_accionantes(text: str | None) -> list[str]:
    """Nombres de accionante hallados (encabezado + cuerpo 'promovido por...')."""
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for rx in (_RX_ACCIONANTE_LABEL, _RX_ACCIONANTE_BODY):
        for m in rx.finditer(text):
            name = _clean_name(m.group(1))
            k = name_key(name)
            if len(name) >= 6 and k not in seen:
                seen.add(k)
                out.append(name)
    return out


def has_acumulacion_signal(text: str | None, filename: str | None = None) -> bool:
    """True si hay señal léxica fuerte de acumulación en texto o filename."""
    if filename and _RX_ACUMULA_FILE.search(filename):
        return True
    if text and _RX_ACUMULA_VERBO.search(text):
        return True
    return False


def _is_real_seq(rad_corto: str) -> bool:
    """Descarta secuencias claramente inválidas como 'AAAA-00000'."""
    m = re.match(r"20\d{2}-(\d{5})$", rad_corto or "")
    return bool(m) and int(m.group(1)) > 0


@dataclass
class AcumulacionEvidence:
    """Resultado de analizar los docs/correos de un caso buscando acumulación."""
    signal: bool = False                       # ¿hay verbo/filename de acumulación?
    rads: list[str] = field(default_factory=list)         # todos los rads vistos (ruido incl.)
    enum_rads: list[str] = field(default_factory=list)    # rads enumerados en docs CON señal
    pairs: dict[str, str] = field(default_factory=dict)   # rad_corto -> accionante (header, 1º gana)
    evidence_doc_ids: list[int] = field(default_factory=list)

    def members(self) -> list[str]:
        """Conjunto AUTORITATIVO de radicados de la acumulación.

        Estrategia conservadora (evita arrastrar docs ajenos o ruido de un bucket
        sucio, lección del caso Hato donde el bucket tenía un OFICIO de otra tutela
        y radicados malformados):

          Tier 1 — si hay enumeración en docs CON señal de acumulación, esos son
                   los miembros (la enumeración es una declaración del juzgado).
          Tier 2 — si no hay enumeración pero hay ≥2 accionantes distintos con
                   emparejamiento de encabezado, esos radicados son los miembros.

        Siempre filtra secuencias inválidas (AAAA-00000).
        """
        enum = [r for r in self.enum_rads if _is_real_seq(r)]
        if len(enum) >= 2:
            return enum
        paired = [r for r in self.pairs if _is_real_seq(r)]
        distinct_names = {name_key(self.pairs[r]) for r in paired}
        if len(paired) >= 2 and len(distinct_names) >= 2:
            return paired
        return []

    @property
    def is_acumulacion(self) -> bool:
        return len(self.members()) >= 2


def analyze_docs(docs: list[dict]) -> AcumulacionEvidence:
    """Analiza una lista de docs [{id, text, filename}] buscando acumulación.

    Función pura: no toca DB. Une la evidencia de todos los docs del caso.
    El conjunto de miembros se ancla a la enumeración de los docs CON señal de
    acumulación (su TEXTO, no el filename — los nombres de archivo vienen
    truncados y producen radicados espurios tipo 'AAAA-00000').
    """
    ev = AcumulacionEvidence()
    rad_order: list[str] = []
    enum_seen: set[str] = set()
    for d in docs:
        text = d.get("text") or ""
        filename = d.get("filename") or ""
        text_signal = has_acumulacion_signal(text, None)
        any_signal = has_acumulacion_signal(text, filename)
        rads = harvest_rads_corto(text + " " + filename)
        pairs = harvest_rad_accionante_pairs(text)
        if any_signal:
            ev.signal = True
        # Enumeración autoritativa: rads del TEXTO de un doc con señal léxica.
        if text_signal:
            for r in harvest_rads_corto(text):
                if r not in enum_seen:
                    enum_seen.add(r)
                    ev.enum_rads.append(r)
        if (any_signal or pairs) and d.get("id") is not None:
            if d["id"] not in ev.evidence_doc_ids:
                ev.evidence_doc_ids.append(d["id"])
        for r in rads:
            if r not in rad_order:
                rad_order.append(r)
        for rad, name in pairs:
            ev.pairs.setdefault(rad, name)  # primer doc (encabezado) gana
    ev.rads = rad_order
    return ev
