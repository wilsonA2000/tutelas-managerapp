"""Etapa 2 — Extracción puramente determinística por regex.

Reusa `backend/agent/regex_library.py` (21 patterns con self-tests). NO usa
IA, NO clasifica documentos con LLM. Recorre los textos en un orden
priorizado por confianza:

  1. Documentos cortos (auto admisorio, sentencia) — más densos en datos.
  2. Email markdown (header) — radicado y FOREST oficiales.
  3. Documento más largo — contexto.

Para cada campo del Excel, define qué pattern aplicar y en qué doc buscar.
Una vez encontrado, NO sobrescribe (`fields.set` lo enforce-a).

Es la única etapa que escribe la mayoría de campos. Si esta etapa no
encuentra un campo, las siguientes (catalog/excel/llm) son las únicas que
pueden llenarlo.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from backend.v9.types import ExtractedFields, FieldSource
from backend.v9.doc_io import DocText

logger = logging.getLogger("tutelas.v9.regex_pass")


# ============================================================
# CLASIFICACIÓN LIGERA DE DOCS POR KEYWORDS (sin IA)
# ============================================================

_KW_AUTO_ADMISORIO = re.compile(r"(?i)(auto\s*avoca|auto\s*admite|admite\s*tutela|avoca\s*conocimiento)")
_KW_SENTENCIA = re.compile(r"(?i)(sentencia|fallo\s+de\s+tutela|por\s+tales\s+razones|resuelve\s*[:\.])")
_KW_IMPUGNACION = re.compile(r"(?i)(impugnaci[oó]n|impugna\s+(la\s+)?sentencia|recurso\s+de\s+impugnaci[oó]n)")
_KW_INCIDENTE = re.compile(r"(?i)(incidente\s+de\s+desacato|abrir\s+incidente|aper(t|c)ura.*incidente)")
_KW_EMAIL = re.compile(r"(?i)(message-id|from:.*@.*gov\.co|gmail|de:\s+tutelas)")


def _doctype(d: DocText) -> str:
    """Clasifica documento por filename primero, luego por keywords de texto.

    Filename gana porque suele venir del operador y es más fiable que el
    texto (que puede mencionar palabras como 'sentencia' aunque el doc sea
    un incidente que se refiere a una sentencia previa).
    """
    fn = d.filename.lower()
    text = d.text[:3000]

    # ----- Prioridad 1: filename con señal fuerte -----
    if "incidente" in fn or "desacato" in fn:
        return "INCIDENTE"
    if "auto" in fn and ("admis" in fn or "avoca" in fn):
        return "AUTO_ADMISORIO"
    if "sentencia" in fn or ("fallo" in fn and "tutela" not in fn):
        return "SENTENCIA"
    if "impugna" in fn:
        return "IMPUGNACION"
    if "email" in fn or "gmail" in fn:
        return "EMAIL"
    if "respuesta" in fn or "contesta" in fn:
        return "RESPUESTA"

    # ----- Prioridad 2: texto con frases específicas (más específico primero) -----
    if re.search(r"(?i)\bincidente\s+de\s+desacato\b|\babrir\s+incidente\b|\baper(?:t|c)ura\s+(?:de\s+)?incidente\b", text):
        return "INCIDENTE"
    if _KW_AUTO_ADMISORIO.search(text):
        return "AUTO_ADMISORIO"
    if _KW_IMPUGNACION.search(text):
        return "IMPUGNACION"
    if _KW_SENTENCIA.search(text):
        return "SENTENCIA"
    if _KW_EMAIL.search(text):
        return "EMAIL"

    return "OTRO"


# ============================================================
# EXTRACTORES POR CAMPO (regex puros)
# ============================================================

def _first_match(pattern, text: str, group: int = 1) -> Optional[str]:
    if not text:
        return None
    m = pattern.search(text)
    return m.group(group).strip() if m else None


# Código Único del Proceso Judicial (Acuerdo 201/1997 + 1412/2002):
#   [DANE 5][Corp 2][Esp 2][Disp 3][Año 4][Sec 5][Rec 2] = 23 dígitos
#   índices 0-4    5-6    7-8    9-11   12-15  16-20  21-22
# Santander → DANE arranca con 68.
_RAD23_PREFIX = re.compile(r"68\d")
_RAD23_WINDOW_CHARS = 50  # 23 dígitos + hasta 27 chars de separadores/saltos


# Caracteres permitidos entre dígitos de un rad23 real:
#   espacios, tabs, newlines, guiones (ASCII y unicode), puntos, comas, slashes.
#   Incluye whitespace unicode comunes en docs jurídicos:
#     U+00A0 (NBSP, no-breaking space) — frecuente en subjects de email
#     U+2009 (thin space), U+202F (narrow no-break space)
# Si entre los dígitos hay LETRAS o cualquier otro símbolo, NO es un rad real
# (puede ser composición espuria de IDs, hashes, FOREST, etc.).
_RAD23_VALID_SEPARATORS = set(" \t\n\r-./,–—\xa0  ")


def _extract_radicado_23(text: str) -> Optional[str]:
    """Extrae el rad23 con estrategia "sliding window + estructura CUP".

    Encuentra TODOS los candidatos de 23 dígitos válidos en el texto y
    devuelve el MÁS FRECUENTE (en caso de empate, el primero del header).
    Esto evita falsos positivos en docs que mencionan rad de otras tutelas.

    Validaciones:
      - 23 dígitos exactos, comienza con '68' (Santander)
      - Año (chars 12-15) entre 2010-2030
      - Secuencia (chars 16-20) no totalmente cero
      - Recurso (chars 21-22) ≤ 10 (típicamente 00, 01, raramente 02-03)
      - Entre el dígito 1 y el dígito 23 NO puede haber letras u otros
        símbolos no-separadores (eso indica composición espuria).
    """
    if not text:
        return None
    from collections import Counter
    candidates: list[str] = []
    seen_at_pos: list[tuple[int, str]] = []  # (pos, rad) para desempate

    for m in _RAD23_PREFIX.finditer(text):
        start = m.start()
        window = text[start:start + _RAD23_WINDOW_CHARS]

        # Recorrer la ventana char por char acumulando dígitos.
        # Si encuentro un char que NO sea dígito ni separador válido → abortar.
        digits_buf = []
        valid = True
        for ch in window:
            if ch.isdigit():
                digits_buf.append(ch)
                if len(digits_buf) == 23:
                    break
            elif ch in _RAD23_VALID_SEPARATORS:
                continue
            else:
                # Letra u otro símbolo entre dígitos → composición espuria
                valid = False
                break
        if not valid or len(digits_buf) < 23:
            continue

        candidate = "".join(digits_buf)
        if not candidate.startswith("68"):
            continue
        year_part = candidate[12:16]
        if not year_part.startswith("20"):
            continue
        try:
            year = int(year_part)
        except ValueError:
            continue
        if not (2010 <= year <= 2030):
            continue
        if candidate[16:21] == "00000":
            continue
        # Recurso (chars 21-22): típicamente 00 (1ra) o 01 (impugnación).
        # Valores >10 son sospechosos (probable composición espuria).
        try:
            recurso = int(candidate[21:23])
            if recurso > 10:
                continue
        except ValueError:
            continue

        candidates.append(candidate)
        seen_at_pos.append((start, candidate))

    if not candidates:
        return None

    # Tomar el más frecuente. Si empate, el primero por posición (el del header).
    counts = Counter(candidates)
    top_count = max(counts.values())
    top_candidates = {c for c, n in counts.items() if n == top_count}
    for _pos, rad in seen_at_pos:
        if rad in top_candidates:
            return rad
    return candidates[0]


# FOREST blacklist: el FOREST de la GOBERNACIÓN como ENTIDAD (no del caso).
# Aparece en el header de TODOS los DOCX de respuesta: "[HEADER FOREST] 3634740 ..."
# Más otros números genéricos que NO son radicados de caso.
_FOREST_ENTITY_BLACKLIST = {"3634740", "890201235", "423545"}

# Patrón canónico de tutelas@santander.gov.co — está en TODOS los emails que
# asignan un FOREST nuevo (admisión, impugnación, contestación, requerimiento).
# Forma: "...para lo pertinente. Con número de radicado 20260069713. Cordialmente,
#         Dirección de Atención al Ciudadano"
_FOREST_CANONICO = re.compile(
    r"(?i)(?:su\s+correo\s+fue\s+recibido,?\s+radicado\s+y\s+enviado[^\d]{0,120}?"
    r"|con\s+n[úu]mero\s+de\s+radicado(?:\s+es)?)\s*[:\.]?\s*(\d{8,13})"
)
# El número de radicado es X (variante de tutelas@santander)
_FOREST_ES = re.compile(r"(?i)el\s+n[úu]mero\s+de\s+radicado\s+es\s*[:\.]?\s*(\d{7,13})")
# RADICACIÓN # : X — marca de agua en el header de los DOCX de respuesta
_FOREST_DOCX_HEADER = re.compile(r"(?i)RADICACI[ÓO]N\s*#?\s*[:\.]?\s*(\d{8,13})")
# Keyword FOREST/Forest seguido de número
_FOREST_KEYWORD = re.compile(r"(?i)(?:FOREST|forest)\s*(?:N[°o]\.?\s*)?:?\s*(\d{7,13})")


def _extract_forest(text: str) -> Optional[str]:
    """Extrae el FOREST (radicado interno de la Gobernación, asignado por
    tutelas@santander.gov.co). 7-13 dígitos, NUNCA con guiones.

    Prioridad de patrones:
      1. Mensaje canónico "Con número de radicado XXXXX" (firma Dir. Atención Ciudadano)
      2. "El número de radicado es XXXXX"
      3. Header DOCX de respuesta "RADICACIÓN # : XXXXX"
      4. Keyword "FOREST: XXXXX" / "Forest No. XXXXX"

    Excluye el FOREST de la Gobernación como entidad (3634740) y otros genéricos.
    """
    if not text:
        return None
    try:
        from backend.agent.forest_extractor import FOREST_BLACKLIST as _EXTRA_BLACKLIST
    except ImportError:
        _EXTRA_BLACKLIST = set()
    blacklist = _FOREST_ENTITY_BLACKLIST | _EXTRA_BLACKLIST

    for pat in (_FOREST_CANONICO, _FOREST_ES, _FOREST_DOCX_HEADER, _FOREST_KEYWORD):
        m = pat.search(text)
        if m:
            v = m.group(1)
            if 7 <= len(v) <= 13 and v not in blacklist:
                return v
    return None


_NAME_STOPWORDS = {
    # Conectivos / preposiciones / artículos
    "PARA", "QUE", "EN", "EL", "LA", "LOS", "LAS", "DE", "DEL", "POR", "CON",
    "SU", "SUS", "UN", "UNA", "Y", "O", "AL", "ANTE", "BAJO", "CABE", "DESDE",
    # Frases que aparecen en demandas ("DEMANDANTE PARA QUE EN EL TÉRMINO DE")
    "TÉRMINO", "TERMINO", "DÍAS", "DIAS", "HORAS", "PROCEDA", "AMPARE",
    "TUTELE", "ORDENE", "DISPONGA", "CONCEDA", "PRESENTE", "PETICIÓN",
    "PETICION", "ACCION", "ACCIÓN", "DERECHO", "DERECHOS",
    # Roles/cargos que no son nombres del accionante
    "ABOGADO", "ABOGADA", "DOCTOR", "DOCTORA", "SEÑOR", "SEÑORA",
    "MAGISTRADO", "JUEZ", "PERSONERO", "PERSONERA", "DEFENSOR",
    "FISCAL", "AGENTE", "REPRESENTANTE", "OFICIOSO", "OFICIOSA",
}


def _looks_like_person_name(s: str) -> bool:
    """Heurística: ¿pinta un string como nombre propio de persona?

    Reglas:
      - 2 a 5 palabras (nombre + 1-3 apellidos típico colombiano)
      - Ninguna de las primeras 3 palabras es stopword
      - Mayoría de palabras tienen pinta de nombre (>=3 letras, no todas mayus en
        medio de palabra, etc.)
    """
    words = s.split()
    if not (2 <= len(words) <= 5):
        return False
    head = [w.upper() for w in words[:3]]
    if any(w in _NAME_STOPWORDS for w in head):
        return False
    # Cada palabra debería tener al menos 2 letras y empezar con letra
    if not all(len(w) >= 2 and w[0].isalpha() for w in words):
        return False
    return True


def _extract_accionante(text: str) -> Optional[str]:
    from backend.agent.regex_library import (
        ACCIONANTE_EXPLICIT, ACCIONANTE_DEMANDANTE, ACCIONANTE_PROMOVIDA,
        LAWYER_CLEANUP,
    )
    for pat in (ACCIONANTE_EXPLICIT, ACCIONANTE_DEMANDANTE, ACCIONANTE_PROMOVIDA):
        m = pat.pattern.search(text)
        if m:
            name = m.group(1)
            # Cortar en newline (los regex aceptan \s que incluye \n y se sobrepasan)
            name = name.split("\n")[0].strip()
            name = LAWYER_CLEANUP.sub("", name)
            # Cortar antes de palabras-frontera comunes
            name = re.split(r"(?i)\b(?:DEMANDADO|ACCIONADO|VINCULADO|CONTRA|JUZGADO|GOBERNACION|PARA\s+QUE|SOLICIT|PRESENT)\b", name)[0].strip()
            name = re.sub(r"\s+", " ", name).upper()
            if 5 <= len(name) <= 60 and _looks_like_person_name(name):
                return name
    return None


def _extract_cedula(text: str) -> Optional[str]:
    from backend.agent.regex_library import CC_ACCIONANTE
    return _first_match(CC_ACCIONANTE.pattern, text)


def _extract_juzgado(text: str) -> Optional[str]:
    from backend.agent.regex_library import SELLO_JUZGADO
    m = SELLO_JUZGADO.pattern.search(text)
    if m:
        full = m.group(0).strip()
        # Cap longitud
        return re.sub(r"\s+", " ", full)[:100]
    # Fallback: línea con "Juzgado"
    for line in text.splitlines()[:50]:
        if re.match(r"^\s*JUZGADO\s+\w", line, re.I):
            return re.sub(r"\s+", " ", line.strip())[:100]
    return None


# Fechas — muy comunes con marcadores en español
_FECHA_PATTERNS = {
    "fecha_ingreso": [
        re.compile(r"(?i)(?:fecha\s+de\s+(?:ingreso|admisi[oó]n|presentaci[oó]n|radicaci[oó]n))[\s:]*?(\d{1,2}[/\-\.]\d{1,2}[/\-\.](?:20)?\d{2,4})"),
        re.compile(r"(?i)(?:radicad[oa]\s+el|presentad[oa]\s+el|admit[ió]\s+el)\s+(\d{1,2}[/\-\.]\d{1,2}[/\-\.](?:20)?\d{2,4})"),
    ],
    "fecha_fallo_1st": [
        re.compile(r"(?i)(?:Bucaramanga|Santander)?,?\s*(\d{1,2}\s+de\s+\w+\s+de\s+20\d{2})"),
        re.compile(r"(?i)fecha\s+(?:de\s+)?(?:fallo|sentencia)[\s:]*?(\d{1,2}[/\-\.]\d{1,2}[/\-\.](?:20)?\d{2,4})"),
    ],
    "fecha_apertura_incidente": [
        re.compile(r"(?i)(?:apertura\s+(?:de\s+)?incidente|abre\s+incidente|incidente\s+de\s+desacato)[\s\S]{0,200}?(\d{1,2}[/\-\.]\d{1,2}[/\-\.](?:20)?\d{2,4})"),
    ],
}


_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


def _norm_fecha(raw: str) -> Optional[str]:
    """Normaliza a DD/MM/YYYY. Acepta '15/03/2026', '15-3-26', '15 de marzo de 2026'."""
    if not raw:
        return None
    raw = raw.strip()
    # Formato "15 de marzo de 2026"
    m = re.match(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(20\d{2})", raw, re.I)
    if m:
        d, mes_word, y = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        mes = _MESES.get(mes_word)
        if mes and 1 <= d <= 31:
            return f"{d:02d}/{mes:02d}/{y}"
        return None
    # Formato numérico
    m = re.match(r"(\d{1,2})[/\-\.](\d{1,2})[/\-\.]((?:20)?\d{2,4})", raw)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        if 1 <= d <= 31 and 1 <= mo <= 12 and 2020 <= y <= 2027:
            return f"{d:02d}/{mo:02d}/{y}"
    return None


def _extract_fecha(text: str, field_name: str) -> Optional[str]:
    for pat in _FECHA_PATTERNS.get(field_name, []):
        m = pat.search(text)
        if m:
            n = _norm_fecha(m.group(1))
            if n:
                return n
    return None


def _extract_sentido_fallo(text: str) -> Optional[str]:
    """Detecta sentido del fallo en sentencia. Valores canónicos: CONCEDE / NIEGA / IMPROCEDENTE / CONCEDE PARCIALMENTE."""
    if not text:
        return None
    # Buscar en zona "RESUELVE" para mayor precisión
    m = re.search(r"(?i)RESUELVE\s*[:\.]?([\s\S]{0,800})", text)
    zone = m.group(1) if m else text[:5000]
    # Match prefijo + cualquier sufijo (CONCEDE, CONCEDER, CONCEDIDA, AMPARAR, AMPARO, TUTELAR, TUTELA)
    if re.search(r"(?i)\b(?:concede\w*|amparar?\w*)\b.{0,80}\bparcial", zone, re.DOTALL):
        return "CONCEDE PARCIALMENTE"
    if re.search(r"(?i)\b(?:CONCED\w*|AMPAR\w*|TUTEL\w*)\b", zone):
        return "CONCEDE"
    if re.search(r"(?i)\b(?:NEGAR|NIEG\w*|NO\s+CONCEDE)\b", zone):
        return "NIEGA"
    if re.search(r"(?i)\b(?:IMPROCEDENTE|IMPROCEDENCIA)\b", zone):
        return "IMPROCEDENTE"
    return None


def _extract_impugnacion_flag(text: str, doctype: str) -> Optional[str]:
    """SI/NO. Si hay un doc IMPUGNACION → SI. Si la sentencia firmó ejecutoriada → NO."""
    if doctype == "IMPUGNACION":
        return "SI"
    if re.search(r"(?i)(impugna\s+(?:el|la)\s+|recurso\s+de\s+impugnaci[oó]n)", text):
        return "SI"
    return None


def _extract_incidente_flag(text: str, doctype: str) -> Optional[str]:
    if doctype == "INCIDENTE":
        return "SI"
    if re.search(r"(?i)(?:abre\s+incidente|incidente\s+de\s+desacato|aper(t|c)ura\s+de\s+incidente)", text):
        return "SI"
    return None


def _extract_abogado_footer(text: str) -> Optional[str]:
    """De DOCX de respuesta: 'Proyectó: NOMBRE'."""
    from backend.agent.regex_library import ABOGADO_FOOTER
    m = ABOGADO_FOOTER.pattern.search(text)
    if m:
        name = m.group(1).strip()
        name = re.sub(r"\s+", " ", name)[:60]
        # Cortar después de salto de línea o cargo
        name = re.split(r"(?i)\s*(?:CPS|OPS|CC\.?|cargo|profes)", name)[0].strip()
        if len(name) >= 5:
            return name.upper()
    return None


_CITY_NOISE = {
    "SANTANDER", "FAMILIA", "CIRCUITO", "MUNICIPAL", "EDUCACION",
    "EDUCACIÓN", "JUSTICIA", "SEDE", "JUDICIAL", "JUSTICA",
    "TRIBUNAL", "JUZGADO", "PRIMERO", "SEGUNDO", "TERCERO",
    "CUARTO", "QUINTO", "SEXTO", "SEPTIMO", "OCTAVO", "NOVENO",
    "DECIMO", "PROMISCUO", "CIVIL", "PENAL", "LABORAL", "DEL",
}


def _extract_ciudad(text: str) -> Optional[str]:
    """Ciudad del JUZGADO (no del afectado). Heurística simple del header."""
    # Header tipo "JUZGADO X PROMISCUO MUNICIPAL DE BUCARAMANGA"
    # Captura SOLO una palabra (la ciudad). Después limpiamos por si viene con \n o ruido.
    m = re.search(
        r"(?i)(?:JUZGADO|TRIBUNAL)[^\n]{0,80}?\bDE\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+)",
        text,
    )
    if not m:
        return None
    ciudad = m.group(1).strip().upper()
    # Cortar en newline / saltos por si acaso
    ciudad = ciudad.split("\n")[0].split("\r")[0].strip()
    # Quitar caracteres no alfa al final
    ciudad = re.sub(r"[^A-ZÁÉÍÓÚÑa-záéíóúñ]+$", "", ciudad)
    if not ciudad or ciudad.upper() in _CITY_NOISE:
        return None
    return ciudad


# ============================================================
# ORQUESTADOR DE LA ETAPA
# ============================================================

# Prioridad de doc_type por campo: dónde buscar primero el dato.
# Si no se encuentra ahí, se cae a "todos los docs".
_DOC_PRIORITY = {
    "radicado_23_digitos": ["AUTO_ADMISORIO", "SENTENCIA", "EMAIL", "OTRO"],
    "radicado_forest": ["EMAIL", "OTRO", "AUTO_ADMISORIO"],
    "accionante": ["AUTO_ADMISORIO", "SENTENCIA", "EMAIL", "OTRO"],
    "juzgado": ["AUTO_ADMISORIO", "SENTENCIA", "OTRO"],
    "ciudad": ["AUTO_ADMISORIO", "SENTENCIA", "OTRO"],
    "fecha_ingreso": ["AUTO_ADMISORIO", "EMAIL", "OTRO"],
    "sentido_fallo_1st": ["SENTENCIA", "OTRO"],
    "fecha_fallo_1st": ["SENTENCIA", "OTRO"],
    "sentido_fallo_2nd": ["SENTENCIA", "IMPUGNACION", "OTRO"],
    "fecha_fallo_2nd": ["SENTENCIA", "IMPUGNACION", "OTRO"],
    "abogado_responsable": ["RESPUESTA", "OTRO"],
    "fecha_apertura_incidente": ["INCIDENTE", "OTRO"],
}


def _docs_in_order(docs: list[DocText], field_name: str) -> list[DocText]:
    """Reordena docs según prioridad por tipo. Docs con error al final."""
    typed = [(d, _doctype(d)) for d in docs if d.ok]
    priority = _DOC_PRIORITY.get(field_name, [])

    def key(item):
        d, t = item
        if t in priority:
            return (priority.index(t), len(d.text))
        return (999, len(d.text))

    typed.sort(key=key)
    return [d for d, _ in typed]


_FOLDER_ACCIONANTE_PATTERN = re.compile(
    r"^\d{4}[-\s]\d{3,5}\s+(.+)$"  # "2026-00364 DIANA CRISTINA MANTILLA"
)
_FOLDER_NAME_TAIL_NOISE = re.compile(
    r"\s+(?:ACCIONADA|ACCIONANTE|VS\.?|CONTRA|Y\s+OTROS?|PRESONERO|PERSONERO|"
    r"AGENTE\s+OFICIOSA?|REPRESENTAD[OA]).*$",
    re.IGNORECASE,
)


def _derive_accionante_from_folder(folder_name: Optional[str]) -> Optional[str]:
    """Extrae el nombre del accionante del folder_name siguiendo el patrón
    `<rad_corto> <ACCIONANTE>` documentado en CLAUDE.md.

    Casos:
      "2026-00364 DIANA CRISTINA MANTILLA"        → "DIANA CRISTINA MANTILLA"
      "2026-00086 JOAN PEDRAZA ACCIONADA"          → "JOAN PEDRAZA"
      "2026-00065 LUIS Y PERSONERO MUNICIPAL DE X" → "LUIS"
    """
    if not folder_name:
        return None
    m = _FOLDER_ACCIONANTE_PATTERN.match(folder_name.strip())
    if not m:
        return None
    raw = m.group(1).strip()
    raw = _FOLDER_NAME_TAIL_NOISE.sub("", raw).strip()
    raw = re.sub(r"\s+", " ", raw).upper()
    if 5 <= len(raw) <= 80 and _looks_like_person_name(raw):
        return raw
    return None


def run(docs: list[DocText], fields: ExtractedFields, folder_name: Optional[str] = None) -> ExtractedFields:
    """Aplica todos los regex del library a los docs y llena los campos vacíos.

    Política: una vez que un campo tiene valor, no se reescribe (set() lo
    garantiza). Recorre docs en orden de prioridad por tipo.

    Args:
        docs: lista de DocText ya leídos
        fields: ExtractedFields a llenar
        folder_name: opcional. Si se pasa, se usa como FALLBACK para extraer
            accionante cuando los regex fallan.
    """
    if not docs:
        # Caso especial: sin docs, intentamos al menos accionante por folder_name
        if folder_name and fields.is_empty("accionante"):
            v = _derive_accionante_from_folder(folder_name)
            if v:
                fields.set("accionante", v, FieldSource.REGEX)
        return fields

    classified = [(d, _doctype(d)) for d in docs if d.ok]
    if not classified:
        logger.warning("regex_pass: 0 docs legibles")
        return fields

    # ----- Identificadores fuertes (radicado, FOREST, cédula, accionante) -----
    for d, _ in classified:
        if fields.is_empty("radicado_23_digitos"):
            v = _extract_radicado_23(d.text)
            if v:
                fields.set("radicado_23_digitos", v, FieldSource.REGEX)

        if fields.is_empty("radicado_forest"):
            v = _extract_forest(d.text)
            if v:
                fields.set("radicado_forest", v, FieldSource.REGEX)

        if fields.is_empty("accionante"):
            v = _extract_accionante(d.text)
            if v:
                fields.set("accionante", v, FieldSource.REGEX)

    # ----- Juzgado, ciudad, fechas (más débiles, requieren más cuidado) -----
    for d in _docs_in_order(docs, "juzgado"):
        if fields.is_empty("juzgado"):
            v = _extract_juzgado(d.text)
            if v:
                fields.set("juzgado", v, FieldSource.REGEX)

    for d in _docs_in_order(docs, "ciudad"):
        if fields.is_empty("ciudad"):
            v = _extract_ciudad(d.text)
            if v:
                fields.set("ciudad", v, FieldSource.REGEX)

    # fecha_ingreso y fecha_fallo_1st usan el reorder por tipo de doc.
    # fecha_apertura_incidente se maneja después en el bloque de incidentes 1/2/3
    # para garantizar orden cronológico correcto entre slots.
    for fecha_field in ("fecha_ingreso", "fecha_fallo_1st"):
        for d in _docs_in_order(docs, fecha_field):
            if fields.is_empty(fecha_field):
                v = _extract_fecha(d.text, fecha_field)
                if v:
                    fields.set(fecha_field, v, FieldSource.REGEX)

    # ----- Sentido fallo + flags (impugnación / incidente) -----
    for d, t in classified:
        if t in {"SENTENCIA", "OTRO"} and fields.is_empty("sentido_fallo_1st"):
            v = _extract_sentido_fallo(d.text)
            if v:
                fields.set("sentido_fallo_1st", v, FieldSource.REGEX)

        if fields.is_empty("impugnacion"):
            v = _extract_impugnacion_flag(d.text, t)
            if v:
                fields.set("impugnacion", v, FieldSource.REGEX)
        # NOTA: incidente / incidente_2 / incidente_3 se asignan más abajo en
        # un bloque cronológico para que el slot 1 sea el incidente más antiguo.

    # Default: si no se encontró flag SI de impugnación, asumir NO
    if fields.is_empty("impugnacion"):
        fields.set("impugnacion", "NO", FieldSource.REGEX)

    # ----- Abogado responsable (footer DOCX de respuesta) -----
    for d in _docs_in_order(docs, "abogado_responsable"):
        if fields.is_empty("abogado_responsable"):
            v = _extract_abogado_footer(d.text)
            if v:
                fields.set("abogado_responsable", v, FieldSource.REGEX)

    # ----- Fallback accionante desde folder_name si regex no encontró -----
    if fields.is_empty("accionante") and folder_name:
        v = _derive_accionante_from_folder(folder_name)
        if v:
            fields.set("accionante", v, FieldSource.REGEX)

    # ----- tipo_actuacion (TUTELA por default; INCIDENTE si solo hay docs de incidente) -----
    if fields.is_empty("tipo_actuacion"):
        types = {t for _, t in classified}
        if types == {"INCIDENTE"} or (types - {"INCIDENTE", "OTRO"}) == set():
            fields.set("tipo_actuacion", "INCIDENTE", FieldSource.REGEX)
        else:
            fields.set("tipo_actuacion", "TUTELA", FieldSource.REGEX)

    # ----- Incidentes (slots 1, 2, 3) — asigna en orden cronológico -----
    # Política: si hay N docs tipo INCIDENTE, el más antiguo va a slot 1,
    # el segundo a slot 2, el tercero a slot 3. Los _docs_in_order falla
    # con empates por longitud, así que aquí ordenamos por la fecha
    # extraída del propio documento (clave estable cronológica).
    incidente_docs = [d for d, t in classified if t == "INCIDENTE"]
    if incidente_docs:
        dated: list[tuple[str, DocText]] = []
        for d in incidente_docs:
            f = _extract_fecha(d.text, "fecha_apertura_incidente") or "9999"
            dated.append((f, d))
        dated.sort(key=lambda x: x[0])  # asc — el más antiguo primero

        slots = [
            ("incidente",   "fecha_apertura_incidente"),
            ("incidente_2", "fecha_apertura_incidente_2"),
            ("incidente_3", "fecha_apertura_incidente_3"),
        ]
        for i, (flag_key, fecha_key) in enumerate(slots):
            if i >= len(dated):
                break
            f, _d = dated[i]
            if fields.is_empty(flag_key):
                fields.set(flag_key, "SI", FieldSource.REGEX)
            if f and f != "9999" and fields.is_empty(fecha_key):
                fields.set(fecha_key, f, FieldSource.REGEX)

    # Defaults NO para todos los flags de incidente que sigan vacíos
    for slot in ("incidente", "incidente_2", "incidente_3"):
        if fields.is_empty(slot):
            fields.set(slot, "NO", FieldSource.REGEX)

    return fields
