"""Dominio ACCIONADOS + VINCULADOS del motor v9 — extraído de field_extractor.py (F6).

Lista de entidades demandadas y vinculadas (normalización canónica SED/Gobernación).
field_extractor.py re-exporta los públicos (extract_accionados_for_case,
extract_vinculados_for_case, _normalize_entity_list, _canon_entity,
_looks_like_accionado_value — estos 3 últimos los importa v9_test_standalone).
"""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy.orm import Session

from backend.database.models import Case, Document
from backend.v9.extractors._shared import _read_doc_text


# ============================================================
# ACCIONADOS + VINCULADOS
# ============================================================

# Formas canónicas de las entidades de la SED (para normalizar)
_CANON_GOBERNACION = "GOBERNACIÓN DE SANTANDER"
_CANON_SECRETARIA = "SECRETARÍA DE EDUCACIÓN DEL DEPARTAMENTO DE SANTANDER"

# Label "Accionado(s): ENTIDAD [- ENTIDAD ...]" — captura el valor de la línea de la
# etiqueta + líneas de continuación INDENTADAS (algunos autos listan una entidad por
# línea). Se detiene al ver una nueva etiqueta "Palabra:".
_PAT_ACCIONADO_LABEL = re.compile(
    r"(?im)^[ \t]*Accionad[oa]s?(?:\s*\(s\))?[ \t]*[:\.]+[ \t]*"
    r"("
    r"[^\r\n]{0,400}"
    r"(?:\n[ \t]+(?![A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\s*[:\.])[^\r\n]{1,250}){0,8}"
    r")"
)
# Palabras que identifican una entidad (pública / privada / educativa). Sirve como
# guarda para aceptar el valor de la etiqueta "Accionado:" y para validar fragmentos.
_ENTITY_WORD_RE = re.compile(
    r"(?i)\b(?:GOBERNACI[ÓO]N|GOBIERNO|DEPARTAMENTO|MUNICIPIO|ALCALD[ÍI]A|"
    r"SECRETAR[ÍI]A|MINISTERIO|DIRECCI[ÓO]N\s+(?:DE|GENERAL|TERRITORIAL)|"
    r"SUBDIRECCI[ÓO]N|UNIDAD\s+(?:ADMINISTRATIVA|DE)|AGENCIA|INSTITUTO|INSTITUCI[ÓO]N|"
    r"COLEGIO|ESCUELA|LICEO|UNIVERSIDAD|CENTRO\s+EDUCATIVO|JARD[ÍI]N\s+INFANTIL|"
    r"FUNDACI[ÓO]N|CORPORACI[ÓO]N|ASOCIACI[ÓO]N|COOPERATIVA|CAJA\b|FONDO\b|EMPRESA|"
    r"HOSPITAL|CL[ÍI]NICA|E\.?S\.?E\.?\b|ESE\b|E\.?P\.?S\.?\b|EPS\b|A\.?R\.?L\.?\b|"
    r"ARL\b|A\.?F\.?P\.?\b|AFP\b|FOMAG|FIDUPREVISORA|PORVENIR|PROTECCI[ÓO]N\s+S|"
    r"COLFONDOS|COLPENSIONES|PERSONER[ÍI]A|FISCAL[ÍI]A|PROCURADUR[ÍI]A|DEFENSOR[ÍI]A|"
    r"CONTRALOR[ÍI]A|REGISTRADUR[ÍI]A|CONSEJO\b|TRIBUNAL|JUZGADO|NACI[ÓO]N\b|RECTOR|"
    r"SENA\b|ICBF|SIMAT|CNSC|COMISAR[ÍI]A|NOTAR[ÍI]A|S\.?A\.?S?\.?\b|LTDA|EICE|"
    r"E\.?I\.?C\.?E\.?|S\.?A\.?S\.?\b|ENTIDAD|UAE\b|UAESP|ANSPE)\b"
)
# "en contra de [ENTIDAD]" — entidades reconocibles por keyword inicial
_ENTITY_KW = (
    r"GOBERNACI[ÓO]N|MUNICIPIO|ALCALD[ÍI]A|SECRETAR[ÍI]A|MINISTERIO|"
    r"INSTITUCI[ÓO]N\s+EDUCATIVA|INSTITUTO|COLEGIO|ESCUELA|LICEO|UNIVERSIDAD|"
    r"E\.?S\.?E\.?|ESE\b|EPS|HOSPITAL|FUNDACI[ÓO]N|PERSONER[ÍI]A|FISCAL[ÍI]A|"
    r"DEPARTAMENTO|CONSEJO|UAE|RECTOR\w*|FONDO|PORVENIR|COLPENSIONES"
)
_PAT_EN_CONTRA_ENTITY = re.compile(
    rf"(?i)\b(?:en\s+contra\s+de(?:l)?|contra\s+(?:el\s+|la\s+|los\s+|las\s+|del\s+)?)\s*"
    rf"((?:LA\s+|EL\s+)?(?:{_ENTITY_KW})[A-ZÁÉÍÓÚÑ\s,\-–.0-9]{{3,180}}?)"
    rf"(?=\s+(?:procurando|por\s+(?:considerar|cuanto|la|el|haber|no)|para\s+(?:que|la|el)|"
    rf"toda\s+vez|y\s+(?:de\s+)?oficio|en\s+procura|solicitando|al\s+considerar|\.|\bquien\b))"
)
# Vinculación: "se ordena/dispone la vinculación de..." / "se vincula a..." / "vincúlese a..."
_PAT_VINCULACION = re.compile(
    r"(?i)(?:se\s+(?:ordena\s+(?:la\s+)?|dispone\s+(?:la\s+)?)?vinculaci[óo]n\s+(?:de\s+)?(?:oficio(?:sa)?\s+)?(?:al?\s+|a\s+l[aoes]+\s+|del?\s+)?"
    r"|se\s+vincula(?:n)?\s+(?:de\s+oficio\s+)?(?:al?\s+|a\s+l[aoes]+\s+)?(?:tr[áa]mite\s+tutelar\s+a;?\s*|presente\s+(?:tr[áa]mite|asunto)\s+a\s+)?"
    r"|vinc[úu]lese\s+(?:de\s+oficio\s+)?(?:al?\s+|a\s+l[aoes]+\s+)?"
    # M2 2026-06-11 (bench: 33/60 golden con el VINCULAR a la vista sin capturar):
    # infinitivo dispositivo del RESUELVE ("SEGUNDO: VINCULAR al MINISTERIO…",
    # "VINCULAR a este trámite a la GOBERNACIÓN…") y pasado narrativo ("vinculó al MEN").
    r"|vincular\s+(?:de\s+oficio\s+)?(?:a\s+(?:este|la\s+presente)\s+(?:tr[áa]mite|acci[óo]n|actuaci[óo]n|litis)\s+)?(?:al?\s+|a\s+l[aoes]+\s+)?"
    r"|vincul[óo]\s+(?:de\s+oficio\s+)?(?:al?\s+|a\s+l[aoes]+\s+)?)"
    r"([A-ZÁÉÍÓÚÑ][^\.]{8,400}?)(?=\s*(?:\.|,?\s*toda\s+vez|por\s+cuanto|quienes|para\s+que|en\s+atenci[óo]n|a\s+fin\s+(?:de|que)|debiendo|;\s*y\b))"
)


# Separadores entre entidades dentro del campo accionados: salto de línea, " - ",
# " | ", " · ", ";", " + ", "  y otros". (NO partimos por coma sola: rompería nombres
# como "SECRETARÍA DE EDUCACIÓN, CULTURA Y DEPORTE".)
_ENTITY_SPLIT_RE = re.compile(
    r"(?:[\r\n]+|\s+[-–—|·•]\s+|\s*;\s*|\s+\+\s+|\s+y\s+otr[oa]s?\b\s*)", re.IGNORECASE
)
# Placeholders que NO son una entidad real.
_ACC_NON_VALUE_RE = re.compile(
    r"(?i)^\s*(?:ningun[oa]s?|n\.?\s*a\.?|no\s+aplica|sin\s+(?:accionad|determin)|"
    r"-+|\.+|s/?d|x+|por\s+determinar)\s*$"
)


# Cláusulas que cuelgan del nombre de la entidad pero no son parte de él
# ("DEPARTAMENTO DE SANTANDER, REPRESENTADO LEGALMENTE POR JUVENAL DÍAZ MATEUS, O QUIEN…").
_ENTITY_TAIL_CLAUSE_RE = re.compile(
    r"(?i)[,;]?\s*(?:representad[oa]s?\b|en\s+cabeza\s+de\b|a\s+trav[ée]s\s+de\b|"
    r"por\s+(?:conducto|intermedio)\s+de\b|en\s+la\s+persona\s+de\b|en\s+su\s+calidad\s+de\b|"
    r"qui[eé]n(?:es)?\s+(?:haga|hagan)\b|o\s+qui[eé]n\b|representante\s+legal\b|"
    r"identificad[oa]\b|con\s+(?:c\.?c\.?|nit)\b).*$"
)


def _canon_entity(s: str) -> str:
    """Normaliza UNA entidad. Gobernación / Secretaría de Educación departamental de
    Santander → forma canónica; cualquier otra (IE, municipio, EPS, fondo, secretaría
    municipal, ministerio…) se conserva tal cual, limpia y en mayúsculas."""
    u = re.sub(r"\s+", " ", s or "").strip().strip(",.;:·-–—()[]\"'").upper()
    u = _ENTITY_TAIL_CLAUSE_RE.sub("", u).strip().strip(",.;:·-–—").strip()
    if not u or len(u) < 3:
        return ""
    # Gobernación de Santander (también "DEPARTAMENTO/DEPARTAMENTAL DE SANTANDER" — misma
    # persona jurídica, o un fragmento de "Secretaría de Educación Departamental de Santander")
    if re.search(r"\bGOBERNACI[ÓO]N\b", u) or re.fullmatch(r"(?:EL\s+)?DEPARTAMENT(?:O|AL)\s+DE\s+SANTANDER\.?", u):
        return _CANON_GOBERNACION
    # Secretaría de Educación — ¿la DEPARTAMENTAL de Santander, o una municipal/nacional/otra?
    if re.search(r"SECRETAR[ÍI]A\s+(?:DEPARTAMENTAL\s+)?DE\s+EDUCA[CS]I?[ÓO]?N?\b", u):
        es_municipal = bool(re.search(r"\bMUNICIPAL\b", u))
        es_nacional = bool(re.search(r"\bNACIONAL\b", u))
        # ¿menciona un lugar que NO es Santander? (p.ej. "DE GIRÓN", "DE BARRANCABERMEJA")
        otro_lugar = bool(
            re.search(r"\bDE\s+(?!SANTANDER\b|EDUCA|LA\b|EL\b|LOS\b)[A-ZÁÉÍÓÚÑ]{4,}", u)
            and not re.search(r"\bSANTANDER\b", u)
        )
        if not (es_municipal or es_nacional or otro_lugar):
            return _CANON_SECRETARIA
        return re.sub(r"^(?:LA|EL)\s+", "", u).strip()[:180]
    # Otra entidad: quitar artículo inicial
    u = re.sub(r"^(?:LA|EL|LOS|LAS|UNA?)\s+", "", u).strip()
    return u[:180]


def _looks_like_accionado_value(raw: str) -> bool:
    """¿El texto tras la etiqueta 'Accionado:' parece una entidad (o lista de
    entidades) y no un placeholder / basura de OCR?"""
    if not raw:
        return False
    v = re.sub(r"\s+", " ", raw).strip()
    if len(v) < 4 or len(v) > 500 or _ACC_NON_VALUE_RE.match(v):
        return False
    # Debe tener alguna palabra-entidad reconocible (o ser GOB/SecEdu, ya cubiertos por
    # _ENTITY_WORD_RE vía GOBERNACI/SECRETAR), o al menos un bloque de 4+ mayúsculas.
    return bool(_ENTITY_WORD_RE.search(v) or re.search(r"[A-ZÁÉÍÓÚÑ]{4,}", v))


_CANON_ENTITIES = {_CANON_GOBERNACION, _CANON_SECRETARIA}


def _normalize_entity_list(raw: str) -> str:
    """Normaliza la lista de accionados PRESERVANDO TODAS las entidades listadas.
    (Antes se descartaban las que no fueran GOB/SecEdu, dejando 'accionados' incompleto
    — DeepSeek lo señaló en ~191 casos: Porvenir SA, Ministerio de Educación, IE, etc.)"""
    pieces = [p for p in _ENTITY_SPLIT_RE.split(raw or "") if p and p.strip()]
    if not pieces:
        pieces = [raw or ""]
    out: list[str] = []
    dropped: list[str] = []
    for p in pieces:
        c = _canon_entity(p)
        if not c or c in out:
            continue
        # Si hay >1 fragmento, descartar los que no parecen una entidad (suelen ser el
        # nombre del representante legal o ruido de OCR colado tras un " - ").
        if len(pieces) > 1 and c not in _CANON_ENTITIES and not _ENTITY_WORD_RE.search(c):
            dropped.append(c)
            continue
        out.append(c)
    if not out and dropped:  # todos quedaron descartados → mejor devolver algo
        out = [dropped[0]]
    if out:
        return " - ".join(out)
    return _canon_entity(raw or "")[:200]


def extract_accionados_for_case(db: Session, case: Case) -> Optional[str]:
    """Extrae los accionados. Estrategia:
      1. Si el auto admisorio dice ACCIONADO: explícito → usarlo (puede ser IE,
         municipio, Gobernación, Secretaría). Normaliza GOB/SEC a forma canónica.
      2. "en contra de [ENTIDAD]" en cualquier doc.
      3. Default: GOBERNACIÓN + SECRETARÍA DE EDUCACIÓN — porque las tutelas que
         gestiona la SED son SIEMPRE contra ellos (lo confirmó el usuario), salvo
         que el auto especifique otra entidad principal (caso: la SED es solo vinculada).

    Default aplica a cualquier case con rad23 (= tutela válida).
    """
    # Texto de los autos admisorios primero, luego cualquier doc
    autos = db.query(Document).filter(Document.case_id == case.id, Document.doc_type == "AUTO_ADMISORIO").all()
    for d in autos:
        text = d.extracted_text or ""
        if not text or len(text) < 150:
            continue
        head = text[:4000]
        # 1. Label ACCIONADO: (puede listar varias entidades, en una o varias líneas)
        m = _PAT_ACCIONADO_LABEL.search(head)
        if m:
            raw = m.group(1).strip()
            if _looks_like_accionado_value(raw):
                return _normalize_entity_list(raw)
        # 2. "en contra de [ENTIDAD]"
        m = _PAT_EN_CONTRA_ENTITY.search(head)
        if m:
            return _normalize_entity_list(m.group(1))

    # Sin auto admisorio claro → buscar "en contra de" en cualquier doc
    for d in db.query(Document).filter(Document.case_id == case.id).all():
        text = _read_doc_text(d)
        if not text or len(text) < 150:
            continue
        m = _PAT_EN_CONTRA_ENTITY.search(text[:4000])
        if m:
            return _normalize_entity_list(m.group(1))
        m = _PAT_ACCIONADO_LABEL.search(text[:4000])
        if m:
            raw = m.group(1).strip()
            if _looks_like_accionado_value(raw):
                return _normalize_entity_list(raw)

    # 3. Default — toda tutela gestionada por la SED es contra GOB+SEC
    if case.radicado_23_digitos:  # es una tutela válida
        return f"{_CANON_GOBERNACION} - {_CANON_SECRETARIA}"
    return None


# Preámbulo de vinculación a recortar: el extractor (regex/LLM) suele capturar el
# verbo + conectores antes de la 1ra entidad ("VINCULAR la presente acción a la
# SECRETARÍA…", "trámite tutelar a; FUNDACIÓN…", "de manera oficiosa a…"). Se
# recorta hasta el inicio de la entidad real. 2026-06-01.
_RE_VINC_LEAD = re.compile(
    r"(?i)^(?:\s*[-:;,]\s*)*"
    r"(?:(?:la|el|los|las|al|a|de|del|en|por|y|este|esta|presente|tr[áa]mite|tutelar|"
    r"tutela|demanda|asunto|actuaci[óo]n|acci[óo]n|accionar|litis|resguardo|"
    r"constitucional|manera|oficios[ao]|oficiosamente|pasiva|calidad|accionad[oa]s|intermedio|sus|"
    r"representantes|legales|adem[áa]s|oficio|orden[ae]se|v[íi]ncul\w*|cont[ée]stese|"
    r"p[óo]ngase|conocimiento|se|se[ñn]or|director|los?|las?|siguientes?)\b[\s.,;:•·-]*)+"
)


def _clean_vinculados_lead(v: str) -> str:
    """Recorta el preámbulo de vinculación. Devuelve "" si no queda entidad."""
    s = (v or "").strip()
    s = _RE_VINC_LEAD.sub("", s).strip(" .,;:-")
    return s if len(s) >= 4 else ""


def extract_vinculados_for_case(db: Session, case: Case) -> Optional[str]:
    """Extrae los vinculados del cuerpo del auto admisorio (frases 'se vincula a...').

    M2 2026-06-11: + PDF_AUTO_ADMISORIO (legacy por-filename — la query lo excluía y
    perdía el auto entero, 14/60 golden) y ventana 5000→9000 (el VINCULAR del RESUELVE
    suele caer pasada la pág. 2 en autos largos, 4/60)."""
    autos = db.query(Document).filter(
        Document.case_id == case.id,
        Document.doc_type.in_(("AUTO_ADMISORIO", "PDF_AUTO_ADMISORIO")),
    ).all()
    for d in autos:
        text = d.extracted_text or ""
        if not text or len(text) < 150:
            continue
        head = text[:9000]
        m = _PAT_VINCULACION.search(head)
        if m:
            raw = m.group(1)
            v = re.sub(r"[\n\r]+", " ", raw)
            v = re.sub(r"\s+", " ", v).strip().rstrip(",.;")
            # Cortar antes de cláusulas de cierre
            v = re.split(r"(?i)\b(?:toda\s+vez|por\s+cuanto|quienes|para\s+que|en\s+atenci[óo]n|a\s+fin\s+(?:de|que)|al\s+considerar)\b", v)[0].strip().rstrip(",.;")
            v = _clean_vinculados_lead(v)  # recortar preámbulo "VINCULAR a la …"
            if 8 <= len(v) <= 300:
                return v[:250]
    return None


