"""Dominio JUZGADO del motor v9 — extraído de field_extractor.py (de-sobreingeniería F6).

Juzgado de 1ra y 2da instancia (campo estructural). Fuente canónica: remitente/destinatario
de los emails de la Rama Judicial (cendoj). field_extractor.py re-exporta los símbolos
públicos (extract_juzgado_for_case, extract_juzgado_2nd_for_case, _clean_juzgado).
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from backend.database.models import Case, Document, Email
from backend.v9.extractors._shared import _read_doc_text, _fold

logger = logging.getLogger("tutelas.v9.extractors.juzgado")


# ============================================================
# JUZGADO  (campo 8 — estructural; 1ra y 2da instancia)
# ============================================================
#
# El juzgado aparece en todo doc oficial del despacho. La fuente CANÓNICA es el
# remitente/destinatario de los emails de la Rama Judicial: las cuentas de
# cendoj.ramajudicial.gov.co / notificacionesrj.gov.co se llaman, p.ej.:
#   "Juzgado 04 Civil Municipal - Santander - Girón <j04cmpalgiron@cendoj...>"
#   "Juzgado 03 Laboral Circuito - Santander - Barrancabermeja <...>"
#   "Notificaciones Secretaría Sala Civil Familia - Santander - Bucaramanga <...>"
# → de ahí salen número, especialidad, NIVEL (Municipal/Circuito) y municipio.
#
# Dos slots:
#   - juzgado     → 1ra instancia (el que lleva la tutela; en tutelas contra la
#                   SED departamental, por reparto, casi siempre es un Juez
#                   Municipal del lugar de los hechos → nivel MUNICIPAL).
#   - juzgado_2nd → 2da instancia (solo si hubo impugnación) → nivel CIRCUITO o
#                   TRIBUNAL. Si no se puede extraer explícito, se DERIVA con el
#                   mapa judicial canónico (`backend/cognition/legal_schema.py`).

# Remitente/destinatario Rama Judicial: "<nombre> - Santander - <municipio> <email@(cendoj|notificacionesrj)>"
_RE_RJ_SENDER = re.compile(
    r"(?i)\b(?P<nombre>(?:juzgado|tribunal|notificaciones)[^<>\n]{3,70}?)\s*[-–]\s*santander\s*[-–]\s*"
    r"(?P<muni>[^<>\n]{2,40}?)\s*<[^>\n]*@(?:cendoj\.ramajudicial|notificacionesrj|ramajudicial)\.gov\.co>"
)
# Fallback: "JUZGADO ..." / "TRIBUNAL ..." dentro del cuerpo de un doc (header/sello).
_RE_JUZGADO_RAW = re.compile(r"(?i)\b(juzgad[oa]\s+[^\n]{4,95})")
_RE_TRIBUNAL_RAW = re.compile(r"(?i)\b(tribunal\s+(?:superior|administrativo|contencioso)[^\n]{0,80})")
# Donde "termina" el nombre del juzgado en texto libre (a partir de aquí es basura).
_JUZGADO_STOP = re.compile(
    r"(?i)\b(?:acta\b|reparto\b|radicaci|radicad|expediente\b|accionant|accionad|"
    r"demandant|demandad|se[ñn]or\b|se[ñn]ora\b|doctor\b|doctora\b|asunto\b|ref\b|"
    r"referencia\b|oficio\b|n[uú]mero\b|n[°º]\b|nro\b|fecha\b|d[ií]a\b|me\s+permito|"
    r"corre[ol]?\b|e-?mail\b|tel[eé]?f?\w*\b|celular\b|carrera\b|calle\b|c[oó]digo\b|piso\b|"
    r"buen\s+d[ií]a|cordial|atentamente|avoca\b|avoqu|admite\b|adm[ií]t|conoce\b|"
    r"profiri|profer|emiti|dentro\s+de|mediante\b|notific|para\s+reparto|"
    r"sala\s+de\s+decisi|de\s+conformidad|conforme\s+a|sobre\s+la\b|en\s+raz[óo]n|"
    r"al\s+confirmar|por\s+considerar|de\s+este\s+distrito|de\s+esta\s+ciudad|"
    r"veinti\w+|trein\w+|cuaren\w+|cincuen\w+|sesen\w+|seten\w+|"
    r"ochen\w+|noven\w+|actuando\b|quien\b|en\s+su\b|el\s+cual\b|la\s+cual\b)"
)
# Salas válidas de un Tribunal Superior (para no capturar texto de más).
_RE_SALA = re.compile(
    r"(?i)\bsala\s+(civil[\s\-]*familia[\s\-]*laboral|civil[\s\-]*familia|civil|penal|laboral|familia|[úu]nica|mixta)\b"
)
_JUZGADO_KEY_TOKENS = re.compile(
    r"(?i)\b(?:municipal|del\s+circuito|circuito|civil|penal|laboral|administrativ[oa]|"
    r"promiscu[oa]|familia|peque[ñn]as\s+causas|ejecuci[oó]n|oralidad|garant[íi]as|adolescentes|sala)\b"
)


def _juzgado_nivel(name: str) -> str:
    """'TRIBUNAL' | 'CIRCUITO' | 'MUNICIPAL' | 'OTRO' a partir del nombre."""
    t = _fold(name)
    if "tribunal" in t or re.search(r"\bsala\b", t):
        return "TRIBUNAL"
    if "circuito" in t:
        return "CIRCUITO"
    if "municipal" in t or "pequenas causas" in t:
        return "MUNICIPAL"
    return "OTRO"


def _norm_muni_titlecase(m: str) -> str:
    """'san vicente de chucurí' → 'San Vicente de Chucurí' (sin tocar tildes)."""
    small = {"de", "del", "la", "las", "los", "y"}
    parts = re.sub(r"\s+", " ", m).strip().split(" ")
    out = []
    for i, p in enumerate(parts):
        out.append(p if (i and p.lower() in small) else (p[:1].upper() + p[1:].lower()))
    return " ".join(out)


def _juzgado_from_rj_sender(line: str) -> Optional[str]:
    """Parsea una línea de remitente/destinatario de la Rama Judicial.
    'Juzgado 04 Civil Municipal - Santander - Girón <j04...@cendoj...>'
    → 'JUZGADO 04 CIVIL MUNICIPAL DE GIRÓN (SANTANDER)'.
    'Notificaciones Secretaría Sala Civil Familia - Santander - Bucaramanga <...>'
    → 'TRIBUNAL SUPERIOR DEL DISTRITO JUDICIAL DE BUCARAMANGA - SALA CIVIL FAMILIA'.
    """
    m = _RE_RJ_SENDER.search(line)
    if not m:
        return None
    nombre = re.sub(r"\s+", " ", m.group("nombre")).strip(" -–")
    muni = _norm_muni_titlecase(m.group("muni"))
    nombre_low = _fold(nombre)
    if "sala" in nombre_low and not nombre_low.startswith("juzgado"):
        # Secretaría de una Sala de Tribunal Superior
        ms = _RE_SALA.search(nombre)
        sala = re.sub(r"\s+", " ", ms.group(1)).strip().upper().replace("  ", " ") if ms else ""
        sala = re.sub(r"\s*-\s*", " ", sala)
        distrito = "BUCARAMANGA" if _fold(muni) == "bucaramanga" else ("SAN GIL" if "gil" in _fold(muni) else muni.upper())
        base = f"TRIBUNAL SUPERIOR DEL DISTRITO JUDICIAL DE {distrito}"
        return f"{base} - SALA {sala}" if sala else base
    if nombre_low.startswith("tribunal"):
        nu = nombre.upper()
        return nu if _fold(muni) in nombre_low else f"{nu} ({muni.upper()})"
    # Juzgado normal
    return f"{nombre.upper()} DE {muni.upper()} (SANTANDER)"


def _clean_juzgado(raw: str) -> Optional[str]:
    """Limpia un candidato de juzgado extraído de texto libre (header/sello).
    Devuelve MAYÚSCULAS, recortado al final del municipio Santander si aparece,
    o None si no parece válido."""
    if not raw:
        return None
    v = re.sub(r"[\s\n\r]+", " ", raw).strip()
    m = _JUZGADO_STOP.search(v)
    if m and m.start() > 8:
        v = v[:m.start()].strip()
    v = v.rstrip(" ,.;:-–—").strip()
    try:
        from backend.cognition.legal_schema import MUNICIPIOS_SANTANDER as _MUNIS
    except Exception:
        _MUNIS = set()
    v_fold_up = _fold(v).upper()
    best_end = -1
    for muni in sorted(_MUNIS, key=len, reverse=True):
        idx = v_fold_up.find(" " + muni)
        if idx >= 0:
            end = idx + 1 + len(muni)
            nxt = v_fold_up[end:end + 1]
            if nxt in ("", " ", ",", ".", ";", ":"):
                if best_end == -1 or end < best_end:
                    best_end = end
    if best_end > 0:
        kept = v[:best_end].rstrip(" ,.;")
        rest = v[best_end:].lstrip(" ,")
        if rest[:9].upper().startswith("SANTANDER"):
            kept = kept + " " + rest.split()[0].rstrip(",.;")
        v = kept
    v = re.sub(r"\s+", " ", v).strip(" ,.;:-–—").upper()
    if not (10 <= len(v) <= 90):
        return None
    if not (v.startswith("JUZGADO") or v.startswith("TRIBUNAL")):
        return None
    if not _JUZGADO_KEY_TOKENS.search(v):
        return None
    return v


def _rj_sender_candidates(db: Session, case_id: int) -> list[str]:
    """Todos los juzgados normalizados que aparecen como remitente/destinatario
    Rama Judicial (cendoj/notificacionesrj) en el case — la fuente más limpia.

    Escanea CUALQUIER doc (no solo EMAIL_JUDICIAL/EMAIL_INTERNO) + el `sender` de los
    emails: el remitente RJ suele venir embebido en un PDF de demanda/auto forwarded
    o en el header del email, no solo en los .md (gap que dejaba juzgados incompletos
    en c411/c369/c219/… — fix 2026-06-02). El ranking del caller (MUNICIPAL>CIRCUITO)
    resuelve los casos con varios remitentes (p.ej. 1ra inst. municipal vs 2da circuito)."""
    out: list[str] = []
    blobs: list[str] = []
    for d in db.query(Document).filter(Document.case_id == case_id).all():
        t = d.extracted_text if d.extracted_text else _read_doc_text(d)
        if t:
            blobs.append(t[:8000])  # cota: el remitente va en el encabezado
    for e in db.query(Email).filter(Email.case_id == case_id).all():
        if e.sender:
            blobs.append(e.sender)
    for t in blobs:
        for m in _RE_RJ_SENDER.finditer(t):
            j = _juzgado_from_rj_sender(m.group(0))
            if j and j not in out:
                out.append(j)
    return out


def _juzgado_candidates_from_text(text: str) -> list[str]:
    """Nombres de juzgado/tribunal limpios que aparecen en un texto libre."""
    if not text:
        return []
    out: list[str] = []
    for pat in (_RE_TRIBUNAL_RAW, _RE_JUZGADO_RAW):
        for m in pat.finditer(text):
            c = _clean_juzgado(m.group(1))
            if c and c not in out:
                out.append(c)
    return out


_JUZGADO_2ND_DOCTYPES = ["SENTENCIA_2DA", "AUTO_2DA", "AUTO_CONCEDE_IMPUGNACION", "IMPUGNACION"]


def extract_juzgado_for_case(db: Session, case: Case) -> Optional[str]:
    """Extrae el juzgado de 1ra instancia (el que lleva la tutela).

    Reúne candidatos de dos fuentes y ordena por (nivel, fuente, longitud):
      - remitente/destinatario Rama Judicial (cendoj/notificacionesrj) — fuente
        más limpia y canónica (`source=0`).
      - header/sello de AUTO_ADMISORIO / SENTENCIA_1RA / NOTIFICACION / OFICIO
        (`source=1..6`).
    Nivel MUNICIPAL gana sobre CIRCUITO/TRIBUNAL (la 1ra instancia de una tutela
    contra la SED departamental casi siempre es un Juez Municipal del lugar de
    los hechos).
    """
    cands: list[tuple[int, str]] = []  # (source_rank, name)  — menor source_rank = mejor fuente

    # Fuente 0: remitente Rama Judicial (limpio, formato estándar "JUZGADO NN ...")
    for j in _rj_sender_candidates(db, case.id):
        cands.append((0, j))

    # Fuentes 1..6: texto de docs oficiales del despacho (header/sello)
    src_map = {"AUTO_ADMISORIO": 1, "SENTENCIA_1RA": 2, "NOTIFICACION": 3,
               "NOTIFICACION_FALLO": 4, "OFICIO_CUMPLIMIENTO": 5, "RESPUESTA": 6}
    for dt, src in src_map.items():
        for d in db.query(Document).filter(Document.case_id == case.id, Document.doc_type == dt).all():
            text = d.extracted_text or ""
            if not text:
                continue
            for c in _juzgado_candidates_from_text(text[:2800]):
                cands.append((src, c))

    if not cands:
        return None

    def sort_key(item: tuple[int, str]):
        src, name = item
        rank = {"MUNICIPAL": 0, "CIRCUITO": 1, "TRIBUNAL": 2, "OTRO": 3}[_juzgado_nivel(name)]
        return (rank, src, len(name))

    cands.sort(key=sort_key)
    raw = cands[0][1]
    # 2026-06-10: pasar el ganador por _clean_juzgado ANTES de normalizar — algunos
    # candidatos llegan con cola basura del header ("…DE IBAGUÉ Corre[o]", "…DE
    # SANTANDER Referencia", c543/c549 de la ingesta). Si el limpiador lo rechaza
    # (forma rara pero real), se conserva el raw para no perder dato.
    raw = _clean_juzgado(raw) or raw
    # 1B: normalizar a forma canónica (número → escrito, sin paréntesis depto)
    from backend.v9.catalog_resolve import normalize_juzgado
    return normalize_juzgado(raw)


def extract_juzgado_2nd_for_case(db: Session, case: Case, juzgado_1st: Optional[str]) -> tuple[Optional[str], str]:
    """Extrae (o deriva) el juzgado de 2da instancia. Solo si hubo impugnación
    (`impugnacion == 'SI'` o existe un doc de 2da instancia).

    Returns: (valor, fuente) — fuente ∈ {"regex", "derivado", "none"}.
    """
    has_2nd_doc = (
        db.query(Document)
        .filter(Document.case_id == case.id, Document.doc_type.in_(_JUZGADO_2ND_DOCTYPES))
        .first()
        is not None
    )
    impugno = (getattr(case, "impugnacion", None) or "").upper() == "SI"
    if not (has_2nd_doc or impugno):
        return None, "none"

    j1_fold = _fold(juzgado_1st) if juzgado_1st else ""

    # M5 2026-06-11: el avocamiento real exige doc de 2ª (SENTENCIA_2DA/AUTO_2DA).
    # Con solo impugnacion=SI, el remitente CIRCUITO suele ser la REMISIÓN por
    # reparto ("remítase al Juzgado X") y el cuadro curado deja juzgado_2nd vacío
    # hasta que la 2ª avoque — 3 'alucinaciones' en el golden (c406/c408/c420).
    has_avoc_doc = (
        db.query(Document)
        .filter(Document.case_id == case.id, Document.doc_type.in_(("SENTENCIA_2DA", "AUTO_2DA")))
        .first() is not None
    )
    if not has_avoc_doc:
        return None, "none"  # sin avocamiento documentado → vacío honesto (semántica del cuadro)
    # 1) remitente Rama Judicial de nivel CIRCUITO/TRIBUNAL, distinto al de 1ra
    rj = _rj_sender_candidates(db, case.id)
    rj_2nd = [j for j in rj if _juzgado_nivel(j) in ("CIRCUITO", "TRIBUNAL") and _fold(j) != j1_fold]
    if rj_2nd and has_avoc_doc:
        rj_2nd.sort(key=lambda j: (0 if _juzgado_nivel(j) == "TRIBUNAL" else 1, len(j)))
        from backend.v9.catalog_resolve import normalize_juzgado
        return normalize_juzgado(rj_2nd[0]), "regex"

    # 2) extracción explícita en docs de 2da instancia
    cands: list[str] = []
    for dt in _JUZGADO_2ND_DOCTYPES:
        for d in db.query(Document).filter(Document.case_id == case.id, Document.doc_type == dt).all():
            text = d.extracted_text or ""
            if not text:
                continue
            for c in _juzgado_candidates_from_text(text[:3500]):
                if _fold(c) != j1_fold and _juzgado_nivel(c) in ("CIRCUITO", "TRIBUNAL"):
                    cands.append(c)
    if cands:
        cands.sort(key=lambda c: (0 if _juzgado_nivel(c) == "TRIBUNAL" else 1, len(c)))
        from backend.v9.catalog_resolve import normalize_juzgado
        return normalize_juzgado(cands[0]), "regex"

    # 3) derivación con el mapa judicial canónico
    if juzgado_1st:
        try:
            from backend.cognition.legal_schema import derivar_juzgado_segunda
            ciudad = getattr(case, "ciudad", None)
            der = derivar_juzgado_segunda(juzgado_1st, municipio_hechos=ciudad)
            if der and der.juzgado_2nd:
                jl = der.juzgado_2nd.lower()
                if "no determin" not in jl and "no identificad" not in jl:
                    val = der.juzgado_2nd
                    if der.sala and der.sala.lower() not in jl:
                        val = f"{val} - Sala {der.sala}"
                    return val.upper() + " (DERIVADO)", "derivado"
        except Exception as e:
            logger.warning("derivar_juzgado_segunda falló: %s", str(e)[:200])
    return None, "none"


