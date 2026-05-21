#!/usr/bin/env python3
"""Ingesta inicial v9 — desde Gmail, dirigida por el doc_librarian.

Reusa la conexión Gmail del módulo `email/gmail_monitor.py` para:
  - Autenticar
  - Listar mensajes
  - Descargar email body + adjuntos

PERO usa el bibliotecario v9 para:
  - Clasificar tipo de cada doc (16 doctypes en lugar de filename simple)
  - Extraer rad23 con sliding window CUP
  - Decidir el case del email = rad23 DOMINANTE entre email + sus adjuntos
  - Marcar como SOSPECHOSO los docs cuyo rad23 difiere del dominante

Sin `match_to_case` viejo (que tenía bugs). Sin contradicciones por construcción:
cada doc va al case dictado por su CONTENIDO, no por heurísticas frágiles.

Uso:
    python3 scripts/ingest_from_gmail_v9.py --limit 10 --dry-run
    python3 scripts/ingest_from_gmail_v9.py --limit 100
    python3 scripts/ingest_from_gmail_v9.py --apply  # todos los emails históricos
"""
from __future__ import annotations

import argparse
import base64
import logging
import re
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.settings import settings  # noqa: E402
from backend.database.database import SessionLocal  # noqa: E402
from backend.database.models import Case, Document, Email  # noqa: E402
from backend.email.gmail_monitor import (  # noqa: E402
    _get_gmail_service, _extract_body_complete, _find_attachment_parts,
    VALID_EXTENSIONS, extract_accionante, extract_forest,
    _normalize_typos, _should_ignore, _sha256_bytes,
)
from backend.v9.doc_librarian import classify, DocType  # noqa: E402
from backend.v9.regex_pass import _extract_radicado_23  # noqa: E402
from backend.v9.doc_io import DocText  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("v9.ingest")


def _norm_filename(name: str) -> str:
    """Sanitiza filename para que sea válido en disco."""
    s = re.sub(r'[<>:"/\\|?*\n\r\t]', '', name)
    s = re.sub(r'\s+', '_', s.strip())
    return s[:200]


def _norm_accionante(s: str) -> str:
    """Quita acentos, mayúsculas, sanitiza para folder name."""
    if not s:
        return "SIN_ACCIONANTE"
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r'[^A-Za-z0-9 ]', '', s).upper().strip()
    return s[:60] if s else "SIN_ACCIONANTE"


def _rad_corto_from_rad23(rad23: str) -> str:
    """rad23 = 23 dígitos puros, devuelve formato 'YYYY-NNNNN'."""
    if not rad23 or len(rad23) < 23:
        return ""
    return f"{rad23[12:16]}-{rad23[16:21]}"


@dataclass
class IngestStats:
    emails_total: int = 0
    emails_processed: int = 0
    emails_skipped: int = 0
    emails_no_rad23: int = 0
    cases_created: int = 0
    cases_reused: int = 0
    documents_added: int = 0
    documents_suspicious: int = 0
    attachments_downloaded: int = 0
    bytes_downloaded: int = 0
    errors: list = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


def _ensure_unique_folder_name(db, base_name: str) -> str:
    """Si base_name colisiona en Case.folder_name, sufija incremental (_2, _3, ...).

    Garantiza UNICIDAD por construcción. Defensa de último recurso para evitar
    IntegrityError UNIQUE constraint failed: cases.folder_name.
    """
    if not db.query(Case).filter(Case.folder_name == base_name).first():
        return base_name
    for n in range(2, 100):
        candidate = f"{base_name}_{n}"
        if not db.query(Case).filter(Case.folder_name == candidate).first():
            return candidate
    # Caso patológico (>100 cases con mismo base_name)
    import time
    return f"{base_name}_{int(time.time())}"


def _adopt_shell(db, rad23: str, accionante: str) -> Optional[Case]:
    """F1 (RC-2): adopta un shell (rad23 NULL) con el mismo rad_corto cuando llega el
    rad23 completo, en vez de crear un caso nuevo (que duplicaría al shell).

    Seguro porque: solo adopta si hay EXACTAMENTE 1 shell con ese rad_corto; y si hay
    conflación (otros casos con rad23 del mismo rad_corto pero rad21 distinto) exige que
    el accionante sea compatible (el shell no tiene rad23 → no conozco su juzgado real).
    """
    rad_corto = _rad_corto_from_rad23(rad23)
    if not rad_corto:
        return None
    rad21 = rad23[:21]
    shells = db.query(Case).filter(
        or_(Case.radicado_23_digitos.is_(None), Case.radicado_23_digitos == ""),
        Case.folder_name.like(f"{rad_corto} %"),
    ).all()
    if len(shells) != 1:
        return None
    shell = shells[0]
    # ¿cluster de conflación? otros casos con rad23 de ESTE rad_corto pero rad21 distinto.
    others = db.query(Case).filter(
        Case.folder_name.like(f"{rad_corto} %"),
        Case.radicado_23_digitos.isnot(None), Case.radicado_23_digitos != "",
    ).all()
    conflacion = any(
        re.sub(r"\D", "", c.radicado_23_digitos or "")[:21] != rad21
        for c in others if len(re.sub(r"\D", "", c.radicado_23_digitos or "")) >= 21
    )
    if conflacion:
        a = _norm_accionante(accionante)
        b = _norm_accionante(shell.accionante or "")
        if not (a and b and a == b):
            return None  # ambiguo en cluster de conflación → no adoptar
    # ADOPTAR: fijar rad23 (deja de ser shell). El folder_renamer corregirá el nombre.
    shell.radicado_23_digitos = rad23
    if accionante and (not shell.accionante or shell.accionante in ("(sin accionante)", "(sin radicado)", "(tutela origen no ingestada)")):
        shell.accionante = accionante
    db.flush()
    return shell


def _ensure_case(db, rad23: str, accionante: str, base_dir: Path) -> tuple[Case, bool]:
    """Busca Case por rad21 (rad23 sin sufijo de recurso). Si no existe, crea uno nuevo.

    Política: la misma tutela en distintas etapas procesales (1ra=00, impugnación=01,
    incidentes posteriores) tiene rad21 idéntico y rad23 que cambia el sufijo.
    Es UN solo case. Buscamos por LIKE 'rad21%' para reusar.
    """
    rad21 = rad23[:21]
    existing = db.query(Case).filter(Case.radicado_23_digitos.like(f"{rad21}%")).first()
    if existing:
        return existing, False

    # F1 (RC-2): adoptar un shell sin rad23 con el mismo rad_corto antes de crear nuevo.
    shell = _adopt_shell(db, rad23, accionante)
    if shell:
        return shell, False

    rad_corto = _rad_corto_from_rad23(rad23)
    accionante_norm = _norm_accionante(accionante)
    base = f"{rad_corto} {accionante_norm}".strip()

    # Cascada de defensa contra colisión:
    # 1. Si existe folder con mismo nombre, agregar código del juzgado
    if db.query(Case).filter(Case.folder_name == base).first():
        juzgado_code = rad23[5:11]
        base = f"{rad_corto} {juzgado_code} {accionante_norm}".strip()
    # 2. Si AÚN colisiona, sufijo incremental (_2, _3, ...)
    folder_name = _ensure_unique_folder_name(db, base)

    folder_path = base_dir / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)

    case = Case(
        radicado_23_digitos=rad23,
        accionante=accionante,
        folder_name=folder_name,
        folder_path=str(folder_path),
        processing_status="PENDIENTE",
        tipo_actuacion="TUTELA",
    )
    db.add(case)
    db.flush()
    return case, True


def _ensure_orphan_case(db, base_dir: Path) -> Case:
    """Case especial para emails sin rad23 detectable."""
    folder_name = "__SIN_RADICADO__"
    case = db.query(Case).filter(Case.folder_name == folder_name).first()
    if case:
        return case
    folder_path = base_dir / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)
    case = Case(
        radicado_23_digitos=None,
        accionante="(sin radicado)",
        folder_name=folder_name,
        folder_path=str(folder_path),
        processing_status="REVISION",
        tipo_actuacion="TUTELA",
    )
    db.add(case)
    db.flush()
    return case


# ============================================================
# DETECCIÓN DE INCIDENTE DE DESACATO
# ============================================================

_INCIDENTE_KEYWORDS = (
    "incidente desacato", "incidente de desacato",
    "abrir incidente", "apertura incidente", "aper. incidente",
    "auto desacato", "sancion desacato", "sanción desacato",
    "providencia sancion", "decide incidente",
    "requerimiento previo desacato", "requerimiento desacato",
)


def detect_incidente_email(subject: str, body: str) -> bool:
    """¿Es un email sobre incidente de desacato? Heurística por keywords."""
    text = f"{subject or ''} {(body or '')[:1000]}".lower()
    return any(kw in text for kw in _INCIDENTE_KEYWORDS)


def _extract_rad_corto(text: str) -> Optional[str]:
    """Extrae el primer rad corto YYYY-NNNNN del texto.

    Reconoce variantes: '2026-0047', '2026 - 0047', '2026-00047'.
    Devuelve siempre normalizado a 5 dígitos: '2026-00047'.
    """
    if not text:
        return None
    # Patrón: YYYY [-,–,/, espacio] NNN-NNNNN
    m = re.search(r"\b(20\d{2})\s*[-–—/]\s*(\d{3,5})\b", text)
    if m:
        year, seq = m.group(1), m.group(2).zfill(5)
        return f"{year}-{seq}"
    return None


def find_tutela_origen(db, subject: str, body: str, base_dir: Path) -> tuple[Optional[Case], Optional[str]]:
    """Busca/crea el Case de la tutela origen para un email de incidente.

    Estrategia:
    1. Extraer rad corto del SUBJECT (más fiable: el operador identifica la tutela origen).
    2. Si no aparece, intentar del body (primeras 1500 chars).
    3. Buscar Case existente cuyo folder_name comience con ese rad corto.
    4. Si NO existe (típicamente tutelas anteriores a 2026 sin carpeta), crear "shell case"
       con folder_name = '<rad_corto> INCIDENTE_HUERFANO_TUTELA_ANTIGUA' marcado para revisión.

    Returns: (case_tutela_origen, rad_corto_de_tutela_origen)
    """
    rad_corto = _extract_rad_corto(subject) or _extract_rad_corto(body[:1500] if body else "")
    if not rad_corto:
        return None, None

    # Buscar case existente con ese rad corto al inicio del folder_name
    case = db.query(Case).filter(Case.folder_name.like(f"{rad_corto} %")).first()
    if case:
        return case, rad_corto

    # No existe → crear shell case (probablemente tutela anterior a 2026)
    folder_name = f"{rad_corto} INCIDENTE_HUERFANO_TUTELA_ANTIGUA"
    folder_path = base_dir / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)
    case = Case(
        radicado_23_digitos=None,  # No tenemos el rad23 completo de la tutela origen
        accionante="(tutela origen no ingestada)",
        folder_name=folder_name,
        folder_path=str(folder_path),
        processing_status="REVISION",
        tipo_actuacion="TUTELA",
        observaciones=f"Shell case creado por ingesta v9 — solo se conoce el rad corto {rad_corto} (probable tutela pre-2026)",
    )
    db.add(case)
    db.flush()
    return case, rad_corto


# ============================================================
# CASCADA DE MATCHING v9.1 — múltiples señales (basado en email/matcher.py v8)
# ============================================================

import difflib
from sqlalchemy import or_

# Patrones relajados para extraer pistas (más permisivos que regex_pass)
_PAT_RAD_CORTO_RELAJADO = re.compile(
    r"\b(20\d{2})[\s\-–—\xa0]?0*(\d{3,5})(?!\d)"
)
_PAT_CEDULA = re.compile(r"(?i)\bc\.?c\.?\s*[:\.]?\s*N?o?\.?\s*(\d{6,10})\b")
_PAT_PERSONERO_MUNICIPIO = re.compile(
    r"(?i)\bpersoner[íi]a?\s+(?:municipal\s+)?(?:de|del)\s+(?:el\s+)?([A-Za-záéíóúñÁÉÍÓÚÑ]{3,30})"
)
# Nombres en MAYÚSCULAS (al menos 2 palabras de 3+ letras)
_PAT_NOMBRE_MAYUS = re.compile(
    r"\b([A-ZÁÉÍÓÚÑ]{3,}(?:\s+[A-ZÁÉÍÓÚÑ]{2,}){1,4})\b"
)
# Palabras que NO son nombres de persona aunque estén en mayúsculas
_NOMBRE_STOPWORDS = {
    "RESPUESTA", "REQUERIMIENTO", "URGENTE", "NOTIFICACION", "NOTIFICACIÓN",
    "OFICIO", "AUTO", "ACCION", "ACCIÓN", "TUTELA", "FALLO", "SENTENCIA",
    "INCIDENTE", "DESACATO", "IMPUGNACION", "IMPUGNACIÓN", "RV", "RE", "FW",
    "REMITE", "ADJUNTO", "ADJUNTOS", "SECRETARIA", "EDUCACION", "EDUCACIÓN",
    "SANTANDER", "GOBERNACION", "GOBERNACIÓN", "MUNICIPAL", "DEPARTAMENTAL",
    "JUZGADO", "TRIBUNAL", "CIRCUITO", "PROMISCUO", "MUNICIPIO", "ALCALDIA",
    "ALCALDÍA", "PERSONERO", "PERSONERÍA", "PERSONERIA", "DEFENSOR", "MINISTERIO",
    "INSTITUTO", "FUNDACION", "FUNDACIÓN", "CONSEJO", "CONTRA", "ANTE",
}


def _extract_rad_corto_relajado(text: str) -> Optional[str]:
    """Extrae rad corto YYYY-NNNNN. Acepta separadores variados (NBSP, espacios, sin separador)."""
    if not text:
        return None
    m = _PAT_RAD_CORTO_RELAJADO.search(text)
    if m:
        year, seq = m.group(1), m.group(2).zfill(5)
        # Validar año razonable
        if 2010 <= int(year) <= 2030:
            return f"{year}-{seq}"
    return None


def _extract_cedula(text: str) -> Optional[str]:
    """Extrae cédula del accionante (CC, c.c., etc.)."""
    if not text:
        return None
    m = _PAT_CEDULA.search(text)
    if m:
        cc = m.group(1)
        if 6 <= len(cc) <= 10:
            return cc
    return None


def _extract_personero_municipio(text: str) -> Optional[str]:
    """Extrae el municipio cuando el subject menciona 'Personero Municipal de X'."""
    if not text:
        return None
    m = _PAT_PERSONERO_MUNICIPIO.search(text)
    if m:
        muni = m.group(1).strip().upper()
        if len(muni) >= 3 and muni not in _NOMBRE_STOPWORDS:
            return muni
    return None


def _extract_nombre_propio(text: str) -> Optional[str]:
    """Extrae el primer nombre propio (2-5 palabras MAYÚSCULAS) del subject.

    Filtra stopwords típicas de subjects ('RESPUESTA', 'TUTELA', etc.)
    """
    if not text:
        return None
    # Quitar prefijos típicos
    text = re.sub(r"^(?:RV|RE|FW|FWD)\s*:\s*", "", text, flags=re.IGNORECASE)
    for m in _PAT_NOMBRE_MAYUS.finditer(text):
        candidate = m.group(1).strip()
        words = candidate.split()
        # Rechazar si TODAS las palabras son stopwords
        non_stop = [w for w in words if w not in _NOMBRE_STOPWORDS]
        if len(non_stop) >= 2:
            return " ".join(non_stop)
    return None


def _juzgado_code_from_rad23(rad23: str) -> Optional[str]:
    """Devuelve los chars 5-12 del rad23 (corp+esp+disp = código del juzgado)."""
    if not rad23 or len(rad23) < 12:
        return None
    return rad23[5:12]


# F2 (RC-3): el municipio del JUZGADO desambigua respuestas SED entre homónimos year:seq.
from backend.agent.extractors.municipios_santander import (  # noqa: E402
    MUNICIPIOS_SANTANDER, _strip_accents as _muni_strip,
)

_RE_JUZ_MUNI = re.compile(
    r"(?i)juzgado\b[^\n]{0,75}?\bde\s+([A-Za-záéíóúñÁÉÍÓÚÑ]+(?:\s+[A-Za-záéíóúñÁÉÍÓÚÑ]+){0,3})"
)


def _extract_juzgado_municipio(text: str) -> Optional[str]:
    """Extrae el municipio del despacho de un 'JUZGADO ... DE <MUNICIPIO>'.
    Valida contra los 87 municipios de Santander (probando 1-3 palabras: 'PUENTE NACIONAL',
    'SAN GIL'). Devuelve el nombre normalizado (sin acentos, MAYÚS) o None."""
    if not text:
        return None
    for m in _RE_JUZ_MUNI.finditer(text[:3000]):
        words = _muni_strip(m.group(1)).split()
        for n in range(min(3, len(words)), 0, -1):
            name = " ".join(words[:n])
            if name in MUNICIPIOS_SANTANDER:
                return name
    return None


def _case_municipio(c: Case) -> Optional[str]:
    """Municipio del juzgado de un Case: del campo `juzgado`, fallback a `ciudad`."""
    return _extract_juzgado_municipio(c.juzgado or "") or (
        _muni_strip(c.ciudad) if c.ciudad and _muni_strip(c.ciudad) in MUNICIPIOS_SANTANDER else None
    )


# === Funciones de match contra DB ===

def _match_by_rad21(db, rad21: str) -> Optional[Case]:
    return db.query(Case).filter(Case.radicado_23_digitos.like(f"{rad21}%")).first()


def _match_by_rad_corto(
    db, rad_corto: str, juzgado_code: Optional[str] = None, accionante: str = "",
    municipio: Optional[str] = None,
) -> tuple[Optional[Case], str]:
    """Busca Case por rad_corto en folder_name. Si hay >1 (homónimos year:seq de
    juzgados distintos), desambigua por municipio del juzgado (F2), código de juzgado,
    o nombre del accionante. Si NO se puede desambiguar → devuelve (None, ...) en vez de
    agarrar el primero (conflar dos expedientes distintos es peor que crear un shell).

    Returns: (case|None, method)
    """
    cases = db.query(Case).filter(Case.folder_name.like(f"{rad_corto} %")).all()
    if not cases:
        return None, "no_match"
    if len(cases) == 1:
        return cases[0], "rad_corto_unique"
    # F2 (RC-3): desambiguar por MUNICIPIO del juzgado (clave para respuestas SED que solo
    # traen rad_corto + nombran el juzgado, p.ej. "...DE PUENTE NACIONAL" → c334).
    if municipio:
        hits = [c for c in cases if _case_municipio(c) == municipio]
        if len(hits) == 1:
            return hits[0], "rad_corto+municipio"
    # Múltiples → desambiguar. 1º por código de juzgado (díg. 6-12 del rad23).
    if juzgado_code:
        jz_hits = [c for c in cases if c.radicado_23_digitos and len(c.radicado_23_digitos) >= 12
                   and c.radicado_23_digitos[5:12] == juzgado_code]
        if len(jz_hits) == 1:
            return jz_hits[0], "rad_corto+juzgado"
    # 2º por similaridad del nombre del accionante (solo entre los homónimos).
    if accionante and len(accionante) >= 6:
        import difflib as _dl
        a = accionante.upper().strip()
        scored = sorted(cases, key=lambda c: _dl.SequenceMatcher(None, a, (c.accionante or "").upper()).ratio(), reverse=True)
        r1 = _dl.SequenceMatcher(None, a, (scored[0].accionante or "").upper()).ratio()
        r2 = _dl.SequenceMatcher(None, a, (scored[1].accionante or "").upper()).ratio() if len(scored) > 1 else 0.0
        if r1 >= 0.80 and r1 - r2 >= 0.15:
            return scored[0], "rad_corto+accionante"
    # No se pudo desambiguar → no adivinar (la cascada seguirá a personería/nombre/shell).
    return None, "rad_corto_ambiguous_unresolved"


def _match_by_cedula(db, cedula: str) -> Optional[Case]:
    """Busca Case con la cédula en accionante u observaciones."""
    return db.query(Case).filter(or_(
        Case.accionante.like(f"%{cedula}%"),
        Case.observaciones.like(f"%{cedula}%"),
        Case.asunto.like(f"%{cedula}%"),
    )).first()


def _match_by_personero(db, municipio: str) -> Optional[Case]:
    """Busca Case cuyo accionante mencione 'Personero...de MUNICIPIO'."""
    cases = db.query(Case).filter(Case.accionante.ilike(f"%{municipio}%")).all()
    for c in cases:
        acc = (c.accionante or "").upper()
        if any(kw in acc for kw in ("PERSONERO", "PERSONERA", "PERSONERÍA", "PERSONERIA")):
            return c
    return None


def _match_by_nombre_fuzzy(db, nombre: str, min_ratio: float = 0.75) -> tuple[Optional[Case], float]:
    """Fuzzy match contra Case.accionante usando difflib. Retorna (case, ratio).

    Optimización: solo compara contra cases con accionante de longitud similar (±5 chars)."""
    if not nombre or len(nombre) < 6:
        return None, 0.0
    nombre_up = nombre.upper().strip()
    nombre_len = len(nombre_up)
    best_case = None
    best_ratio = 0.0
    for c in db.query(Case).all():
        acc = (c.accionante or "").upper().strip()
        if not acc or abs(len(acc) - nombre_len) > 30:
            continue
        ratio = difflib.SequenceMatcher(None, nombre_up, acc).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_case = c
    if best_ratio >= min_ratio:
        return best_case, best_ratio
    return None, best_ratio


def _match_by_thread(db, in_reply_to: str, references: str) -> Optional[Case]:
    """Busca Email parent por message_id; retorna su case_id.

    Threading RFC 5322: si este email es respuesta a uno ya procesado, hereda case.
    """
    candidates = []
    if in_reply_to:
        candidates.append(in_reply_to.strip("<>"))
    if references:
        # `references` es lista separada por espacios
        candidates.extend(r.strip("<>") for r in references.split() if r.strip("<>"))
    for ref in candidates:
        parent = db.query(Email).filter(Email.message_id == f"<{ref}>").first()
        if parent and parent.case_id:
            case = db.query(Case).filter(Case.id == parent.case_id).first()
            if case:
                return case
        # También buscar sin angle brackets
        parent = db.query(Email).filter(Email.message_id == ref).first()
        if parent and parent.case_id:
            case = db.query(Case).filter(Case.id == parent.case_id).first()
            if case:
                return case
    return None


def find_case_cascade(
    db, base_dir: Path, *,
    subject: str, body: str, sender: str,
    in_reply_to: str, references: str,
    dominant_rad: Optional[str],
    accionante_extracted: str,
) -> tuple[Case, str, bool]:
    """Cascada de matching v9.1 — 10 niveles. Returns (case, method, was_created)."""
    text = (subject or "") + " " + (body or "")[:3000]

    # 0. Threading RFC 5322
    case = _match_by_thread(db, in_reply_to, references)
    if case:
        return case, "thread", False

    # 1. rad23 dominante de adjuntos → rad21 match
    if dominant_rad:
        case = _match_by_rad21(db, dominant_rad[:21])
        if case:
            return case, "rad21_attachments", False
        # No existe → crear
        case, created = _ensure_case(db, dominant_rad, accionante_extracted, base_dir)
        return case, "ensure_case_from_attachments", created

    # 2. rad23 en subject/body con extractor relajado (NBSP)
    rad23_in_text = _extract_radicado_23(text)
    if rad23_in_text:
        case = _match_by_rad21(db, rad23_in_text[:21])
        if case:
            return case, "rad23_in_text", False
        case, created = _ensure_case(db, rad23_in_text, accionante_extracted, base_dir)
        return case, "ensure_case_from_text", created

    # 3. FOREST + sender SED
    forest = extract_forest(body or "", [])
    if forest and "santander.gov" in (sender or "").lower():
        case = db.query(Case).filter(Case.radicado_forest == forest).first()
        if case:
            return case, "forest+sender_sed", False

    # 4. Cédula del accionante
    cedula = _extract_cedula(text)
    if cedula:
        case = _match_by_cedula(db, cedula)
        if case:
            return case, f"cedula({cedula})", False

    # 5. rad_corto en subject/body. Si hay homónimos year:seq se desambigua por nombre
    #    del accionante; si no se puede, NO se agarra el primero (sigue la cascada).
    rad_corto = _extract_rad_corto_relajado(subject) or _extract_rad_corto_relajado(body[:1500] if body else "")
    if rad_corto:
        muni = _extract_juzgado_municipio(text)  # municipio del juzgado nombrado en el correo
        case, method = _match_by_rad_corto(
            db, rad_corto, juzgado_code=None, accionante=accionante_extracted, municipio=muni)
        if case:
            return case, f"rad_corto:{method}", False

    # 6. Personería municipal
    municipio = _extract_personero_municipio(text)
    if municipio:
        case = _match_by_personero(db, municipio)
        if case:
            return case, f"personero({municipio})", False

    # 7. Nombre accionante (fuzzy)
    nombre = _extract_nombre_propio(subject)
    if nombre:
        case, ratio = _match_by_nombre_fuzzy(db, nombre, min_ratio=0.75)
        if case:
            return case, f"nombre_fuzzy({ratio:.2f}):{nombre[:30]}", False

    # 8. Si tenemos rad_corto, crear shell case con rad_corto + nombre extraído
    if rad_corto:
        from backend.email.gmail_monitor import extract_accionante as _extract_acc
        acc = accionante_extracted or _extract_acc(subject, body) or "(sin accionante)"
        base = f"{rad_corto} {_norm_accionante(acc)}".strip()
        # Cascada defensiva: si colisiona, intentar con sufijo incremental
        folder_name = _ensure_unique_folder_name(db, base)
        folder_path = base_dir / folder_name
        folder_path.mkdir(parents=True, exist_ok=True)
        case = Case(
            radicado_23_digitos=None,
            accionante=acc,
            folder_name=folder_name,
            folder_path=str(folder_path),
            processing_status="REVISION",
            tipo_actuacion="TUTELA",
            observaciones=f"Shell case por ingesta v9.1 — solo rad corto {rad_corto} disponible",
        )
        db.add(case)
        db.flush()
        return case, "shell_with_rad_corto", True

    # 9. Final: __SIN_RADICADO__
    return _ensure_orphan_case(db, base_dir), "orphan", False


def process_email(service, msg_summary: dict, db, base_dir: Path,
                  stats: IngestStats, dry_run: bool = False) -> Optional[dict]:
    """Procesa 1 email completo. Retorna info para log."""
    msg_id = msg_summary["id"]
    try:
        msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    except Exception as e:
        stats.errors.append(f"fetch {msg_id}: {e}")
        return None

    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    subject = _normalize_typos(headers.get("subject", ""))
    sender = headers.get("from", "")
    date_str = headers.get("date", "")

    if _should_ignore(subject, sender):
        stats.emails_skipped += 1
        return {"action": "skipped", "subject": subject[:60], "reason": "filter"}

    body = _extract_body_complete(msg.get("payload", {}))
    att_parts = _find_attachment_parts(msg.get("payload", {}))
    att_filenames = [a["filename"] for a in att_parts]

    # ----- Descargar adjuntos a un staging temporal para clasificarlos -----
    staging = base_dir / "__staging__" / msg_id
    if not dry_run:
        staging.mkdir(parents=True, exist_ok=True)

    staged_files: list[tuple[Path, bytes]] = []
    for att in att_parts:
        fname = _norm_filename(att["filename"])
        ext = Path(fname).suffix.lower()
        if ext not in VALID_EXTENSIONS:
            continue
        try:
            att_data = service.users().messages().attachments().get(
                userId="me", messageId=msg_id, id=att["attachmentId"]
            ).execute()
            data = base64.urlsafe_b64decode(att_data["data"])
            staged_path = staging / fname
            counter = 1
            while staged_path.exists():
                staged_path = staging / f"{Path(fname).stem}_{counter}{ext}"
                counter += 1
            if not dry_run:
                staged_path.write_bytes(data)
            staged_files.append((staged_path, data))
            stats.attachments_downloaded += 1
            stats.bytes_downloaded += len(data)
        except Exception as e:
            stats.errors.append(f"attach {fname}: {e}")

    # ----- Extraer rad23 del email + cada adjunto -----
    rad_candidates: list[str] = []

    # Del body del email
    rad_in_body = _extract_radicado_23(body or "")
    if rad_in_body:
        rad_candidates.append(rad_in_body)

    # De cada adjunto leído (texto)
    attachment_classifications = []
    for sp, data in staged_files:
        text = _read_text_from_bytes(sp, data)
        if text:
            rad = _extract_radicado_23(text)
            if rad:
                rad_candidates.append(rad)
            doc = DocText(path=str(sp), filename=sp.name, text=text, method="staged")
            cls = classify(doc)
            attachment_classifications.append((sp, data, text, rad, cls))
        else:
            attachment_classifications.append((sp, data, "", None, None))

    # ----- Decidir rad23 dominante -----
    if rad_candidates:
        counts = Counter(rad_candidates)
        dominant_rad = counts.most_common(1)[0][0]
    else:
        dominant_rad = None

    # ----- Detectar si es email de INCIDENTE DE DESACATO -----
    is_incidente = detect_incidente_email(subject, body)
    incidente_rad_corto: Optional[str] = None
    target_subfolder: Optional[Path] = None

    rad_in_subject = _extract_radicado_23(subject)
    incidente_suffix: Optional[str] = None
    if is_incidente and rad_in_subject:
        incidente_suffix = rad_in_subject[-2:]

    # ----- CASCADA DE MATCHING v9.1 (10 niveles) -----
    in_reply_to = headers.get("in-reply-to", "")
    references = headers.get("references", "")
    accionante_extracted = extract_accionante(subject, body) or ""

    case, match_method, was_created = find_case_cascade(
        db, base_dir,
        subject=subject, body=body, sender=sender,
        in_reply_to=in_reply_to, references=references,
        dominant_rad=dominant_rad,
        accionante_extracted=accionante_extracted,
    )
    if was_created:
        stats.cases_created += 1
    else:
        stats.cases_reused += 1
    if match_method == "orphan":
        stats.emails_no_rad23 += 1

    # Tracking del método de match para diagnóstico
    if not hasattr(stats, 'match_methods'):
        stats.match_methods = Counter()
    stats.match_methods[match_method] += 1

    # Si es incidente, crear sub-carpeta con sufijo de recurso (si lo conocemos)
    if is_incidente and case and case.folder_name != "__SIN_RADICADO__":
        # Determinar rad_corto del incidente
        if dominant_rad:
            rc = _rad_corto_from_rad23(dominant_rad)
        elif rad_in_subject:
            rc = _rad_corto_from_rad23(rad_in_subject)
        else:
            # Extraer rad_corto del subject como último recurso
            rc = _extract_rad_corto_relajado(subject) or _extract_rad_corto_relajado(body[:500] if body else "")

        if rc:
            incidente_rad_corto = f"{rc}-{incidente_suffix}" if incidente_suffix else rc
            target_subfolder = Path(case.folder_path) / f"incidente_{incidente_rad_corto}"
            target_subfolder.mkdir(parents=True, exist_ok=True)

    folder_path = target_subfolder if target_subfolder else Path(case.folder_path)

    # ----- Crear Email en DB -----
    try:
        email_dt = parsedate_to_datetime(date_str)
    except Exception:
        email_dt = datetime.utcnow()
    msg_id_header = headers.get("message-id", msg_id)

    email_obj = db.query(Email).filter(Email.message_id == msg_id_header).first()
    if not email_obj:
        email_obj = Email(
            message_id=msg_id_header,
            subject=subject[:500],
            sender=sender[:200],
            date_received=email_dt,
            body_preview=body[:1000] if body else "",
            case_id=case.id,
            attachments=[{"filename": f.name} for f, _ in staged_files],
            status="ASIGNADO" if dominant_rad else "AMBIGUO",
        )
        db.add(email_obj)
        db.flush()

    # ----- Guardar email .md y registrarlo como Document -----
    # Garantizar UNICIDAD por msg_id para evitar colisiones entre emails distintos
    # con mismo subject + misma fecha (común en reenvíos y respuestas duplicadas).
    msg_id_short = msg_id[:8] if msg_id else "noid"
    md_filename = f"Email_{email_dt.strftime('%Y%m%d')}_{_norm_filename(subject)[:42]}_{msg_id_short}.md"
    md_path = folder_path / md_filename
    md_content = (
        f"# {subject}\n\n"
        f"**De:** {sender}\n"
        f"**Fecha:** {date_str}\n"
        f"**Caso:** {case.folder_name}\n\n---\n\n{body}\n"
    )
    if att_filenames:
        md_content += "\n## Adjuntos\n" + "\n".join(f"- {f}" for f in att_filenames)
    if not dry_run and not md_path.exists():
        md_path.write_text(md_content, encoding="utf-8")

    if not db.query(Document).filter(Document.case_id == case.id, Document.filename == md_filename).first():
        db.add(Document(
            case_id=case.id, filename=md_filename, file_path=str(md_path),
            doc_type="EMAIL_JUDICIAL", file_size=len(md_content),
            file_hash=_sha256_bytes(md_content.encode("utf-8")),
            email_id=email_obj.id, email_message_id=msg_id_header,
            verificacion="OK",
            incidente_radicado=incidente_rad_corto,
        ))
        stats.documents_added += 1

    # ----- Mover adjuntos del staging al folder del case + crear Documents -----
    for sp, data, text, rad, cls in attachment_classifications:
        target = folder_path / sp.name
        counter = 1
        while target.exists() and target != sp:
            target = folder_path / f"{Path(sp.name).stem}_{counter}{sp.suffix}"
            counter += 1

        if not dry_run:
            try:
                if sp.exists():
                    sp.rename(target)
            except OSError:
                # cross-device: copy + unlink
                target.write_bytes(data)
                if sp.exists():
                    sp.unlink()

        # Decidir verificacion. Comparar rad21 (sin los 2 dígitos finales del
        # consecutivo de recursos): la misma tutela en 1ra y 2da instancia tiene
        # rad21 idéntico pero rad23 cambia el sufijo (00 → 01). Eso NO es FOREIGN.
        if rad and dominant_rad and rad[:21] != dominant_rad[:21]:
            verif = "SOSPECHOSO"
            stats.documents_suspicious += 1
        elif not rad and not dominant_rad:
            verif = "REVISAR"
        else:
            verif = "OK"

        doc_type_value = cls.doc_type.value if cls else "DESCONOCIDO"

        # F4: dedup byte-idéntico dentro del caso (evita el "split" de adjuntos repetidos).
        file_hash = _sha256_bytes(data)
        if db.query(Document).filter(Document.case_id == case.id, Document.file_hash == file_hash).first():
            continue

        if not db.query(Document).filter(Document.case_id == case.id, Document.filename == target.name).first():
            db.add(Document(
                case_id=case.id, filename=target.name, file_path=str(target),
                doc_type=doc_type_value, file_size=len(data),
                file_hash=file_hash,
                email_id=email_obj.id, email_message_id=msg_id_header,
                verificacion=verif,
                extracted_text=(text[:30000] if text else ""),
                incidente_radicado=incidente_rad_corto,
            ))
            stats.documents_added += 1

    # Limpiar staging
    if not dry_run:
        try:
            staging.rmdir()
        except Exception:
            pass

    return {
        "action": "ingested",
        "subject": subject[:60],
        "rad23": dominant_rad or "(sin rad)",
        "case_id": case.id,
        "case_folder": case.folder_name,
        "documents": stats.documents_added,
    }


def _read_text_from_bytes(path: Path, data: bytes) -> str:
    """Extrae texto de PDF/DOCX desde bytes en disco."""
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            import pymupdf
            doc = pymupdf.open(stream=data, filetype="pdf")
            text = ''.join(doc[i].get_text() for i in range(min(doc.page_count, 30)))
            doc.close()
            return text
        if ext == ".docx":
            from backend.extraction.docx_extractor import extract_docx
            # extract_docx requiere path; ya está escrito en staging
            r = extract_docx(str(path))
            return getattr(r, "text", "") if not isinstance(r, tuple) else r[0]
        if ext == ".doc":
            from backend.extraction.doc_extractor import extract_doc
            r = extract_doc(str(path))
            return getattr(r, "text", "") if not isinstance(r, tuple) else r[0]
    except Exception as e:
        logger.warning(f"read_text {path.name}: {e}")
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="Máximo emails a procesar (0 = todos)")
    ap.add_argument("--query", type=str, default=None, help="Query Gmail (default: GMAIL_HISTORICAL_QUERY)")
    ap.add_argument("--dry-run", action="store_true", help="No descarga ni escribe a DB")
    args = ap.parse_args()

    base_dir = Path(settings.BASE_DIR)
    if not base_dir.exists():
        base_dir.mkdir(parents=True, exist_ok=True)
    print(f"BASE_DIR: {base_dir}")

    print("Conectando a Gmail...")
    service = _get_gmail_service()
    if service is None:
        print("ERROR: no pude conectar a Gmail. Revisa GMAIL_USER y credenciales en .env")
        return 1

    query = args.query or os.getenv("GMAIL_HISTORICAL_QUERY", "in:inbox")
    print(f"Query: {query}")

    print("Listando mensajes (cronológicamente: más antiguo → más reciente)...")
    # IMPORTANTE: Gmail API devuelve mensajes del MÁS RECIENTE al MÁS ANTIGUO.
    # Para procesar emails en orden cronológico real (admisión → respuesta →
    # sentencia → impugnación → incidente), debemos invertir el orden.
    # Esto evita que un incidente llegue antes que su tutela origen.
    # Listamos TODOS los IDs primero (rápido, solo IDs no metadatos) y luego invertimos.
    all_msgs = []
    page_token = None
    while True:
        resp = service.users().messages().list(
            userId="me", q=query, pageToken=page_token, maxResults=500,
        ).execute()
        all_msgs.extend(resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    # Invertir: ahora el primero es el MÁS ANTIGUO
    all_msgs.reverse()
    # Aplicar limit AHORA, después de invertir → procesamos los N más antiguos
    msgs = all_msgs[:args.limit] if args.limit else all_msgs
    print(f"Total mensajes en inbox: {len(all_msgs)}")
    print(f"Procesando los {len(msgs)} MÁS ANTIGUOS primero")
    if args.dry_run:
        print("MODO DRY-RUN — no se descargarán archivos ni se escribirá a DB")

    stats = IngestStats(emails_total=len(msgs))
    db = SessionLocal()
    t0 = time.perf_counter()

    try:
        for i, m in enumerate(msgs):
            if i % 25 == 0:
                elapsed = time.perf_counter() - t0
                print(f"  [{i:>4}/{len(msgs)}] elapsed={elapsed:.0f}s | "
                      f"cases={stats.cases_created} docs={stats.documents_added} "
                      f"susp={stats.documents_suspicious} sin_rad={stats.emails_no_rad23}",
                      flush=True)
            try:
                res = process_email(service, m, db, base_dir, stats, dry_run=args.dry_run)
                if not args.dry_run:
                    db.commit()  # Commit por email — un error no pierde los anteriores
                if res:
                    stats.emails_processed += 1
            except Exception as e:
                if not args.dry_run:
                    db.rollback()
                stats.errors.append(f"email#{i} ({m.get('id','?')[:10]}): {str(e)[:200]}")
                logger.warning(f"Error en email #{i}: {str(e)[:200]}")
    finally:
        db.close()

    elapsed = time.perf_counter() - t0
    print()
    print("=" * 70)
    print(f"INGESTA TERMINADA en {elapsed:.1f}s ({elapsed/max(stats.emails_processed,1):.2f}s/email)")
    print("=" * 70)
    print(f"Emails total:           {stats.emails_total}")
    print(f"Emails procesados:      {stats.emails_processed}")
    print(f"Emails ignorados:       {stats.emails_skipped}")
    print(f"Emails sin rad23:       {stats.emails_no_rad23}")
    print(f"Cases creados:          {stats.cases_created}")
    print(f"Cases reusados:         {stats.cases_reused}")
    print(f"Adjuntos descargados:   {stats.attachments_downloaded}")
    print(f"MB descargados:         {stats.bytes_downloaded / 1024 / 1024:.1f}")
    print(f"Documents creados:      {stats.documents_added}")
    print(f"Docs SOSPECHOSOS:       {stats.documents_suspicious}")
    print(f"Errores:                {len(stats.errors)}")
    if stats.errors[:3]:
        for e in stats.errors[:3]:
            print(f"  · {e}")
    if hasattr(stats, 'match_methods') and stats.match_methods:
        print(f"\nMétodos de match (cascada v9.1):")
        for m, n in stats.match_methods.most_common():
            print(f"  {m:<35} {n:>4}")
    return 0


if __name__ == "__main__":
    import os
    sys.exit(main())
