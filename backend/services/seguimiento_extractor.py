"""Extractor de plazo de cumplimiento desde sentencias de tutela.

Regla: para cada sentencia (1ra o 2da instancia) con fallo desfavorable a SED,
identificar el primer ordinal del RESUELVE con orden imperativa, descartar
plazos procesales (impugnación / Corte / revisión), y devolver el plazo del
resultado final (si hay dos plazos en el mismo ordinal, el más largo).

Reglas operativas validadas con Wilson (2026-05-19):
  - Pares de plazo en MISMO ordinal (48h iniciar + 10 días resultado) → el más largo.
  - SED no destinataria directa → guardar igual el plazo de la entidad principal
    (la SED es vinculada y debe acompañar; vigilamos el plazo).
  - Plazos procesales (impugnación, recurso, Corte) NO son plazos de cumplimiento.

Sin IA. Devuelve None si no logra extraer — el caller decide si activa LLM fallback.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ── Diccionarios ────────────────────────────────────────────────────────────

# Palabras → número (español, casos comunes en sentencias colombianas).
_NUM_WORDS: dict[str, int] = {
    "un": 1, "uno": 1, "una": 1,
    "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciseis": 16, "dieciséis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19,
    "veinte": 20, "veintiuno": 21, "veintidos": 22, "veintidós": 22,
    "veintitres": 23, "veintitrés": 23, "veinticuatro": 24,
    "veinticinco": 25, "veintiseis": 26, "veintiséis": 26,
    "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
    "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
    "setenta": 70, "ochenta": 80, "noventa": 90, "cien": 100, "ciento": 100,
}

# Combinados con "y" — los más frecuentes en sentencias.
_COMPOUND_WORDS: dict[str, int] = {
    "treinta y seis": 36, "cuarenta y ocho": 48, "setenta y dos": 72,
    "noventa y seis": 96, "ciento veinte": 120, "ciento ochenta": 180,
    "doscientos cuarenta": 240, "trescientos sesenta": 360,
}


# ── Regex ───────────────────────────────────────────────────────────────────

# Documentos que NO son la sentencia (autos correctivos, oficios, correos).
_NOT_SENTENCIA = re.compile(
    r"(AUTO\s+(?:QUE\s+)?CORRIGE"
    r"|OFICIO\s+\w*\s*NOTIFICA"
    r"|OFICIO\s+No\.?\s*\d+"           # "OFICIO No. 147" — encabezado de oficios
    r"|NOTIFICACI[OÓ]N\s+FALLO"        # "NOTIFICACIÓN FALLO TUTELA…"
    r"|NOTIFICANDO\s+(?:el|la)\s+FALLO"
    r"|outlook\.cloud\.microsoft"
    r"|/mail/sentitems"
    r"|^Desde:\s.*<.*@"
    r"|^From:\s.*<.*@)",
    re.IGNORECASE | re.MULTILINE,
)

# Detecta si una 2da instancia SOLO confirma sin emitir nueva orden con plazo.
# Cuando esto pasa, el plazo de cumplimiento original está en la sentencia de 1ra.
_SOLO_CONFIRMA = re.compile(
    r"^\s*PRIMER[OA][\s:.]+\s*CONFIRMAR\s+(?:la\s+sentencia|el\s+fallo|en\s+(?:su\s+)?integridad|el\s+ordinal)",
    re.IGNORECASE | re.MULTILINE,
)

# Bloque RESUELVE / FALLA / DECIDE — con encabezado claro (cuidado con "resuelve" en
# antecedentes). Exigimos formato típico jurídico: salto de línea + keyword + ":".
_RESUELVE_STRICT = re.compile(
    r"\n\s*(?P<kw>R\s*E\s*S\s*U\s*E\s*L\s*V\s*E|F\s*A\s*L\s*L\s*A|D\s*E\s*C\s*I\s*D\s*E)\s*[:.]?\s*\n",
    re.IGNORECASE,
)

# Variante laxa para la COLA del fallo (últimas páginas): no exige que el keyword
# esté aislado entre saltos de línea. Acepta "RESUELVE:" pegado al texto, y suma
# RESOLUCIÓN/RESUELVO/DISPONE. Solo usar sobre texto ya acotado (resolutivo).
_RESUELVE_LENIENT = re.compile(
    r"(?P<kw>R\s*E\s*S\s*U\s*E\s*L\s*V\s*E[NO]?"
    r"|F\s*A\s*L\s*L\s*A"
    r"|D\s*E\s*C\s*I\s*D\s*E"
    r"|D\s*I\s*S\s*P\s*O\s*N\s*E"
    r"|RESOLUCI[OÓ]N)\s*[:.]?",
    re.IGNORECASE,
)


def _find_resuelve_block_lenient(full_text: str) -> Optional[str]:
    """Como _find_resuelve_block pero con el patrón laxo. Para usar SOLO sobre la
    cola del fallo ya acotada, donde no hay antecedentes narrativos que confundan."""
    matches = list(_RESUELVE_LENIENT.finditer(full_text))
    if not matches:
        return None
    return full_text[matches[-1].start():]

# Ordinales jurídicos.
_ORDINAL_RE = re.compile(
    r"\n\s*(?P<n>PRIMERO|SEGUNDO|TERCERO|CUARTO|QUINTO|SEXTO|S[EÉ]PTIMO|OCTAVO|NOVENO|D[EÉ]CIMO)"
    r"\s*[:.]\s*",
    re.IGNORECASE,
)

# Verbos imperativos que abren una orden con plazo (vs. AMPARAR / TUTELAR / NOTIFICAR
# que no son órdenes de cumplimiento). Cubre formas activas e impersonales reflexivas
# ("Ordénase a SED..." es típico de varios juzgados), futuros conjugados
# ("se ordenará al representante legal..."), y verbos sinónimos
# (CONMINAR, frecuente en sentencias de tutela en educación).
_VERBO_ORDEN = re.compile(
    r"\b(?:"
    r"ORDENAR|ORDENA|ORDENAR[ÁA]N?|ORD[EÉ]NESE|ORD[EÉ]NASE"
    r"|REQUIERA|REQUERIR|REQUERIR[ÁA]N?|REQUI[EÉ]R[AE]SE|REQU[EÉ]RIR"
    r"|DISPONER|DISPONDR[ÁA]N?|DISP[OÓ]NGASE|DISP[OÓ]NESE"
    r"|CONMINAR|CONM[IÍ]NESE|CONM[IÍ]NASE"
    r")\b",
    re.IGNORECASE,
)

# Filtro: si el ordinal habla de impugnación / Corte / recurso, NO es cumplimiento.
_ES_PROCESAL = re.compile(
    r"\b(impugna|apela(?:r|ci[oó]n)|recurso\s+(?:de|procede)|"
    r"Corte\s+Constitucional|eventual\s+revisi[oó]n|"
    r"env[ií]ar\s+(?:el\s+)?expediente|REMITIR\s+(?:el\s+)?expediente"
    r"|NOTIFICAR|NOTIF[IÍ]QUESE|REM[IÍ]TASE)",
    re.IGNORECASE,
)

# Patrón maestro de plazo. Conector permisivo (lazy entre "dentro|en|término|plazo"
# y la cantidad) para cubrir variantes tipo "dentro del término de las 48 horas",
# "en el plazo improrrogable de cuarenta y ocho (48) horas", etc.
_PLAZO_RE = re.compile(
    r"""
    # Token-pivote: una palabra "conectora" típica antes del plazo
    \b(?:t[eé]rmino|dentro|plazo|no\s+mayor)
    # Hasta 60 chars de "rellenos" cortos entre el pivote y la cantidad (lazy)
    [\w\sáéíóúñÁÉÍÓÚÑ,/-]{0,60}?
    \s+
    (?:
        # Variante 1: "cuarenta y ocho (48)"
        (?P<w1>[a-záéíóúñ]+(?:\s+y\s+[a-záéíóúñ]+)?)\s*\(\s*(?P<d1>\d+)\s*\)
        # Variante 2: "cuarenta y ocho" sin paréntesis (lookahead a unidad)
      | (?P<w2>[a-záéíóúñ]+(?:\s+y\s+[a-záéíóúñ]+)?)(?=\s+(?:HORAS?|D[IÍ]AS?|MES|SEMANAS?))
        # Variante 3: "48" desnudo
      | (?P<d3>\d+)
    )
    \s*
    (?P<unit>HORAS?|D[IÍ]AS?(?:\s+CALENDARIO)?|MES(?:ES)?(?:\s+CALENDARIO)?|SEMANAS?)
    """,
    re.IGNORECASE | re.VERBOSE,
)


# ── Tipos ───────────────────────────────────────────────────────────────────

@dataclass
class PlazoExtraido:
    dias: int                # plazo normalizado a días enteros (redondeo hacia arriba para horas)
    raw: str                 # texto original "cuarenta y ocho (48) horas"
    unidad: str              # HORAS / DIAS / MES / SEMANAS
    cantidad: int            # número en la unidad original (48 si son "48 horas")


@dataclass
class OrdenCumplimiento:
    plazo_dias: int
    plazo_raw: str           # ej. "cuarenta y ocho (48) horas"
    ordinal: str             # "SEGUNDO" / "TERCERO" / ...
    destinatario: str        # "SECRETARÍA DE EDUCACIÓN DE SANTANDER" / etc.
    orden_texto: str         # primeros 300 chars del ordinal (para audit)
    source: str = "regex"    # "regex" | "regex_strict" | "llm" | "manual"


# ── Helpers ─────────────────────────────────────────────────────────────────

def _word_to_int(w: str) -> Optional[int]:
    """Convertir palabra (o palabras "x y z") a entero. None si no es número en palabras."""
    w_norm = re.sub(r"\s+", " ", w.strip().lower())
    if w_norm in _COMPOUND_WORDS:
        return _COMPOUND_WORDS[w_norm]
    if w_norm in _NUM_WORDS:
        return _NUM_WORDS[w_norm]
    # "treinta y seis" composicional
    if " y " in w_norm:
        parts = w_norm.split(" y ", 1)
        if parts[0] in _NUM_WORDS and parts[1] in _NUM_WORDS:
            a, b = _NUM_WORDS[parts[0]], _NUM_WORDS[parts[1]]
            # decenas + unidades (treinta y seis = 36) requiere a%10==0 y b<10
            if a % 10 == 0 and b < 10:
                return a + b
    return None


def _unit_to_days(cantidad: int, unidad: str) -> int:
    """Convertir cantidad+unidad a días enteros. Horas redondea hacia arriba."""
    u = unidad.upper().strip()
    if u.startswith("HORA"):
        return max(1, math.ceil(cantidad / 24))
    if u.startswith("D"):  # DIAS / DÍAS / DIA CALENDARIO
        return cantidad
    if u.startswith("MES"):  # MESES / MES CALENDARIO
        return cantidad * 30
    if u.startswith("SEMANA"):
        return cantidad * 7
    return 0


def _read_pdf_text(file_path: str | Path) -> str:
    """Lee texto completo del PDF. Usa pymupdf directo (no doc_io porque queremos
    todo el texto para encontrar RESUELVE, no head+tail)."""
    import pymupdf
    doc = pymupdf.open(str(file_path))
    try:
        return "\n".join(doc[i].get_text() for i in range(doc.page_count))
    finally:
        doc.close()


def _find_resuelve_block(full_text: str) -> Optional[str]:
    """Devuelve el bloque desde el ÚLTIMO RESUELVE/FALLA/DECIDE encontrado.
    Usar el último evita falsos positivos con la palabra "resuelve" minúscula
    que aparece en antecedentes narrativos."""
    matches = list(_RESUELVE_STRICT.finditer(full_text))
    if not matches:
        return None
    return full_text[matches[-1].start():]


def _split_ordinales(block: str) -> list[tuple[str, str]]:
    """Parte un bloque RESUELVE en lista de (nombre_ordinal, texto_ordinal)."""
    matches = list(_ORDINAL_RE.finditer(block))
    if not matches:
        return []
    out: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(block)
        nombre = m.group("n").upper().replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ó", "O")
        out.append((nombre, block[m.start():end]))
    return out


# Caso especial: "dentro del mes calendario" / "dentro del año" sin número explícito.
# El artículo "del" implica cantidad=1.
_PLAZO_UN_RE = re.compile(
    r"dentro\s+del\s+(mes(?:\s+calendario)?|a[ñn]o)\s+(?:siguiente|posterior)",
    re.IGNORECASE,
)

# Caso especial: "de manera inmediata" / "inmediatamente" / "sin demora" → plazo de 1 día
# (no es 0 porque eso rompe lógica de fecha_limite; usamos 1 día como "lo antes posible").
_PLAZO_INMEDIATO_RE = re.compile(
    r"\b(de\s+manera\s+inmediata|inmediatamente|sin\s+(?:dilaci[oó]n|demora|tardanza)|"
    r"de\s+inmediato|sin\s+m[aá]s\s+dilaci[oó]n)\b",
    re.IGNORECASE,
)


def _find_plazos_en_ordinal(texto: str) -> list[PlazoExtraido]:
    """Encuentra todos los plazos numéricos en el texto de un ordinal."""
    plazos: list[PlazoExtraido] = []
    for m in _PLAZO_RE.finditer(texto):
        unit = m.group("unit")
        cantidad: Optional[int] = None
        raw = m.group(0).strip()
        if m.group("d1") is not None:
            cantidad = int(m.group("d1"))
        elif m.group("d3") is not None:
            cantidad = int(m.group("d3"))
        elif m.group("w2") is not None:
            cantidad = _word_to_int(m.group("w2"))
        if cantidad is None or cantidad <= 0:
            continue
        dias = _unit_to_days(cantidad, unit)
        if dias <= 0:
            continue
        plazos.append(PlazoExtraido(dias=dias, raw=raw, unidad=unit, cantidad=cantidad))

    # Caso especial: "dentro del mes calendario siguiente" → 1 mes = 30 días
    for m in _PLAZO_UN_RE.finditer(texto):
        unidad_raw = m.group(1).lower()
        if "mes" in unidad_raw:
            plazos.append(PlazoExtraido(dias=30, raw=m.group(0).strip(), unidad="MES", cantidad=1))
        elif "año" in unidad_raw or "ano" in unidad_raw:
            plazos.append(PlazoExtraido(dias=365, raw=m.group(0).strip(), unidad="AÑO", cantidad=1))

    # Caso especial: "de manera inmediata" / "inmediatamente" → 1 día.
    # Solo si no se encontró ningún plazo numérico (el numérico tiene prioridad).
    if not plazos:
        m = _PLAZO_INMEDIATO_RE.search(texto)
        if m:
            plazos.append(PlazoExtraido(dias=1, raw=m.group(0).strip(), unidad="INMEDIATO", cantidad=1))

    return plazos


# Extractor de destinatario: "ORDENAR a ENTIDAD NN para que..." → "ENTIDAD NN"
_DESTINATARIO_RE = re.compile(
    r"(?:ORDEN[AÉ]R|ORD[EÉ]NESE|REQUIERA|REQU[EÉ]RIR|DISPONER|DISP[OÓ]NGASE)\s+"
    r"(?:a\s+|al\s+)"
    r"(?:la\s+|el\s+|los\s+|las\s+|doctor[a]?\s+\w+\s+\w+,?\s+en\s+calidad\s+de\s+)?"
    r"(?P<entidad>[A-ZÁÉÍÓÚÑ\s/.\-º]+?)(?=\s*(?:,|para\s+que|que\s|si\s|de\s+conformidad|en\s+(?:un|el|la|los|las)|dentro)|\n)",
    re.IGNORECASE,
)


def _extract_destinatario(texto: str) -> str:
    """Extraer la entidad destinataria de la orden. Heurística simple."""
    m = _DESTINATARIO_RE.search(texto)
    if m:
        return re.sub(r"\s+", " ", m.group("entidad")).strip(" ,.")[:200]
    return ""


def _sentido_es_concede(sentido_fallo: Optional[str]) -> bool:
    """¿El sentido del fallo es desfavorable a SED (= concede el amparo)?"""
    s = (sentido_fallo or "").strip().upper()
    if not s:
        return False
    # Favorables a SED → no requieren cumplimiento
    if s in {"NIEGA", "IMPROCEDENTE", "DESISTIDO", "RECHAZA"}:
        return False
    if "NIEGA" in s or "IMPROCED" in s or "DENIEGA" in s:
        return False
    # CONFIRMA es ambiguo: CONFIRMA de un IMPROCEDENTE es favorable; CONFIRMA de un
    # CONCEDE es desfavorable. El caller debe decidir según ambos sentidos.
    if "CONCEDE" in s or "TUTELAR" in s or "AMPAR" in s or "MODIFICA" in s:
        return True
    if "CONFIRMA" in s:
        return True  # asumimos desfavorable; el caller refina con sentido_fallo_1st
    return False


# ── API pública ─────────────────────────────────────────────────────────────

def _try_extract_from_pdf(file_path: str | Path) -> tuple[Optional[OrdenCumplimiento], str]:
    """Intenta extraer desde un PDF. Devuelve (OrdenCumplimiento|None, motivo).

    Motivos: 'ok', 'not_sentencia', 'no_resuelve', 'sin_ordinales',
             'solo_confirma', 'sin_orden_con_plazo'.
    """
    try:
        full = _read_pdf_text(file_path)
    except Exception:
        return None, "pdf_error"
    if len(full) < 1500:
        return None, "muy_corto"
    if _NOT_SENTENCIA.search(full[:3000]):
        return None, "not_sentencia"

    bloque = _find_resuelve_block(full)
    if not bloque:
        return None, "no_resuelve"

    # Detectar 2da que SOLO confirma — el plazo está en la 1ra
    if _SOLO_CONFIRMA.search(bloque[:500]):
        # Verificar que no haya ningún ordinal con verbo de orden + plazo nuevo
        ordinales_check = _split_ordinales(bloque)
        tiene_nueva_orden = any(
            _VERBO_ORDEN.search(t) and _find_plazos_en_ordinal(t)
            for _, t in ordinales_check
        )
        if not tiene_nueva_orden:
            return None, "solo_confirma"

    ordinales = _split_ordinales(bloque)
    if not ordinales:
        return None, "sin_ordinales"

    for nombre, texto in ordinales:
        if not _VERBO_ORDEN.search(texto):
            continue
        texto_pre_plazo = texto[:300].upper()
        if re.search(r"\b(IMPUGNADA?|APEL[AO]|RECURSO\s+DE|REVISAR)\b", texto_pre_plazo):
            continue
        plazos = _find_plazos_en_ordinal(texto)
        if not plazos:
            continue
        plazo = max(plazos, key=lambda p: p.dias)
        destinatario = _extract_destinatario(texto)
        return OrdenCumplimiento(
            plazo_dias=plazo.dias, plazo_raw=plazo.raw, ordinal=nombre,
            destinatario=destinatario,
            orden_texto=re.sub(r"\s+", " ", texto).strip()[:300],
            source="regex",
        ), "ok"

    return None, "sin_orden_con_plazo"


def extract_plazo_cumplimiento(
    file_path: str | Path,
    sentido_fallo_1st: Optional[str] = None,
    sentido_fallo_2nd: Optional[str] = None,
    fallback_paths: Optional[list[str | Path]] = None,
) -> Optional[OrdenCumplimiento]:
    """Extrae el plazo de cumplimiento principal de una sentencia de tutela.

    Args:
        file_path: ruta al PDF de la sentencia preferida (1ra o 2da instancia).
        sentido_fallo_1st: para filtrar; si NIEGA/IMPROCEDENTE y no hay 2da CONCEDE, skip.
        sentido_fallo_2nd: idem.
        fallback_paths: PDFs adicionales a probar si el principal no extrae (típicamente
            la sentencia 1ra cuando la 2da solo confirma sin emitir orden nueva con plazo).

    Returns:
        OrdenCumplimiento con plazo_dias, ordinal, destinatario, orden_texto.
        None si no se pudo extraer (motivos: doc no es sentencia, fallo favorable a
        SED, o no se encontró plazo).
    """
    # Filtro por sentido del fallo. Caso típicos:
    #   - 1ra=NIEGA, 2da=None             → favorable SED, skip
    #   - 1ra=IMPROCEDENTE, 2da=CONFIRMA  → favorable SED (confirma rechazo), skip
    #   - 1ra=CONCEDE, 2da=CONFIRMA       → desfavorable, vigilar
    #   - 1ra=CONCEDE, 2da=REVOCA         → revoca y favor SED, skip
    #   - 1ra=NIEGA, 2da=REVOCA           → revoca rechazo → desfavorable SED, vigilar (raro)
    s1 = (sentido_fallo_1st or "").upper().strip()
    s2 = (sentido_fallo_2nd or "").upper().strip()

    if s2:
        # Hay 2da instancia, ese sentido domina sobre 1ra
        if "REVOCA" in s2:
            # 2da revoca → resultado depende de 1ra
            if "NIEGA" in s1 or "IMPROCED" in s1:
                pass  # revocan rechazo → desfavorable SED
            else:
                return None  # revocan concede → favorable SED
        elif "CONFIRMA" in s2 or "MODIFICA" in s2:
            # 2da confirma/modifica → mantiene 1ra
            if "NIEGA" in s1 or "IMPROCED" in s1:
                return None  # confirmaron rechazo → favorable SED
            if "CONCEDE" not in s1 and "TUTELAR" not in s1 and "AMPAR" not in s1:
                return None
        elif not _sentido_es_concede(s2):
            return None
    else:
        if not _sentido_es_concede(s1):
            return None

    # Intentar primero con el PDF principal
    result, motivo = _try_extract_from_pdf(file_path)
    if result:
        return result

    # Si la 2da solo confirma o no tiene orden con plazo, intentar con los fallbacks
    # (típicamente la sentencia de 1ra instancia del mismo case).
    if motivo in {"solo_confirma", "sin_orden_con_plazo", "no_resuelve", "not_sentencia"} and fallback_paths:
        for fp in fallback_paths:
            r2, _ = _try_extract_from_pdf(fp)
            if r2:
                r2.source = "regex_fallback_1ra"
                return r2

    return None


# ════════════════════════════════════════════════════════════════════════════
# v2 — extractor de ÓRDENES (no solo plazos). Una sentencia puede tener N
# órdenes a SED; cada una con su propia temporalidad (NUMERICO/FECHA/INMEDIATO/
# PERMANENTE/CONDICIONAL/SIN_PLAZO). Toda orden es exigible vía desacato,
# tenga plazo numérico o no. Ref: Decreto 2591/1991 Art. 27, 52.
# ════════════════════════════════════════════════════════════════════════════

TIPO_NUMERICO    = "NUMERICO"      # "dentro de 5 días"
TIPO_FECHA       = "FECHA"         # "a más tardar el 27 de mayo"
TIPO_INMEDIATO   = "INMEDIATO"     # "de inmediato / sin dilación"
TIPO_PERMANENTE  = "PERMANENTE"    # "de forma continua / hasta que"
TIPO_CONDICIONAL = "CONDICIONAL"   # "en el evento en que se genere"
TIPO_SIN_PLAZO   = "SIN_PLAZO"     # orden registrada sin temporalidad explícita

DEST_SED_DIRECTA           = "SED_DIRECTA"
DEST_SED_VINCULADA         = "SED_VINCULADA"
DEST_TERCERO_SED_VINCULADA = "TERCERO_SED_VINCULADA"
DEST_SED_OTRA              = "SED_OTRA"       # SED de otro municipio/depto — informativa
DEST_EXTERNO               = "EXTERNO"        # entidad externa sin SED vinculada — se descarta

VERBO_IMPERATIVO  = "IMPERATIVO"   # ORDENAR/REQUERIR/DISPONER/CONMINAR
VERBO_EXHORTATIVO = "EXHORTATIVO"  # EXHORTAR (orden suave, solo si SED es destinataria)
VERBO_DECLARATIVO = "DECLARATIVO"  # TUTELAR/AMPARAR/CONCEDER (declara derecho)
VERBO_PROCESAL    = "PROCESAL"     # NOTIFICAR/REMITIR/LIBRAR/ARCHIVAR/DESVINCULAR
VERBO_NINGUNO     = "NINGUNO"


@dataclass
class OrdenDeCumplimiento:
    """Una orden discreta de una sentencia, exigible vía desacato."""
    ordinal_nombre: str       # PRIMERO/SEGUNDO/...
    verbo_orden: str          # ORDENAR/CONMINAR/REQUERIR/DISPONER/EXHORTAR
    verbo_tipo: str           # IMPERATIVO/EXHORTATIVO
    destinatario: str         # texto del destinatario (entidad)
    destinatario_tipo: str    # SED_DIRECTA/SED_VINCULADA/TERCERO_SED_VINCULADA/SED_OTRA
    accion_resumida: str      # primera frase imperativa, ≤200 chars
    tipo_plazo: str           # NUMERICO/FECHA/INMEDIATO/PERMANENTE/CONDICIONAL/SIN_PLAZO
    plazo_dias: Optional[int] # solo si tipo_plazo ∈ {NUMERICO, INMEDIATO}
    plazo_raw: str            # texto original que justifica el plazo (debug/audit)
    fecha_especifica: Optional[str]  # DD/MM/YYYY si tipo_plazo == FECHA
    condicion: Optional[str]  # texto de la condición si tipo_plazo == CONDICIONAL
    orden_texto: str          # primeros 400 chars del ordinal (audit)
    source: str = "regex_v2"


# ── Verbos por categoría ──────────────────────────────────────────────────

_VERBO_IMPERATIVO_RE = re.compile(
    r"\b(?:"
    r"ORDENAR|ORDENA|ORDENAR[ÁA]N?|ORD[EÉ]NESE|ORD[EÉ]NASE"
    r"|REQUERIR|REQUERIR[ÁA]N?|REQUIERA|REQUI[EÉ]R[AE]SE"
    r"|DISPONER|DISPONDR[ÁA]N?|DISP[OÓ]NGASE|DISP[OÓ]NESE"
    r"|CONMINAR|CONM[IÍ]NESE|CONM[IÍ]NASE"
    r")\b",
    re.IGNORECASE,
)

_VERBO_EXHORTATIVO_RE = re.compile(
    r"\b(?:EXHORT[AÁ]R|EXH[OÓ]RTESE|EXH[OÓ]RTASE)\b",
    re.IGNORECASE,
)

_VERBO_DECLARATIVO_RE = re.compile(
    r"\b(?:TUTELAR|AMPARAR|AMP[AÁ]RESE|CONCEDER|CONC[EÉ]DASE|PROTEGER|PROT[EÉ]JASE)\b",
    re.IGNORECASE,
)

# Verbos procesales: trámite del juez, no obligación de cumplimiento para SED.
# Buscamos en cualquier posición del ordinal, pero la clasificación final se hace
# por orden de aparición (el primer verbo encontrado gana — ver _classify_verbo).
_VERBO_PROCESAL_RE = re.compile(
    r"\b(?:"
    r"NOTIFICAR|NOTIF[IÍ]QUESE|NOTIF[IÍ]CASE"
    r"|REMITIR|REM[IÍ]TASE|REM[IÍ]TANSE"
    r"|LIBRAR|L[IÍ]BRESE|L[IÍ]BRENSE"
    r"|ARCHIVAR|ARCH[IÍ]VESE"
    r"|DESVINCULAR|DESV[IÍ]NCULESE"
    r"|T[EÉ]NGASE\s+POR"
    r"|DECLARAR\s+(?:IMPROCEDENTE|IMPR[OÓ]CEDENTE)"
    r")\b",
    re.IGNORECASE,
)


def _classify_verbo(texto_ordinal: str) -> tuple[str, str]:
    """Clasifica el ordinal por su verbo principal.

    Reglas (en este orden):
      1. Si hay IMPERATIVO/EXHORTATIVO Y no hay PROCESAL antes que él → gana el verbo de orden.
         Cubre el patrón frecuente: "Primero: CONCEDER el amparo y, en consecuencia, ORDENAR/DISPONER...".
      2. Si PROCESAL aparece antes que cualquier verbo de orden → PROCESAL.
         Cubre: "Si no fuere impugnado, remítase a la Corte... como lo ordena el Art. 31".
      3. Sin verbo de orden y sin procesal: DECLARATIVO si lo hay, NINGUNO si no.
    """
    head = texto_ordinal[:500]
    INF = float("inf")
    pos_imp = INF; m_imp = None
    pos_exh = INF; m_exh = None
    pos_proc = INF; m_proc = None
    pos_decl = INF; m_decl = None
    if (m := _VERBO_IMPERATIVO_RE.search(head)):
        pos_imp, m_imp = m.start(), m
    if (m := _VERBO_EXHORTATIVO_RE.search(head)):
        pos_exh, m_exh = m.start(), m
    if (m := _VERBO_PROCESAL_RE.search(head)):
        pos_proc, m_proc = m.start(), m
    if (m := _VERBO_DECLARATIVO_RE.search(head)):
        pos_decl, m_decl = m.start(), m

    pos_orden = min(pos_imp, pos_exh)
    if pos_orden < INF:
        if pos_proc < pos_orden:
            return VERBO_PROCESAL, m_proc.group(0).upper()
        if pos_imp <= pos_exh:
            return VERBO_IMPERATIVO, m_imp.group(0).upper()
        return VERBO_EXHORTATIVO, m_exh.group(0).upper()
    if pos_proc < INF:
        return VERBO_PROCESAL, m_proc.group(0).upper()
    if pos_decl < INF:
        return VERBO_DECLARATIVO, m_decl.group(0).upper()
    return VERBO_NINGUNO, ""


# ── Destinatario ──────────────────────────────────────────────────────────

_DEST_SED_SANTANDER_RE = re.compile(
    r"\b(?:"
    r"SECRETAR[IÍ]A\s+DE\s+EDUCACI[OÓ]N\s+(?:DEPARTAMENTAL\s+)?(?:DE\s+)?SANTANDER"
    r"|GOBERNACI[OÓ]N\s+DE\s+SANTANDER"
    r"|SECRETAR[IÍ]A\s+DE\s+EDUCACI[OÓ]N\s+DEPARTAMENTAL"
    r"|SECRETAR(?:IO|IA)\s+DE\s+EDUCACI[OÓ]N\s+(?:DEL\s+)?(?:DEPARTAMENTO\s+)?DE\s+SANTANDER"
    r"|S\.?E\.?D\.?\s+SANTANDER"
    r")\b",
    re.IGNORECASE,
)

_DEST_SED_OTRA_RE = re.compile(
    r"\b(?:"
    r"SECRETAR[IÍ]A\s+DE\s+EDUCACI[OÓ]N\s+(?:MUNICIPAL\s+)?DE\s+(?!SANTANDER\b)([A-ZÁÉÍÓÚÑ]+)"
    r")\b",
    re.IGNORECASE,
)


def _classify_destinatario(texto_ordinal: str, sed_es_accionada_en_case: bool = True) -> tuple[str, str]:
    """Detecta destinatario y lo clasifica.

    sed_es_accionada_en_case: True si SED Santander aparece como accionada/vinculada
        en el case (lo sabemos por la DB). Cuando True, una orden a un TERCERO
        (EPS, Universidad) con SED vinculada se marca TERCERO_SED_VINCULADA.

    Devuelve (destinatario_tipo, destinatario_texto). Destinatario_texto vacío
    cuando no se logra identificar.
    """
    head = texto_ordinal[:600]
    if _DEST_SED_SANTANDER_RE.search(head):
        m = _DEST_SED_SANTANDER_RE.search(head)
        return DEST_SED_DIRECTA, m.group(0).strip()
    m_otra = _DEST_SED_OTRA_RE.search(head)
    if m_otra:
        # Si menciona SED de otro municipio Y también SED Santander en cualquier parte,
        # marca SED_VINCULADA si SED Santander aparece más adelante en el texto
        if _DEST_SED_SANTANDER_RE.search(texto_ordinal):
            return DEST_SED_VINCULADA, m_otra.group(0).strip()
        return DEST_SED_OTRA, m_otra.group(0).strip()
    # Orden a tercero (EPS, Universidad, Alcaldía...) — si SED es accionada/vinculada
    # en el case general, vigilamos igual (regla operativa de Wilson)
    if sed_es_accionada_en_case:
        # Heurística: buscar entidad después del verbo "a ENTIDAD"
        m_dest = _DESTINATARIO_RE.search(texto_ordinal)
        if m_dest:
            entidad = re.sub(r"\s+", " ", m_dest.group("entidad")).strip(" ,.")[:200]
            return DEST_TERCERO_SED_VINCULADA, entidad
        return DEST_TERCERO_SED_VINCULADA, ""
    return DEST_EXTERNO, ""


# ── Tipo de plazo ─────────────────────────────────────────────────────────

_MES_NUM = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

# Plazo por FECHA absoluta: "a más tardar el día veintisiete (27) de mayo"
_PLAZO_FECHA_RE = re.compile(
    r"(?:a\s+m[aá]s\s+tardar|antes\s+del?|hasta\s+(?:el\s+d[ií]a\s+)?)"
    r"\s*(?:el\s+d[ií]a\s+)?"
    r"(?:[a-záéíóúñ\s]+?\s*\(\s*(?P<dia_num>\d{1,2})\s*\)|(?P<dia>\d{1,2}))"
    r"\s+de\s+(?P<mes>enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)"
    r"(?:\s+(?:de\s+)?(?P<anio>\d{4}|los\s+corrientes|del\s+(?:presente\s+)?a[ñn]o))?",
    re.IGNORECASE,
)

# Plazo PERMANENTE (obligación de tracto sucesivo)
_PLAZO_PERMANENTE_RE = re.compile(
    r"\b(?:"
    r"de\s+(?:forma|manera)\s+(?:permanente|continua|ininterrumpida|sostenida|indefinida)"
    r"|(?:continuar|seguir|mantener)\s+(?:prestando|brindando|garantizando|otorgando|suministrando)"
    r"|hasta\s+(?:que|tanto)\s+(?:cese|persista|culmine|termine|finalice)"
    r"|durante\s+(?:el\s+|todo\s+el\s+)?(?:tiempo|t[eé]rmino|per[íi]odo)\s+que\s+(?:dure|persista)"
    r")",
    re.IGNORECASE,
)

# Plazo CONDICIONAL (latente, se activa con un evento)
_PLAZO_CONDICIONAL_RE = re.compile(
    r"\b(?:"
    r"en\s+(?:el\s+)?(?:caso|evento)\s+(?:de\s+que|en\s+que|de\s+)"
    r"|si\s+(?:acaeciere|llegare\s+a|se\s+(?:generara|presentara|produjera|llegara|diera))"
    r"|cuando\s+(?:se\s+(?:genere|presente|produzca|d[eé])|llegue\s+a)"
    r"|si\s+a[uú]n\s+no\s+lo\s+hubiese\s+hecho"
    r")",
    re.IGNORECASE,
)


def _parse_fecha_especifica(match, fecha_fallo_str: Optional[str]) -> Optional[str]:
    """Convierte un match de _PLAZO_FECHA_RE en DD/MM/YYYY.
    Usa fecha_fallo (DD/MM/YYYY) para resolver "los corrientes" o año implícito."""
    dia = match.group("dia_num") or match.group("dia")
    if not dia:
        return None
    dia = int(dia)
    mes_nombre = (match.group("mes") or "").lower()
    mes = _MES_NUM.get(mes_nombre)
    if not mes:
        return None
    anio = match.group("anio") or ""
    if anio and anio.isdigit():
        year = int(anio)
    elif fecha_fallo_str:
        # "los corrientes" o ausente → mismo año que fecha_fallo
        try:
            year = int(fecha_fallo_str.split("/")[-1])
        except (ValueError, IndexError):
            return None
    else:
        return None
    try:
        return f"{dia:02d}/{mes:02d}/{year:04d}"
    except Exception:
        return None


def _detectar_tipo_plazo(
    texto_ordinal: str,
    fecha_fallo_str: Optional[str] = None,
) -> tuple[str, Optional[int], str, Optional[str], Optional[str]]:
    """Determina la temporalidad de la orden.

    Devuelve (tipo, plazo_dias, plazo_raw, fecha_especifica, condicion).

    Prioridad:
      1. CONDICIONAL — si toda la orden está envuelta en una condición.
      2. NUMERICO    — "dentro de 5 días" / "48 horas".
      3. FECHA       — "a más tardar el 27 de mayo".
      4. INMEDIATO   — "de inmediato / sin dilación".
      5. PERMANENTE  — "de forma continua / hasta que cese".
      6. SIN_PLAZO   — orden sin temporalidad explícita (igualmente exigible).
    """
    # 1. CONDICIONAL: si arranca con condición que envuelve toda la orden
    m_cond = _PLAZO_CONDICIONAL_RE.search(texto_ordinal[:400])
    is_condicional = False
    if m_cond:
        # Heurística: si la condición está en los primeros 200 chars y la orden
        # principal viene después, es condicional. Si la condición es una nota
        # menor ("si aún no lo hubiese hecho"), no la consideramos CONDICIONAL.
        pos = m_cond.start()
        if pos < 200 and not re.search(r"si\s+a[uú]n\s+no\s+lo", m_cond.group(0), re.IGNORECASE):
            is_condicional = True

    # 2. NUMERICO: usar el extractor de plazos numéricos existente
    plazos_num = _find_plazos_en_ordinal(texto_ordinal)
    plazos_num_pure = [p for p in plazos_num if p.unidad != "INMEDIATO"]
    if plazos_num_pure:
        plazo = max(plazos_num_pure, key=lambda p: p.dias)
        if is_condicional:
            cond_text = re.sub(r"\s+", " ", texto_ordinal[m_cond.start():m_cond.end()+150]).strip()[:200]
            return TIPO_CONDICIONAL, plazo.dias, plazo.raw, None, cond_text
        return TIPO_NUMERICO, plazo.dias, plazo.raw, None, None

    # 3. FECHA
    m_fecha = _PLAZO_FECHA_RE.search(texto_ordinal)
    if m_fecha:
        fecha_iso = _parse_fecha_especifica(m_fecha, fecha_fallo_str)
        if fecha_iso:
            # Calcular plazo_dias relativo a fecha_fallo si está disponible
            plazo_dias = None
            if fecha_fallo_str:
                try:
                    from datetime import datetime
                    ff = datetime.strptime(fecha_fallo_str, "%d/%m/%Y")
                    fl = datetime.strptime(fecha_iso, "%d/%m/%Y")
                    plazo_dias = max(1, (fl - ff).days)
                except Exception:
                    pass
            return TIPO_FECHA, plazo_dias, m_fecha.group(0).strip(), fecha_iso, None

    # 4. INMEDIATO
    plazos_inm = [p for p in plazos_num if p.unidad == "INMEDIATO"]
    if plazos_inm:
        return TIPO_INMEDIATO, 1, plazos_inm[0].raw, None, None

    # 5. PERMANENTE
    m_perm = _PLAZO_PERMANENTE_RE.search(texto_ordinal)
    if m_perm:
        return TIPO_PERMANENTE, None, m_perm.group(0).strip(), None, None

    # 6. CONDICIONAL puro (sin plazo numérico interno) — si detectamos condición fuerte
    if is_condicional:
        cond_text = re.sub(r"\s+", " ", texto_ordinal[m_cond.start():m_cond.end()+150]).strip()[:200]
        return TIPO_CONDICIONAL, None, "", None, cond_text

    # 7. SIN_PLAZO
    return TIPO_SIN_PLAZO, None, "", None, None


# ── Acción resumida ───────────────────────────────────────────────────────

_ACCION_VERBOS = re.compile(
    r"\b(?:adopte|adoptar|implemente|implementar|realice|realizar|gestione|gestionar"
    r"|expida|expedir|emita|emitir|reconozca|reconocer|garantice|garantizar"
    r"|proporcione|proporcionar|suministre|suministrar|cumpla|cumplir"
    r"|pague|pagar|reintegre|reintegrar|nombre|nombrar|traslade|trasladar"
    r"|autorice|autorizar|brinde|brindar|provea|proveer|d[eé]\s+continuidad"
    r"|construya|construir|materialice|materializar|asuma|asumir)\b",
    re.IGNORECASE,
)


def _extraer_accion_resumida(texto_ordinal: str) -> str:
    """Frase imperativa principal. Heurística: primera oración después del verbo,
    cortada en ≤200 chars."""
    # Buscar verbo de acción
    m = _ACCION_VERBOS.search(texto_ordinal)
    if not m:
        # fallback: primeras 200 chars sin saltos
        return re.sub(r"\s+", " ", texto_ordinal[:200]).strip()
    start = m.start()
    # Tomar desde el verbo hasta el siguiente punto o salto de párrafo
    seg = texto_ordinal[start:start + 400]
    # Cortar en el primer "." seguido de mayúscula/salto, o en \n\n
    m_end = re.search(r"\.\s*(?:[A-ZÁÉÍÓÚÑ]|\n)", seg)
    if m_end:
        seg = seg[:m_end.start()]
    return re.sub(r"\s+", " ", seg).strip()[:250]


# ── API v2: extract_ordenes_cumplimiento ──────────────────────────────────

def extract_ordenes_cumplimiento(
    file_path: str | Path,
    sentido_fallo_1st: Optional[str] = None,
    sentido_fallo_2nd: Optional[str] = None,
    fallback_paths: Optional[list[str | Path]] = None,
    fecha_fallo: Optional[str] = None,
    sed_es_accionada: bool = True,
) -> list[OrdenDeCumplimiento]:
    """Extrae TODAS las órdenes sustantivas de cumplimiento de una sentencia.

    Devuelve lista (puede ser vacía si la sentencia es favorable a SED o si el
    PDF no es una sentencia procesable).

    Args:
        file_path: PDF principal (1ra o 2da según preferencia del caller).
        sentido_fallo_1st/2nd: si es favorable a SED, devuelve [].
        fallback_paths: si la principal solo CONFIRMA, intenta estos.
        fecha_fallo: DD/MM/YYYY — necesario para calcular plazo_dias en plazos
            tipo FECHA ("a más tardar el 27 de mayo" → días desde fecha_fallo).
        sed_es_accionada: si True (default), órdenes a terceros (EPS, etc.) en
            el case se marcan TERCERO_SED_VINCULADA. Si False, se descartan.

    Filtros aplicados:
        - Sentencias favorables a SED → []
        - Ordinales con verbo PROCESAL solo (NOTIFICAR/REMITIR/ARCHIVAR) → skip
        - Ordinales con verbo DECLARATIVO solo (TUTELAR sin orden adyacente) → skip
        - Ordinales con verbo EXHORTATIVO a entidad que NO es SED → skip
        - Ordinales con destinatario EXTERNO sin SED vinculada → skip
    """
    # Filtro por sentido del fallo (misma lógica que la API v1)
    s1 = (sentido_fallo_1st or "").upper().strip()
    s2 = (sentido_fallo_2nd or "").upper().strip()
    if s2:
        if "REVOCA" in s2:
            if not ("NIEGA" in s1 or "IMPROCED" in s1):
                return []
        elif "CONFIRMA" in s2 or "MODIFICA" in s2:
            if "NIEGA" in s1 or "IMPROCED" in s1:
                return []
            if "CONCEDE" not in s1 and "TUTELAR" not in s1 and "AMPAR" not in s1:
                return []
        elif not _sentido_es_concede(s2):
            return []
    else:
        if not _sentido_es_concede(s1):
            return []

    ordenes = _extraer_de_pdf_v2(file_path, fecha_fallo, sed_es_accionada)

    # Si no encontró nada útil y hay fallbacks (típicamente 2da CONFIRMA), probarlos
    if not ordenes and fallback_paths:
        for fp in fallback_paths:
            ordenes_fb = _extraer_de_pdf_v2(fp, fecha_fallo, sed_es_accionada)
            if ordenes_fb:
                for o in ordenes_fb:
                    o.source = "regex_v2_fallback_1ra"
                return ordenes_fb

    return ordenes


def _extraer_de_pdf_v2(
    file_path: str | Path,
    fecha_fallo: Optional[str],
    sed_es_accionada: bool,
) -> list[OrdenDeCumplimiento]:
    """Worker: lee PDF, parte ordinales, clasifica cada uno."""
    try:
        full = _read_pdf_text(file_path)
    except Exception:
        return []
    if len(full) < 1500:
        return []
    if _NOT_SENTENCIA.search(full[:3000]):
        return []
    return _extraer_ordenes_de_texto(full, fecha_fallo, sed_es_accionada)


def _extraer_ordenes_de_texto(
    full: str,
    fecha_fallo: Optional[str],
    sed_es_accionada: bool,
    lenient_resuelve: bool = False,
) -> list[OrdenDeCumplimiento]:
    """Core de clasificación de órdenes a partir de TEXTO ya extraído.

    Separado de `_extraer_de_pdf_v2` para que el extractor focalizado (que lee
    solo las últimas páginas, con OCR si hace falta) reuse la misma lógica.

    lenient_resuelve: cuando el texto ya es solo la cola del fallo (parte
        resolutiva), permite localizar el bloque RESUELVE aunque el keyword no
        esté perfectamente aislado entre saltos de línea.
    """
    bloque = _find_resuelve_block(full)
    if not bloque and lenient_resuelve:
        bloque = _find_resuelve_block_lenient(full)
    if not bloque:
        return []
    ordinales = _split_ordinales(bloque)
    if not ordinales:
        return []

    # Detectar si la 2da solo CONFIRMA sin orden nueva (igual que v1)
    if _SOLO_CONFIRMA.search(bloque[:500]):
        tiene_nueva = any(_VERBO_IMPERATIVO_RE.search(t[:300]) for _, t in ordinales)
        if not tiene_nueva:
            return []  # caller intentará fallback con 1ra

    ordenes: list[OrdenDeCumplimiento] = []
    for nombre, texto in ordinales:
        verbo_tipo, verbo_match = _classify_verbo(texto)

        # Skip puramente procesales
        if verbo_tipo == VERBO_PROCESAL:
            continue
        # Skip declarativos puros (TUTELAR/AMPARAR) — son antesala, la orden viene en otro ordinal
        if verbo_tipo == VERBO_DECLARATIVO:
            continue
        # Skip si menciona impugnación/nulidad en los primeros 300 chars
        if re.search(r"\b(IMPUGNADA?|APEL[AO]|RECURSO\s+DE|NULIDAD)\b", texto[:300], re.IGNORECASE):
            continue

        dest_tipo, dest_texto = _classify_destinatario(texto, sed_es_accionada)
        tipo_plazo, plazo_dias, plazo_raw, fecha_esp, cond = _detectar_tipo_plazo(texto, fecha_fallo)

        # Caso de ORDEN IMPLÍCITA: el ordinal arranca con "a la SED ... que [subj] dentro/a más tardar X"
        # sin verbo imperativo explícito (frecuente en sentencias laborales / educativas).
        # Sólo si destinatario es SED Y hay plazo NUMERICO o FECHA, lo tratamos como orden.
        if verbo_tipo == VERBO_NINGUNO:
            if dest_tipo in (DEST_SED_DIRECTA, DEST_SED_VINCULADA) and tipo_plazo in (TIPO_NUMERICO, TIPO_FECHA):
                verbo_tipo = VERBO_IMPERATIVO
                verbo_match = "(IMPLÍCITO)"
            else:
                continue

        # EXHORTAR solo cuenta si la entidad exhortada es SED
        if verbo_tipo == VERBO_EXHORTATIVO and dest_tipo not in (DEST_SED_DIRECTA, DEST_SED_VINCULADA):
            continue
        # Skip externos sin SED vinculada
        if dest_tipo == DEST_EXTERNO:
            continue
        # SED_OTRA se REGISTRA con marca distintiva (no se descarta).
        # Wilson decide caso por caso si esa SED municipal nos involucra.

        accion = _extraer_accion_resumida(texto)

        ordenes.append(OrdenDeCumplimiento(
            ordinal_nombre=nombre,
            verbo_orden=verbo_match,
            verbo_tipo=verbo_tipo,
            destinatario=dest_texto,
            destinatario_tipo=dest_tipo,
            accion_resumida=accion,
            tipo_plazo=tipo_plazo,
            plazo_dias=plazo_dias,
            plazo_raw=plazo_raw,
            fecha_especifica=fecha_esp,
            condicion=cond,
            orden_texto=re.sub(r"\s+", " ", texto).strip()[:400],
        ))

    # Dedup por ordinal_nombre: si una sentencia tiene dos fragmentos con el mismo
    # numeral (PDFs mal-spliteables o texto que repite el numeral), mantener uno
    # solo — preferir el más informativo (con plazo numérico, luego con orden_texto
    # más largo).
    if ordenes:
        seen: dict[str, OrdenDeCumplimiento] = {}
        for o in ordenes:
            key = o.ordinal_nombre
            if key not in seen:
                seen[key] = o
                continue
            prev = seen[key]
            # Score: con plazo_dias > sin; texto más largo gana.
            score_o = (1 if o.plazo_dias else 0, len(o.orden_texto))
            score_prev = (1 if prev.plazo_dias else 0, len(prev.orden_texto))
            if score_o > score_prev:
                seen[key] = o
        ordenes = list(seen.values())
    return ordenes
