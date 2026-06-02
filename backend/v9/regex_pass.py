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
from backend.v9.catalog_resolve import resolve_abogado

import unicodedata as _ud

# ============================================================
# HELPERS DE PERTENENCIA AL CASE (validar que un doc trata del accionante)
# ============================================================
# Usado para filtrar docs RESPUESTA "prestados" a una carpeta (insumos de otras
# tutelas que el operador metió por error). También importado por field_extractor.

_ACCIONANTE_STOP = {
    "DE", "DEL", "LA", "LAS", "LOS", "EL", "Y", "O", "EN", "POR", "PARA", "CON",
    "PERSONERIA", "MUNICIPAL", "MUNICIPIO", "DEPARTAMENTAL", "DEPARTAMENTO",
    "REPRESENTACION", "REPRESENTANTE", "ACCIONANTE", "TUTELANTE", "DEFENSOR",
    "DEFENSORIA", "PUEBLO", "AGENCIA", "OFICIOSO", "OFICIOSA", "FAMILIA",
}


def _strip_accents_upper(s: str) -> str:
    norm = _ud.normalize("NFD", s.upper())
    return "".join(c for c in norm if _ud.category(c) != "Mn")


def accionante_tokens(accionante: Optional[str]) -> set[str]:
    """Tokens significativos del accionante (≥4 letras, sin stopwords, sin tildes)."""
    if not accionante:
        return set()
    norm = _strip_accents_upper(accionante)
    norm = re.sub(r"[^A-Z\s]", " ", norm)
    return {t for t in norm.split() if len(t) >= 4 and t not in _ACCIONANTE_STOP}


def doc_mentions_accionante(tokens: set[str], doc_text: str) -> bool:
    """≥2 tokens significativos del accionante deben aparecer en el doc. Si el
    accionante tiene <2 tokens significativos (p.ej. "PERSONERIA MUNICIPAL"),
    exige ≥1. Devuelve False si tokens está vacío o doc_text es vacío."""
    if not tokens or not doc_text:
        return False
    norm = _strip_accents_upper(doc_text)
    hits = sum(1 for t in tokens if t in norm)
    needed = 2 if len(tokens) >= 2 else 1
    return hits >= needed


def _rad_corto_from_23(rad23: Optional[str]) -> Optional[str]:
    """Del rad de 23 dígitos extrae el formato corto "YYYY-#####" usando los
    dígitos 12-15 (año) y 16-20 (secuencial). Sin separadores intermedios."""
    if not rad23:
        return None
    digits = re.sub(r"\D", "", rad23)
    if len(digits) < 21:
        return None
    return f"{digits[12:16]}-{digits[16:21]}"


def _rad_in_text(rad: str, norm_text: str) -> bool:
    """Busca un radicado en un texto normalizado (mayúsculas, sin tildes).
    Tolera separadores entre los dígitos pero exige boundaries antes/después
    para evitar colisiones por substring (un rad corto "2026-00037" no debe
    matchear si los 9 dígitos aparecen dentro de otro número más largo)."""
    digits = re.sub(r"\D", "", rad or "")
    if not digits or not norm_text:
        return False
    # Permitir hasta 3 separadores no-dígito entre dígitos consecutivos,
    # boundary = no-dígito (o inicio/fin) a cada lado.
    pat = r"(?<!\d)" + r"\D{0,3}".join(digits) + r"(?!\d)"
    return re.search(pat, norm_text) is not None


def doc_belongs_to_case(
    accionante_tok: set[str],
    radicados: set[str],
    doc_text: str,
    doc_filename: str = "",
) -> bool:
    """Decide si un doc trata del case actual. Pasa si:
      (a) menciona ≥2 tokens significativos del accionante, O
      (b) cita el rad23 o el rad_forest del case (estos son globalmente únicos), O
      (c) cita un rad corto del case ("YYYY-#####") Y además:
            - el rad corto aparece también en el filename (señal operativa fuerte:
              el operador nombró el archivo con ese rad), O
            - al menos 1 token del accionante aparece en el texto (desambigua
              dos tutelas distintas con el mismo rad corto en juzgados diferentes).
    Cubre contestaciones SED genéricas que solo citan el radicado, sin dejar
    pasar docs prestados de otras tutelas que comparten rad corto.
    Si no hay ni accionante ni radicados, devuelve True (no se puede filtrar)."""
    if not accionante_tok and not radicados:
        return True
    if accionante_tok and doc_mentions_accionante(accionante_tok, doc_text):
        return True
    if not radicados:
        return False
    norm_text = _strip_accents_upper(doc_text or "")
    norm_filename = _strip_accents_upper(doc_filename or "")
    norm_haystack = norm_filename + "\n" + norm_text
    # (b) rad globalmente único en haystack
    for rad in radicados:
        if not rad:
            continue
        digits = re.sub(r"\D", "", rad)
        # rad23 = 21+ dígitos · rad_forest SED = 10-11 dígitos · rad corto = 9 dígitos
        if len(digits) >= 10 and _rad_in_text(rad, norm_haystack):
            return True
    # (c) rad corto con desambiguación
    acc_any_hit = bool(
        accionante_tok and any(t in norm_text for t in accionante_tok)
    )
    for rad in radicados:
        if not rad:
            continue
        digits = re.sub(r"\D", "", rad)
        if len(digits) != 9:  # rad corto: YYYY + 5 dígitos
            continue
        in_filename = _rad_in_text(rad, norm_filename)
        in_text = _rad_in_text(rad, norm_text)
        if in_filename:
            return True
        if in_text and acc_any_hit:
            return True
    return False


def _rad_corto_from_folder(folder_name: Optional[str]) -> Optional[str]:
    """Del folder_name del case extrae el rad corto "YYYY-#####"."""
    if not folder_name:
        return None
    m = re.match(r"\s*(\d{4})\s*[-/\s]\s*(\d{3,5})", folder_name)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2).zfill(5)}"

logger = logging.getLogger("tutelas.v9.regex_pass")


# ============================================================
# CLASIFICACIÓN LIGERA DE DOCS POR KEYWORDS (sin IA)
# ============================================================

_KW_AUTO_ADMISORIO = re.compile(
    r"(?i)(auto\s*avoca|auto\s*admite|admite\s*tutela|avoca\s*conocimiento|"
    r"admit\w*\s+(?:la\s+)?(?:presente\s+)?acci[oó]n\s+(?:constitucional\s+)?de\s+tutela)")
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
    # Email primero: un archivo "Email_..." es un correo aunque su asunto mencione
    # "AUTO_ADMITE", "INCIDENTE", "SENTENCIA", etc. (es la notificación, no el doc).
    if "email" in fn or "gmail" in fn or fn.endswith(".md"):
        return "EMAIL"
    if "incidente" in fn or "desacato" in fn:
        return "INCIDENTE"
    if "auto" in fn and ("admi" in fn or "avoca" in fn):  # admite, admisorio, admision
        return "AUTO_ADMISORIO"
    if "sentencia" in fn or ("fallo" in fn and "tutela" not in fn):
        return "SENTENCIA"
    if "impugna" in fn:
        return "IMPUGNACION"
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

# --- Recuperación ANCLADA al folder (dept-agnóstica) -------------------------
# El prefijo histórico `68\d` (Santander) tiene dos puntos ciegos:
#   1) ignora tutelas radicadas FUERA de Santander (Medellín 05, Bogotá 11,
#      Cúcuta 54…) donde la SED entra como vinculada;
#   2) falla cuando hay un separador justo tras "68" ("68-296...", "68.679...").
# Solución: una pasada que acepta CUALQUIER departamento pero exige que la cola
# del rad (año chars 12-15 + consecutivo chars 16-20) coincida con el rad corto
# del folder. Eso descarta rads citados/prestados (no inventa por frecuencia).
_RAD23_CAND = re.compile(r"\d[\d.\-\s–—]{18,45}\d")
# Rad corto del folder → (año4, consecutivo5). "2026-00061 X" → ("2026","00061").
_RAD23_FOLDER_SHORT = re.compile(r"(20\d{2})[-.\s]?0?(\d{4,5})")


def _folder_short_rad(folder_name: Optional[str]) -> Optional[tuple[str, str]]:
    """Devuelve (año4, consecutivo5) del rad corto en el folder, o None.

    OJO: muchos folders usan el nº INTERNO de la Gobernación (ej. "2026-21107")
    en vez del consecutivo del juzgado. En ese caso el ancla no casará con el
    rad real del juzgado → no se recupera nada (seguro: no inventa).
    """
    if not folder_name:
        return None
    m = _RAD23_FOLDER_SHORT.search(folder_name)
    if not m:
        return None
    return (m.group(1), m.group(2).zfill(5))


def _anchored_rad23(text: str, anchor: tuple[str, str]) -> Optional[str]:
    """Rad23 de cualquier departamento cuya cola (año+consecutivo) == anchor."""
    if not text:
        return None
    year, consec = anchor
    pos_order: list[tuple[int, str]] = []
    for m in _RAD23_CAND.finditer(text):
        cand = re.sub(r"\D", "", m.group(0))
        if len(cand) != 23:
            continue
        if cand[12:16] != year or cand[16:21] != consec:
            continue
        try:
            if int(cand[21:23]) > 10:  # recurso plausible (00/01, raro 02-03)
                continue
        except ValueError:
            continue
        pos_order.append((m.start(), cand))
    if not pos_order:
        return None
    from collections import Counter
    counts = Counter(c for _p, c in pos_order)
    top = max(counts.values())
    topset = {c for c, n in counts.items() if n == top}
    for _p, rad in pos_order:
        if rad in topset:
            return rad
    return pos_order[0][1]


# Caracteres permitidos entre dígitos de un rad23 real:
#   espacios, tabs, newlines, guiones (ASCII y unicode), puntos, comas, slashes.
#   Incluye whitespace unicode comunes en docs jurídicos:
#     U+00A0 (NBSP, no-breaking space) — frecuente en subjects de email
#     U+2009 (thin space), U+202F (narrow no-break space)
# Si entre los dígitos hay LETRAS o cualquier otro símbolo, NO es un rad real
# (puede ser composición espuria de IDs, hashes, FOREST, etc.).
_RAD23_VALID_SEPARATORS = set(" \t\n\r-./,–—\xa0  ")


def _extract_radicado_23(
    text: str, anchor: Optional[tuple[str, str]] = None
) -> Optional[str]:
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

    # (0) Recuperación ANCLADA al folder: si tenemos el rad corto del folder,
    # aceptamos el rad de CUALQUIER departamento cuya cola coincida. Esto es
    # alta confianza y descarta rads citados/prestados. Solo si hay ancla.
    if anchor is not None:
        anchored = _anchored_rad23(text, anchor)
        if anchored:
            return anchored

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
# NUEVO formato FOREST Gobernación (2026+, formato único con guiones):
# tipo-año-dependencia-consecutivo, p.ej. "2-2026-104200-001763". Reemplaza al viejo de
# solo dígitos. Es muy distintivo (un dígito + guion + año + dependencia + consecutivo) →
# patrón directo seguro: ni rad23 ni rad corto tienen esta forma.
_FOREST_NUEVO = re.compile(r"\b(\d-20\d{2}-\d{4,7}-\d{3,7})\b")


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
    # NUEVO formato (2026+, único): "Gober ... 2-2026-104200-001763". Va SIEMPRE en el cuerpo
    # del correo (.md). Tiene prioridad sobre el viejo de solo dígitos. Si hay un marcador
    # "Gober" cerca, mejor, pero el patrón ya es distintivo por sí solo.
    m = _FOREST_NUEVO.search(text)
    if m:
        return m.group(1)

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


# El footer del DOCX de respuesta de la SED lista varios roles: el REDACTOR
# ("Proyectó/Elaboró/Redactó: NOMBRE") y el SUPERVISOR ("Aprobó/Revisó/Vo.Bo.: NOMBRE").
# En muchas plantillas el supervisor (la jefa del Grupo de Apoyo Jurídico) se lista PRIMERO,
# así que un .search() simple agarraba a la supervisora. Queremos al REDACTOR.
_FOOTER_ROLE_WORDS = r"proyect[oó]|elabor[oó]|redact[oó]|aprob[oó]|revis[oó]|vist[oa]\s+bueno|vo\.?\s*bo\.?"
_RE_FOOTER_ROLE = re.compile(
    rf"(?im)\b({_FOOTER_ROLE_WORDS})\s*[:.]\s*(.+?)(?=$|\b(?:{_FOOTER_ROLE_WORDS})\s*[:.]|Aport[oó]\b|Anexo)"
)
_DRAFTER_ROLE_PREFIXES = ("proyect", "elabor", "redact")
# tokens que indican cargo / dependencia (todo lo que sigue se descarta del nombre)
_RE_FOOTER_NAME_CUT = re.compile(
    r"(?i)\s*(?:[-–/|·•]?\s*)(?:CPS\b|OPS\b|CC\.?\b|cargo\b|profes|coordinador|jefe\b|"
    r"abogad[oa]\b|contratista\b|grupo\s+de\s+apoyo|l[ií]der\b|directora?\b|secretari[oa]\b|"
    r"S\.?E\.?D\.?\b|gobernaci[oó]n\b|CE\b\s*-?\s*SEC\b)"
)
_FOOTER_NAME_BAD_WORDS = {
    "SECRETARIA", "SECRETARÍA", "EDUCACION", "EDUCACIÓN", "GOBERNACION", "GOBERNACIÓN",
    "GRUPO", "APOYO", "JURIDICO", "JURÍDICO", "DESPACHO", "DIRECCION", "DIRECCIÓN",
    "INDICACIONES", "INSUMOS", "BAJO", "OFICINA", "DEPENDENCIA", "DEPARTAMENTO",
    "ANEXO", "ANEXOS", "PANTALLAZO", "INFORMACION", "INFORMACIÓN", "SIMAT", "CONTRATISTA",
}


def _footer_name_from_value(raw: str) -> Optional[str]:
    """Limpia el valor capturado tras 'rol:' y lo devuelve si parece nombre de persona."""
    name = re.sub(r"\s+", " ", (raw or "").strip())[:90]
    name = _RE_FOOTER_NAME_CUT.split(name)[0]
    name = name.strip(" .,;:-–/|·•").strip()
    if not (5 <= len(name) <= 55):
        return None
    words = name.split()
    if not (2 <= len(words) <= 6) or not all(w[:1].isalpha() for w in words):
        return None
    if any(w.upper().strip(".,") in _FOOTER_NAME_BAD_WORDS for w in words):
        return None
    return name.upper()


def _extract_abogado_footer(text: str) -> Optional[str]:
    """Del footer del DOCX de respuesta: nombre del REDACTOR ('Proyectó/Elaboró: NOMBRE'),
    prefiriéndolo sobre el SUPERVISOR ('Aprobó/Revisó: NOMBRE') cuando ambos aparecen.
    Devuelve None si no hay ningún nombre limpio (mejor vacío que atribuir a la supervisora)."""
    tail = text[-3500:] if len(text) > 3500 else text  # el footer está al final
    drafters: list[str] = []
    supervisors: list[str] = []
    for m in _RE_FOOTER_ROLE.finditer(tail):
        role = m.group(1).lower()
        name = _footer_name_from_value(m.group(2))
        if not name:
            continue
        (drafters if any(role.startswith(p) for p in _DRAFTER_ROLE_PREFIXES) else supervisors).append(name)
    for bucket in (drafters, supervisors):
        if bucket:
            return bucket[0]
    return None


_CITY_NOISE = {
    "SANTANDER", "FAMILIA", "CIRCUITO", "MUNICIPAL", "EDUCACION",
    "EDUCACIÓN", "JUSTICIA", "SEDE", "JUDICIAL", "JUSTICA",
    "TRIBUNAL", "JUZGADO", "PRIMERO", "SEGUNDO", "TERCERO",
    "CUARTO", "QUINTO", "SEXTO", "SEPTIMO", "OCTAVO", "NOVENO",
    "DECIMO", "PROMISCUO", "CIVIL", "PENAL", "LABORAL", "DEL",
    # Atributos del juzgado que NO son ciudad
    "REPARTO", "CONOCIMIENTO", "GARANTIAS", "GARANTÍAS", "EJECUCION", "EJECUCIÓN",
    "DESCONGESTION", "DESCONGESTIÓN", "ADOLESCENTES", "MIXTO", "ORALIDAD",
    "SENTENCIAS", "ADMINISTRATIVO", "CONTROL", "ESTE", "DISTRITO", "CAUSAS",
    "COMPETENCIAS", "MULTIPLES", "MÚLTIPLES", "PEQUEÑAS",
}
# Palabras "atributo" que pueden preceder a la ciudad real: "...DE DESCONGESTIÓN DE
# BUCARAMANGA" → la ciudad es BUCARAMANGA.
_CITY_PREFIX_NOISE = re.compile(
    r"(?i)^(?:DESCONGESTI[ÓO]N|EJECUCI[ÓO]N(?:\s+DE\s+SENTENCIAS?)?|SENTENCIAS?|"
    r"GARANT[ÍI]AS|CONOCIMIENTO|ADOLESCENTES|PEQUE[ÑN]AS\s+CAUSAS|REPARTO|"
    r"COMPETENCIAS\s+M[ÚU]LTIPLES|CONTROL\s+DE\s+GARANT[ÍI]AS|FAMILIA)"
    r"\s+(?:Y\s+COMPETENCIAS\s+M[ÚU]LTIPLES\s+)?DE\s+"
)


def _extract_ciudad(text: str) -> Optional[str]:
    """Ciudad del JUZGADO (no del afectado). Heurística del header.
    Captura nombres compuestos ("SAN VICENTE DE CHUCURÍ", "SABANA DE TORRES")."""
    m = re.search(
        r"(?i)(?:JUZGADO|TRIBUNAL)[^\n]{0,80}?\bDE\s+"
        r"((?:SAN(?:TA)?\s+)?[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+"
        r"(?:\s+(?:DE|DEL|LA|LOS|LAS)\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+){0,3})",
        text,
    )
    if not m:
        return None
    ciudad = re.sub(r"\s+", " ", m.group(1)).strip().upper()
    # Quitar prefijos-atributo del juzgado ("DESCONGESTIÓN DE X" → "X"), repetidamente.
    for _ in range(3):
        nueva = _CITY_PREFIX_NOISE.sub("", ciudad).strip()
        if nueva == ciudad:
            break
        ciudad = nueva
    # Quitar sufijo " SANTANDER" y caracteres no-alfa al final
    ciudad = re.sub(r"\s+SANTANDER$", "", ciudad).strip()
    ciudad = re.sub(r"[^A-ZÁÉÍÓÚÑ ]+$", "", ciudad).strip()
    # Si quedó "ALGO DE CIUDAD" y "ALGO" es ruido, quedarse con lo último tras " DE "
    palabras = ciudad.split()
    if len(palabras) >= 3 and " DE " in f" {ciudad} " and palabras[0] in _CITY_NOISE:
        ciudad = ciudad.split(" DE ", 1)[1].strip()
    if not ciudad or ciudad in _CITY_NOISE or len(ciudad) < 3:
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
    "abogado_responsable": ["RESPUESTA"],
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


def run(
    docs: list[DocText],
    fields: ExtractedFields,
    folder_name: Optional[str] = None,
    *,
    case_accionante: Optional[str] = None,
    case_radicados: Optional[set[str]] = None,
) -> ExtractedFields:
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
    # Ancla del folder para recuperar rads de cualquier depto (ver _anchored_rad23).
    rad_anchor = _folder_short_rad(folder_name)

    # FIX (2026-05-28): para rad23, PRIORIZAR docs de origen judicial
    # (AUTO_ADMISORIO/DEMANDA_TUTELA/SENTENCIA_1RA) sobre respuestas FOREST.
    # Razón: el rad de respuesta SED puede ser un rad interno de Gobernación
    # (FOREST 68XXX) que NO coincide con el rad del juzgado real (puede ser
    # de otro depto: ej. c139 tenía rad23 de Charalá 68167 cuando el juzgado
    # real era Encino 68162). El AUTO_ADMISORIO es la fuente autoritativa.
    _JUDICIAL_DOCTYPES = {"AUTO_ADMISORIO", "DEMANDA_TUTELA", "SENTENCIA_1RA",
                          "PDF_AUTO_ADMISORIO", "PDF_SENTENCIA", "ANEXO_DEMANDA"}
    judicial_first = sorted(
        classified,
        key=lambda dc: 0 if dc[1] in _JUDICIAL_DOCTYPES else 1,
    )
    for d, _ in judicial_first:
        if fields.is_empty("radicado_23_digitos"):
            v = _extract_radicado_23(d.text, anchor=rad_anchor)
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

    # Última excepción para radicado_23_digitos: si NINGÚN doc trae el CUP de 23
    # dígitos (muchos juzgados municipales solo imprimen "RADICADO: 2026-00083"),
    # caer al rad corto del FOLDER, pero CORROBORADO contra un doc JUDICIAL.
    # El discriminador NO es la magnitud (los Juzgados de Pequeñas Causas usan
    # consecutivos > 10000 legítimos, ej. c175 "2026-10070") sino que el rad del
    # folder aparezca junto a "radicado" en el auto/sentencia/demanda del juzgado.
    # Eso confirma que es el rad real del juzgado y descarta el nº interno de la
    # Gobernación (que solo aparece en las RESPUESTA de la SED) y los rads citados.
    # Decisión Wilson 2026-06-01: "trabajamos con lo que tenemos". Formato AAAA-NNNNN.
    if fields.is_empty("radicado_23_digitos") and rad_anchor is not None:
        _yr, _cons = rad_anchor
        _rad_rx = re.compile(r"radicad[oa]\b[^\d]{0,40}" + _yr + r"\s*[-.\s]\s*0*" + _cons.lstrip("0") + r"\b", re.IGNORECASE)
        for _d, _dt in judicial_first:
            if _dt in _JUDICIAL_DOCTYPES and _d.text and _rad_rx.search(_d.text):
                fields.set("radicado_23_digitos", f"{_yr}-{_cons}", FieldSource.REGEX)
                break

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
    # fecha_fallo_1st NO se extrae aquí: el guard `_doctype(d)=="SENTENCIA"` lo derrota
    # la misma mala clasificación que sentido_fallo (un doc con "RESUELVE:" se marca
    # "SENTENCIA" aunque sea un auto/escrito) → inventaba fecha de fallo en recién
    # admitidas. Autoridad ÚNICA: field_extractor_pass.extract_fecha_fallo_1ra_for_case
    # (valida que exista sentencia 1ra real).
    for fecha_field in ("fecha_ingreso",):
        for d in _docs_in_order(docs, fecha_field):
            if fields.is_empty(fecha_field):
                v = _extract_fecha(d.text, fecha_field)
                if v:
                    fields.set(fecha_field, v, FieldSource.REGEX)

    # ----- Sentido fallo + flags (impugnación / incidente) -----
    for d, t in classified:
        # sentido_fallo_1st: NO se extrae aquí. `_doctype` clasifica por keyword y
        # marca "SENTENCIA" cualquier doc con "RESUELVE:" — incluido un ESCRITO DE TUTELA
        # que cita un precedente o redacta su pretensión como dispositiva ("solicito que se
        # RESUELVA: PRIMERO TUTELAR...") → inventaba CONCEDE en casos recién admitidos sin
        # fallo (bug c226/c478/c479: el guard `t=="SENTENCIA"` lo derrota la mala clasif.).
        # Autoridad ÚNICA: field_extractor_pass.extract_sentido_fallo_1ra_for_case, que usa
        # el doc_type REAL de la DB (SENTENCIA_1RA) y devuelve None si no hay fallo.

        if fields.is_empty("impugnacion"):
            v = _extract_impugnacion_flag(d.text, t)
            if v:
                fields.set("impugnacion", v, FieldSource.REGEX)
        # NOTA: incidente / incidente_2 / incidente_3 se asignan más abajo en
        # un bloque cronológico para que el slot 1 sea el incidente más antiguo.

    # Default: si no se encontró flag SI de impugnación, asumir NO
    if fields.is_empty("impugnacion"):
        fields.set("impugnacion", "NO", FieldSource.REGEX)

    # ----- Abogado responsable (fallback si field_extractor_pass no llenó) -----
    # Regla cerrada (feedback Wilson 2026-05-18, mem feedback-abogado-responsable-fuente):
    #   (1) Universo restringido a docs doc_type == "RESPUESTA".
    #   (2) El firmante debe resolver a uno de los 17 abogados oficiales (catalogo,
    #       conf >= 0.85). Si no, NO escribir nada.
    #   (3) El doc debe pertenecer al case: accionante (≥2 tokens) O radicado en
    #       texto/filename con boundaries. Se usa SIEMPRE el accionante/radicados
    #       pasados EXPLÍCITAMENTE por el pipeline (case_accionante / case_radicados),
    #       NO `fields.values` — porque la extracción de accionante puede estar
    #       contaminada por docs prestados a la carpeta y envenenar el filtro.
    if fields.is_empty("abogado_responsable"):
        acc_tokens_local = accionante_tokens(case_accionante)
        rads_local = set(case_radicados) if case_radicados else set()
        # Si el caller no proveyó radicados, derivar al menos del folder_name
        if not rads_local and folder_name:
            rc = _rad_corto_from_folder(folder_name)
            if rc:
                rads_local.add(rc)
        for d in docs:
            if not d.ok or _doctype(d) != "RESPUESTA":
                continue
            if not fields.is_empty("abogado_responsable"):
                break
            # Regla (3): si el pipeline pasó accionante/rads, filtrar; si no
            # (test sintético sin DB), no filtrar por pertenencia.
            if (acc_tokens_local or rads_local) and not doc_belongs_to_case(
                acc_tokens_local, rads_local, d.text, d.filename
            ):
                continue
            v = _extract_abogado_footer(d.text)
            if not v:
                continue
            canonical, conf = resolve_abogado(v)
            if not canonical or conf < 0.85:
                continue
            fields.set("abogado_responsable", v, FieldSource.REGEX)
            fields.abogado_canonical = canonical
            fields.abogado_canonical_confidence = conf

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
