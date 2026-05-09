"""
Re-ingesta determinística (sin LLM) — Fase A+B+C del plan embudo.

Para cada caso con processing_status='PENDIENTE', llena los campos del
cuadro usando regex/lookup directos sobre docs físicos.

Fase A: identidad (rad23, accionante, juzgado, ciudad) desde Auto Avoca
Fase B: regex sobre Sentencia, Carta-Respuesta, Auto Incidente, Auto Impugnación
Fase C: parser EMAIL_MD para CC del abogado contratista

NO usa LLM. Los campos textuales (asunto, derecho_vulnerado, pretensiones,
observaciones) se quedan vacíos para Fase D posterior.

Uso:
  .venv/bin/python3 scripts/deterministic_reingest.py [--limit N]
"""
from __future__ import annotations
import argparse
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf
from sqlalchemy.orm import Session
from backend.database.database import SessionLocal
from backend.database.models import Case, Document
from backend.agent.extractors.municipios_santander import MUNICIPIOS_SANTANDER

# ─── Patrones ─────────────────────────────────────────────────────────

RE_RAD23 = re.compile(r'(?<!\d)((?:\d[\s./\-]?){22}\d)(?!\d)')

# Auto Avoca/Admisorio
AUTO_AVOCA_FNAME = [
    'auto avoca', 'auto admisorio', 'autoavoca', 'autoadmisorio',
    'auto-avoca', 'auto-admisorio', 'admisor', 'admite tut', 'admitase',
    'obedezcase', 'autoobedezcase', 'autoadmite', 'auto admite',
    'autoadmiteacciontutela',
]
AUTO_AVOCA_CONTENT = [
    'AVOCA EL CONOCIMIENTO', 'AVOCAR EL CONOCIMIENTO', 'AVOCA CONOCIMIENTO',
    'ADMITE LA TUTELA', 'ADMÍTASE LA ACCIÓN', 'ADMITASE LA ACCION',
]

# Sentencia 1ra
FALLO_1RA_FNAME = ['fallo1ra','fallotutela','sentencia1ra','fallodetutela',
                    'sentenciatutela','fallo de tutela','sentencia de tutela',
                    'fallo tutela','falloprimerainst']

# Sentencia 2da
FALLO_2DA_FNAME = ['fallo2da','sentencia2da','sentenciasegunda','segundainstancia',
                    'fallosegundainstancia','fallo2dainstancia']

# Auto Impugnación
IMPUG_FNAME = ['impugnacion','ampliaimpugnacion','escritoimpugnacion','impugna']

# Auto Incidente
INCID_FNAME = ['autoabreincidente','autoincidente','incidentedesacato','aperturaincidente']

# Carta-Respuesta DOCX FOREST
RESP_DOCX_FNAME = ['respuesta','contestacion','forest']

# ─── Utilidades de extracción ─────────────────────────────────────────

def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn")

def extract_pdf_pages(path: Path, first=None, last=None) -> tuple[str, int]:
    """Devuelve (text, total_pages)."""
    try:
        doc = pymupdf.open(str(path))
        n = doc.page_count
        if first is None and last is None:
            indices = range(n)
        else:
            fp = first or 0
            lp = last or 0
            if n <= fp + lp:
                indices = range(n)
            else:
                indices = list(range(fp)) + list(range(n - lp, n))
        text = "\n".join(doc[i].get_text() for i in indices)
        doc.close()
        return text, n
    except Exception:
        return "", 0

def normalize_rad23(s: str) -> str | None:
    digits = re.sub(r'\D', '', s)
    return digits if len(digits) == 23 else None

def is_anchor(filename: str, text: str, hints_fname: list, hints_content: list = None, max_pages: int = 8, total: int = 0) -> bool:
    fn = filename.lower()
    if total and total > max_pages:
        return False
    if any(h in fn for h in hints_fname):
        return True
    if hints_content and text:
        upper = text.upper()
        if any(h in upper for h in hints_content):
            return True
    return False

# ─── Extractores específicos por campo ────────────────────────────────

# Patrón de fechas en español: "veintisiete (27) de abril de dos mil veintiséis (2026)" o "27 de abril de 2026"
RE_FECHA_LARGA = re.compile(
    r'(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+de\s+(?:dos mil\s+\w+\s*\(?(\d{4})\)?|\(?(\d{4})\)?)',
    re.I,
)
RE_FECHA_NUM = re.compile(r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})')
MES_NUM = {"enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,"julio":7,
           "agosto":8,"septiembre":9,"octubre":10,"noviembre":11,"diciembre":12}

def extract_fecha(text: str) -> str | None:
    """Devuelve fecha 'YYYY-MM-DD' del primer match en el texto."""
    if not text: return None
    m = RE_FECHA_LARGA.search(text)
    if m:
        d = int(m.group(1))
        mes = m.group(2).lower()
        y = int(m.group(3) or m.group(4))
        if mes in MES_NUM and 1900 <= y <= 2100 and 1 <= d <= 31:
            return f"{y:04d}-{MES_NUM[mes]:02d}-{d:02d}"
    m = RE_FECHA_NUM.search(text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= d <= 31 and 1 <= mo <= 12 and 1900 <= y <= 2100:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    return None

# Juzgado: requerir que tras "JUZGADO ..." venga "DE <CIUDAD>" o que el patrón comience al inicio de línea
RE_JUZGADO_LINE = re.compile(
    r'(?:^|\n)\s*'
    r'(JUZGADO\s+(?:PRIMERO|SEGUNDO|TERCERO|CUARTO|QUINTO|SEXTO|S[ÉE]PTIMO|S[EÉ]PTIMO|OCTAVO|NOVENO|D[ÉE]CIMO|UND[ÉE]CIMO|DUOD[ÉE]CIMO|D[ÉE]CIMO\s+\w+|D[ÉE]CIMO\w*|\d{1,3}|\d+°)'
    r'\s+(?:CIVIL|PENAL|LABORAL|DE\s+FAMILIA|ADMINISTRATIVO|PROMISCUO|DE\s+EJECUCI[ÓO]N)'
    r'(?:\s+(?:MUNICIPAL|DEL\s+CIRCUITO(?:\s+DE\s+EJECUCI[ÓO]N(?:\s+DE\s+SENTENCIAS)?)?|DE\s+EJECUCI[ÓO]N|CON\s+FUNCI[ÓO]N\s+DE\s+CONOCIMIENTO|DE\s+PEQUE[NÑ]AS\s+CAUSAS|DE\s+ORALIDAD))?'
    r'\s+(?:DE\s+|EN\s+)?([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ\s\.]{3,50}?))'
    r'(?:\s*[\.\n,;]|\s+\(|\s*$)',
    re.M,
)

def extract_juzgado_y_ciudad(text: str) -> tuple[str | None, str | None]:
    """Del Auto Avoca o Sentencia, extrae juzgado completo y ciudad. Validar contra municipios."""
    if not text: return None, None
    # Intento 1: regex anclada a inicio de línea
    for m in RE_JUZGADO_LINE.finditer(text[:6000]):
        juz = ' '.join(m.group(1).split()).rstrip('.,;:').strip()
        if len(juz) > 150: continue
        # Validar municipio en el juzgado
        upper = strip_accents(juz).upper()
        for muni in sorted(MUNICIPIOS_SANTANDER, key=len, reverse=True):
            if f' {muni}' in upper or upper.endswith(f' {muni}') or upper.endswith(muni):
                return juz, muni.title()
    # Intento 2: línea con "JUZGADO" + municipio Santander
    for line in text[:5000].splitlines():
        line = line.strip()
        if 'JUZGADO' not in line.upper(): continue
        if len(line) < 15 or len(line) > 200: continue
        upper = strip_accents(line).upper()
        for muni in sorted(MUNICIPIOS_SANTANDER, key=len, reverse=True):
            if muni in upper:
                # Limpiar línea: tomar desde "JUZGADO" hasta municipio + offset
                idx = upper.find('JUZGADO')
                end_idx = upper.find(muni) + len(muni)
                clean = line[idx:idx + end_idx - upper.find('JUZGADO') + 5]
                clean = clean.strip().rstrip('.,;:').strip()
                if 15 < len(clean) < 150:
                    return clean, muni.title()
    return None, None

# Accionante
RE_ACCIONANTE = [
    re.compile(r'ACCIONANTE\s*[:\-]?\s*\n?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s\.]+?)(?:\n|ACCIONAD|CONTRA|VINCULAD|ACCI[ÓO]N|RAD)', re.I),
    re.compile(r'(?:tutela|acci[óo]n)\s+(?:presentada|instaurada|interpuesta)\s+por(?:\s+(?:el|la|los|las|el\s+se[ñn]or|la\s+se[ñn]ora))?\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s\.]{6,80}?)(?:[,.\n]|\s+act|\s+en\s+contra|\s+contra)', re.I),
    re.compile(r'TUTELA\s+INSTAURADA\s+POR\s+(?:EL\s+)?(?:SE[ÑN]OR(?:A)?\s+)?([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s\.]+?)(?:\n|\s+CONTRA|\s+EN\s+CONTRA|\s+ACTUANDO)', re.I),
    re.compile(r'ADMITIR\s+la\s+acci[óo]n\s+de\s+tutela\s+(?:instaurada|presentada)\s+(?:por\s+)?(?:el|la|los|las)?\s*(?:se[ñn]or(?:a|es)?\s+)?([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s\.]+?)(?:[,.\n]|\s+contra|\s+en\s+contra|\s+actuando)', re.I),
]

_ACC_PREFIX_TRIM = re.compile(
    r'^(?:el|la|los|las|el\s+se[ñn]or|la\s+se[ñn]ora|los\s+se[ñn]ores|las\s+se[ñn]oras|'
    r'se[ñn]or(?:a|es|as)?|por\s+(?:el|la|los|las)?\s*(?:se[ñn]or(?:a|es|as)?)?|'
    r'sr\.?|sra\.?)\s+',
    re.I,
)
_ACC_INVALID_TOKENS = {
    'JUZGADO','RADICADO','ACCIONANTE','ACCIONADO','VINCULADO','GOBERNACI[OÓ]N',
    'SECRETAR[IÍ]A','MINISTERIO','TUTELA','RESPUESTA','RADICACI[OÓ]N','CONTESTACI[OÓ]N',
}

_ACC_STOP_WORDS = re.compile(
    r'\s+(?:es|son|act[uú]a|act[uú]an|actuando|mayor|menor|dado\s+que|por\s+cuanto|'
    r'qui[eé]n|quien(?:es)?|en\s+su\s+calidad|en\s+nombre|en\s+representaci[óo]n|'
    r'identificad[oa]|identificad[oa]s|del?\s+\w+\s+a[nñ]os|cc?\s+\d|'
    r'c[eé]dula|nuip|RC|TI|tarjeta|en\s+ejercicio|por\s+intermedio|mediante|'
    r'a\s+trav[eé]s|y\s+otros?|y\s+otras?|presentar?|interpus|allega)\b',
    re.I,
)

def _clean_accionante(raw: str) -> str | None:
    s = ' '.join(raw.split()).strip(' ,.;:')
    # Limpiar prefijos
    while True:
        new = _ACC_PREFIX_TRIM.sub('', s).strip()
        if new == s: break
        s = new
    s = s.strip(' ,.;:')
    # Cortar al primer stop-word del español jurídico
    m = _ACC_STOP_WORDS.search(s)
    if m:
        s = s[:m.start()].strip(' ,.;:')
    # Cortar en coma si tiene 2+ comas (probable lista compleja)
    if s.count(',') >= 1:
        s = s.split(',')[0].strip()
    if len(s) < 5 or len(s) > 100: return None
    upper = strip_accents(s).upper()
    for inv in _ACC_INVALID_TOKENS:
        if inv in upper:
            return None
    words = s.split()
    if len(words) < 2 or len(words) > 10: return None
    return s

def extract_accionante(text: str) -> str | None:
    if not text: return None
    snippet = text[:5000]
    for pat in RE_ACCIONANTE:
        m = pat.search(snippet)
        if m:
            cand = _clean_accionante(m.group(1))
            if cand:
                return cand
    return None

# Sentido fallo: múltiples patrones (con tolerancia a tipografía espaciada)
RE_LETRAS_ESPACIADAS = re.compile(r'\b([A-ZÁÉÍÓÚÑ])(?:\s+([A-ZÁÉÍÓÚÑ])){2,}\b')

def normalize_spaced_letters(text: str) -> str:
    """Colapsa palabras con letras espaciadas (R E S U E L V E → RESUELVE)."""
    def join_letters(m):
        s = m.group(0)
        # Tomar solo letras y unirlas
        letters = re.findall(r'[A-ZÁÉÍÓÚÑ]', s)
        return ''.join(letters)
    return RE_LETRAS_ESPACIADAS.sub(join_letters, text)

RE_FALLO_PATTERNS = [
    # Patrón clásico: RESUELVE + PRIMERO + verbo
    re.compile(
        r'(?:RESUELVE|RESOLUCI[ÓO]N|FALL[AO]|DECIDE)[\s:\.\n]+'
        r'(?:PRIMERO|1\.?\-?|UNO\.?|I\.?)\s*[:\.\-]?\s*'
        r'(CONCEDE(?:R)?(?:\s+PARCIALMENTE)?|CONCEDIENDO|TUTELA(?:R)?|AMPARA(?:R)?|NIEGA(?:R)?|NEGAR|'
        r'IMPROCEDENTE|DECLARA(?:R)?\s+IMPROCEDENTE|RECHAZA(?:R)?|NO\s+TUTELA|'
        r'CONFIRMA(?:R)?|REVOCA(?:R)?|MODIFICA(?:R)?)',
        re.I,
    ),
    # Patrón directo después de RESUELVE/PRIMERO: capturar verbo en cualquier parte
    re.compile(
        r'(?:PRIMERO|1\.?\-?|UNO\.?)\s*[:\.\-]?\s*'
        r'(DECLARAR?\s+IMPROCEDENTE|CONCEDER\s+(?:EL\s+|LA\s+)?(?:AMPARO|TUTELA)(?:\s+PARCIALMENTE)?|'
        r'TUTELAR\s+(?:EL|LOS|LA|LAS)?\s*DERECH|AMPARAR\s+(?:EL|LOS|LA|LAS)?\s*DERECH|'
        r'NEGAR\s+(?:EL\s+|LA\s+)?(?:AMPARO|TUTELA)|NO\s+TUTELAR|RECHAZAR\s+(?:DE\s+PLANO|LA\s+ACCI)|'
        r'CONFIRMAR\s+(?:LA\s+SENTENCIA|EL\s+FALLO|INTEGRAMENTE)|REVOCAR\s+(?:LA\s+SENTENCIA|EL\s+FALLO|PARCIALMENTE)|'
        r'MODIFICAR\s+(?:LA\s+SENTENCIA|EL\s+FALLO))',
        re.I,
    ),
]

def normalize_fallo_1ra(raw: str) -> str | None:
    if not raw: return None
    u = strip_accents(raw).upper()
    if 'CONCED' in u and 'PARCIAL' in u: return 'CONCEDE PARCIALMENTE'
    if 'IMPROCEDENT' in u: return 'IMPROCEDENTE'  # antes de CONCEDE para evitar match falso
    if 'CONCED' in u or 'TUTELA' in u or 'AMPARA' in u: return 'CONCEDE'
    if 'NIEGA' in u or 'NEGAR' in u or 'NO TUTELA' in u: return 'NIEGA'
    if 'RECHAZA' in u: return 'RECHAZA'
    return None

def normalize_fallo_2da(raw: str) -> str | None:
    if not raw: return None
    u = strip_accents(raw).upper()
    if 'CONFIRMA' in u: return 'CONFIRMA'
    if 'REVOCA' in u: return 'REVOCA'
    if 'MODIFICA' in u: return 'MODIFICA'
    if 'CONCED' in u and 'PARCIAL' in u: return 'CONCEDE PARCIALMENTE'
    return None

def detect_fallo_in_doc(text: str) -> tuple[str | None, int | None]:
    """Detecta sentido del fallo + instancia automáticamente.
    Returns (sentido, instancia) o (None, None)."""
    if not text: return None, None
    norm = normalize_spaced_letters(text)
    # Buscar marca de SEGUNDA INSTANCIA en el texto
    is_segunda = bool(re.search(r'\b(?:SEGUNDA\s+INSTANCIA|2DA\s+INSTANCIA|TRIBUNAL\s+SUPERIOR|SALA\s+(?:CIVIL|PENAL))\b', norm[:5000], re.I))
    relevant = norm[-12000:] if len(norm) > 12000 else norm
    for pat in RE_FALLO_PATTERNS:
        for m in pat.finditer(relevant):
            raw = m.group(1)
            v2 = normalize_fallo_2da(raw)
            v1 = normalize_fallo_1ra(raw)
            if v2 and (is_segunda or not v1):
                return v2, 2
            if v1:
                return v1, 1
    return None, None

def extract_sentido_fallo(text: str, instancia: int = 1) -> str | None:
    """Compat: extrae solo si la instancia detectada coincide."""
    sentido, inst = detect_fallo_in_doc(text)
    if not sentido: return None
    if inst == instancia:
        return sentido
    return None

# Accionados / Vinculados — múltiples patrones, captura más permisiva
RE_ACCIONADOS_LIST = [
    re.compile(
        r'ACCIONAD[OA]S?\s*[:\-]?\s*\n?\s*([A-ZÁÉÍÓÚÑ\d][A-ZÁÉÍÓÚÑa-záéíóúñ0-9\s,\.\-&/\(\)°ºNn\.]{4,300}?)(?=\n\s*\n|\n\s*(?:VINCULAD|REPRESENT|HECHOS|PRETENSIONES|DERECHOS|RAD\.|RADICADO|JUEZ|ACCIONANTE|VINC[UÚ]L|EN\s+CONTRA|CONTRA\s+QUIEN|ASUNTO))',
        re.I,
    ),
    # Patrón "EN CONTRA DE" / "DIRIGIDA CONTRA"
    re.compile(
        r'(?:EN\s+CONTRA\s+DE|DIRIGIDA\s+CONTRA|CONTRA\s*[:\-]?\s+)([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ0-9\s,\.\-&/\(\)]{4,250}?)(?=\n\s*\n|\n\s*(?:VINCULAD|HECHOS|PRETENSIONES|DERECHOS|POR\s+(?:LA|EL)|EN\s+EJERCICIO|ACTUANDO))',
        re.I,
    ),
]

RE_VINCULADOS_LIST = [
    re.compile(
        r'(?:VINCULAD[OA]S?|VINC[UÚ]L(?:[ÉE]?SE|AR|ESE|ASE))\s*(?:A\s+)?[:\-]?\s*\n?\s*([A-ZÁÉÍÓÚÑ\d][A-ZÁÉÍÓÚÑa-záéíóúñ0-9\s,\.\-&/\(\)°ºNn\.]{4,400}?)(?=\n\s*\n|\n\s*(?:HECHOS|PRETENSIONES|DERECHOS|JUEZ|RAD\.|RADICADO|ACCIONAD|ACCIONANTE|EN\s+EJERCICIO|POR\s+(?:LA|EL)|ASUNTO))',
        re.I,
    ),
    # "ORDÉNASE VINCULAR A"
    re.compile(
        r'(?:ORD[ÉE]NASE\s+VINCULAR\s+A|D[ÉE]SE\s+TRASLADO\s+A|N[OÓ]TIF[IÍ]QUESE\s+A)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ0-9\s,\.\-&/\(\)]{4,300}?)(?=\n\s*\n|\n\s*(?:HECHOS|PRETENSIONES|DERECHOS|RAD\.|EN\s+EJERCICIO|POR\s+LA))',
        re.I,
    ),
]

def _clean_entity_list(raw: str) -> str | None:
    """Limpia lista de instituciones — corta en palabras de continuación de prosa."""
    s = ' '.join(raw.split()).strip(' ,.;:-')
    # Cortar en frases que indican prosa, no listado
    stop = re.search(
        r'\b(?:que\s+en|en\s+el\s+t[eé]rmino|deben?|deber[áa]n?|rendir|allegar|'
        r'presentar\s|en\s+su\s+contra|notif[ií]quese|c[óo]rrase|ent[eé]rese|'
        r'previo\s+a|para\s+que|conforme\s+a|por\s+lo\s+anterior|'
        r'en\s+ejercicio|hechos|pretensiones|qui[eé]n(?:es)?\s+(?:son|es)|'
        r'identific(?:ad[oa]|ándo)|cc?\s+\d|c[eé]dula|nuip)\b',
        s, re.I,
    )
    if stop:
        s = s[:stop.start()].strip(' ,.;:-')
    # Eliminar conectores al inicio
    s = re.sub(r'^(?:y\s+otros?|y\s+otras?|otros?|otras?|de\s+|a\s+|al\s+|la\s+|el\s+|los\s+|las\s+)+', '', s, flags=re.I).strip(' ,.;:-')
    if 4 <= len(s) <= 280:
        return s
    return None

def extract_accionados_vinculados(text: str) -> tuple[str | None, str | None]:
    if not text: return None, None
    snippet = text[:6000]
    accd = None
    vinc = None
    for pat in RE_ACCIONADOS_LIST:
        m = pat.search(snippet)
        if m:
            cand = _clean_entity_list(m.group(1))
            if cand:
                accd = cand
                break
    for pat in RE_VINCULADOS_LIST:
        m = pat.search(snippet)
        if m:
            cand = _clean_entity_list(m.group(1))
            if cand:
                vinc = cand
                break
    return accd, vinc

# CC del email .md
RE_CC = re.compile(r'(?:^|\n)\s*(?:Cc|CC|C\.C)\s*[:\-]\s*([^\n]+)', re.I)
RE_EMAIL = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')

# Dominios PERSONALES = contratistas. Filtro positivo (whitelist).
_PERSONAL_DOMAINS = {
    'gmail.com', 'hotmail.com', 'hotmail.es', 'outlook.com', 'outlook.es',
    'yahoo.com', 'yahoo.es', 'live.com', 'icloud.com', 'protonmail.com',
    'me.com', 'aol.com', 'msn.com', 'yopmail.com',
}

# Usernames que aunque sean dominio personal, son institucionales (SED en gmail, etc.)
_INSTITUTIONAL_USERNAMES = [
    'apoyojuridicosed', 'apoyojuridicogobernacion', 'apoyojuridico',
    'notificaciones', 'secretaria.', 'secretariadeeducacion',
    'sedsantander', 'gobernaciondesantander',
]

def _is_personal_email(email_lc: str) -> bool:
    """True si es dominio personal (= contratista). Cualquier .gov.co/.edu.co/.com.co es institucional.
    También rechaza usernames institucionales aunque sean en dominios personales."""
    if '@' not in email_lc: return False
    user, _, domain = email_lc.partition('@')
    if domain not in _PERSONAL_DOMAINS: return False
    for u in _INSTITUTIONAL_USERNAMES:
        if u in user: return False
    return True

def extract_abogado_from_email_md(text: str) -> str | None:
    """Primer email PERSONAL (gmail/hotmail/outlook/etc.) = contratista. Filtro positivo."""
    if not text: return None
    m = RE_CC.search(text)
    if not m:
        candidate_block = text[:4000]
    else:
        candidate_block = m.group(1) + "\n" + text[m.end():m.end()+2000]
    emails = RE_EMAIL.findall(candidate_block)
    for e in emails:
        e_low = e.lower()
        if _is_personal_email(e_low):
            return e
    return None

# Derechos fundamentales: keywords → categoría
DERECHOS_KEYWORDS = [
    ('EDUCACION', ['educaci[óo]n', 'educativ[oa]', 'matr[ií]cula', 'cupo escolar',
                   'colegio', 'escolar', 'docente', 'instituci[óo]n educativa',
                   'establecimiento educativ', 'curso lectivo']),
    ('SALUD', ['salud', '\\beps\\b', 'hospital', 'm[eé]dic[oa]', 'medicamento',
               'tratamiento m[eé]dico', 'cita m[eé]dica', 'eps[\\s-]', 'fomag', 'fiduprevisora']),
    ('DEBIDO PROCESO', ['debido proceso', 'derecho de defensa', 'contradicci[óo]n',
                         'audiencia', 'notificaci[óo]n']),
    ('TRABAJO', ['\\btrabajo\\b', 'laboral', 'empleo', 'salario', 'remuneraci[óo]n',
                  'estabilidad laboral', 'cesant[ií]a', 'pensi[óo]n', 'jubilaci[óo]n']),
    ('VIDA', ['derecho a la vida', 'integridad personal', 'amenaza\\s+(?:de\\s+muerte|grave)']),
    ('PETICION', ['derecho de petici[óo]n', 'respuesta\\s+a\\s+(?:la\\s+)?petici[óo]n',
                   'silencio administrativo', 'no\\s+(?:ha\\s+)?respond']),
    ('MINIMO VITAL', ['m[ií]nimo vital', 'subsistencia', 'alimentos b[áa]sicos']),
    ('VIVIENDA', ['vivienda digna', 'habitaci[óo]n', 'subsidio.*vivienda']),
    ('DIGNIDAD', ['dignidad humana']),
    ('IGUALDAD', ['\\bigualdad\\b', 'no discriminaci[óo]n', 'discriminaci[óo]n']),
    ('LIBRE DESARROLLO', ['libre desarrollo de la personalidad']),
    ('ALIMENTACION', ['\\bpae\\b', 'alimentaci[óo]n escolar', 'alimentos escolares']),
    ('TRANSPORTE', ['transporte escolar']),
    ('ACCESIBILIDAD', ['accesibilidad', 'discapacidad', 'apoyo pedag[óo]gico',
                        'docente de apoyo', 'inclusi[óo]n educativa']),
    ('ACCESO', ['acceso a la educaci[óo]n']),
    ('INTERES SUPERIOR DEL MENOR', ['inter[eé]s superior del menor', 'derechos del ni[ñn]o']),
    ('SEGURIDAD SOCIAL', ['seguridad social', 'sistema general.*pensi']),
]
DERECHOS_RES = [(name, re.compile(r'\b(?:' + '|'.join(kws) + r')\b', re.I)) for name, kws in DERECHOS_KEYWORDS]

def extract_derechos(text: str) -> str | None:
    """Devuelve derechos detectados separados por ' - '. Limita a top 4."""
    if not text: return None
    detected = []
    for name, regex in DERECHOS_RES:
        if regex.search(text):
            detected.append(name)
    if not detected: return None
    # Limitar a top 4 (los más frecuentes/relevantes)
    return ' - '.join(detected[:4])

# Pretensiones: regex sobre Escrito Tutela. PRETENSIONES en línea propia + lista numerada.
RE_PRETENSIONES = re.compile(
    r'\bPRETENSIONES\b\s*\n+'
    r'((?:.{15,200}\n){1,15})'  # 1-15 líneas
    r'(?=\n\s*\n\s*[A-ZÁÉÍÓÚÑ]{3,}|\n\s*(?:HECHOS|FUNDAMENTOS|DERECHOS\s+VULNERAD|PRUEBAS|JURAMENTO|ANEXOS?|NOTIFICACI|FIRM)|$)',
    re.I,
)

def extract_pretensiones_from_escrito(text: str) -> str | None:
    """Solo aplicar a docs que parecen escrito de tutela (no fallo/sentencia)."""
    if not text: return None
    # Verificar que NO sea un fallo/sentencia (que mencionarían "pretensiones del accionante")
    upper = text[:3000].upper()
    if 'RESUELVE' in upper or 'SENTENCIA DE TUTELA' in upper or 'PARTE RESOLUTIVA' in upper:
        # Es fallo, evitar
        if 'PRETENSIONES DEL ACCIONANTE' in upper or 'PRETENSIONES DE LA TUTELA' in upper:
            return None
    m = RE_PRETENSIONES.search(text[:12000])
    if not m: return None
    pret = m.group(1).strip()
    # Validar que tenga estructura de lista (numeración, viñetas, "Solicit", "Ruego", "PRIMERA:", etc.)
    if not re.search(r'(?:\d+[\.\)]|\bPRIM(?:ER[OA])?\b|SEGUND[OA]|TERCER[OA]|•|\bSOLICIT|\bRUEGO|\bAMPARAR|\bORDENAR|\bGARANTI|\bDECLARAR)', pret, re.I):
        return None
    pret = re.sub(r'\n{2,}', '\n', pret)
    pret = re.sub(r'\s{2,}', ' ', pret)
    pret = pret.strip(' .,;:-')
    if len(pret) < 30 or len(pret) > 2000: return None
    return pret[:600]

# Asunto: extracción + heurística
RE_ASUNTO_DOC = re.compile(
    r'(?:ASUNTO|REFERENCIA|REF\.?)\s*[:\-]\s*([^\n]{10,200})',
    re.I,
)

def extract_asunto(text: str, derecho: str | None, categoria: str | None) -> str | None:
    if not text: return None
    # Intento 1: encabezado del doc
    m = RE_ASUNTO_DOC.search(text[:3000])
    if m:
        a = m.group(1).strip(' .,;:-')
        # Filtrar si es un radicado o numero
        if not re.match(r'^[\d\-/]+\s*$', a) and 10 <= len(a) <= 200:
            return a
    # Intento 2: heurística por keywords
    text_low = text[:5000].lower()
    if 'cupo' in text_low or 'matr[ií]cula' in text_low or 'no.*matric' in text_low:
        return "Solicita cupo o matrícula escolar"
    if 'pae' in text_low or 'alimentaci[óo]n escolar' in text_low or 'alimentos escolares' in text_low:
        return "Solicita garantía de alimentación escolar (PAE)"
    if 'transporte escolar' in text_low:
        return "Solicita transporte escolar"
    if 'docente de apoyo' in text_low or 'apoyo pedag[óo]gico' in text_low:
        return "Solicita docente de apoyo pedagógico"
    if 'desacato' in text_low or 'incumplimiento' in text_low:
        return "Incidente de desacato"
    if 'petici[óo]n' in text_low and 'respuesta' in text_low:
        return "Solicita respuesta a derecho de petición"
    if 'salud' in text_low and ('eps' in text_low or 'tratamiento' in text_low):
        return "Solicita acceso a servicio de salud"
    # Fallback: derecho_vulnerado
    if derecho:
        first = derecho.split(' - ')[0]
        return f"Tutela por vulneración a {first}"
    return None

# Email .md parsers — fallback de identidad
RE_EMAIL_CASO = re.compile(r'\*\*Caso:\*\*\s*\d{4}-\d+\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s\.]{4,80}?)(?:\s*\[|\n|$)')
RE_EMAIL_FECHA = re.compile(r'\*\*Fecha:\*\*\s*(\d{4}-\d{2}-\d{2})')
RE_EMAIL_ASUNTO_HEADER = re.compile(r'^#\s+(.+?)\s*$', re.M)
RE_EMAIL_JUZGADO = re.compile(
    r'(JUZGADO\s+(?:\d{1,3}|°?\d+|PRIMERO|SEGUNDO|TERCERO|CUARTO|QUINTO|SEXTO|S[ÉE]PTIMO|OCTAVO|NOVENO|D[ÉE]CIMO|UND[ÉE]CIMO|DUOD[ÉE]CIMO)\s*°?\s*(?:CIVIL|PENAL|LABORAL|PROMISCUO|FAMILIA|DE\s+EJECUCI[ÓO]N)[^<\n]{3,100}?)(?:\s*<|\s+\(|\s*\n|;)',
    re.I,
)
RE_EMAIL_BLOCK_ACCIONANTE = re.compile(
    r'ACCIONANTE\s*[:\-]\s*\n?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s\.]+?)(?:\n|ACCIONAD|VINCULAD)',
    re.I,
)

def extract_from_email_md(text: str) -> dict:
    """Devuelve dict con campos extraíbles del email .md de notificación."""
    out = {}
    if not text: return out
    # Caso: desde header **Caso:**
    m = RE_EMAIL_CASO.search(text)
    if m:
        cand = ' '.join(m.group(1).split()).strip(' .,;:')
        cleaned = _clean_accionante(cand)
        if cleaned:
            out['accionante'] = cleaned
    # Fallback: bloque "ACCIONANTE:" en cuerpo del email forwarded
    if 'accionante' not in out:
        m = RE_EMAIL_BLOCK_ACCIONANTE.search(text)
        if m:
            cleaned = _clean_accionante(m.group(1))
            if cleaned:
                out['accionante'] = cleaned
    # Juzgado: probar TODOS los matches y elegir el primero con municipio Santander
    for m in RE_EMAIL_JUZGADO.finditer(text):
        juz = ' '.join(m.group(1).split()).strip(' .,;:')
        if len(juz) > 150: continue
        upper = strip_accents(juz).upper()
        # Skip si es Tribunal/Sala (es 2da instancia, no juzgado del caso)
        if 'TRIBUNAL' in upper or 'SALA' in upper: continue
        for muni in sorted(MUNICIPIOS_SANTANDER, key=len, reverse=True):
            if muni in upper:
                out['juzgado'] = juz[:120]
                out['ciudad'] = muni.title()
                break
        if 'juzgado' in out: break
    # Fecha del email = aproximación de fecha de notificación
    m = RE_EMAIL_FECHA.search(text)
    if m:
        out['email_fecha'] = m.group(1)
    # Asunto del email indica tipo de doc
    m = RE_EMAIL_ASUNTO_HEADER.search(text)
    if m:
        asunto = m.group(1)
        upper = asunto.upper()
        out['email_asunto_upper'] = upper
        # Inferir fecha_fallo si el asunto dice "FALLO 1 INST" y hay email_fecha
        if 'FALLO' in upper and ('1 INST' in upper or 'PRIMERA' in upper or 'PRIMER' in upper):
            out['_is_fallo1_email'] = True
        if 'FALLO' in upper and ('2 INST' in upper or 'SEGUNDA' in upper or '2DA' in upper):
            out['_is_fallo2_email'] = True
        if 'IMPUGNACION' in upper or 'IMPUGNACIÓN' in upper:
            out['_is_impug_email'] = True
        if 'AUTO ADMITE' in upper or 'ADMISIÓN' in upper or 'ADMISION' in upper or 'AVOCA' in upper:
            out['_is_avoca_email'] = True
        if 'INCIDENTE' in upper or 'DESACATO' in upper:
            out['_is_incidente_email'] = True
    return out

# Forest radicado
RE_FOREST_NUM = re.compile(r'(?:RAD(?:ICADO)?\s+FOREST|FOREST(?:\s+RAD(?:ICADO)?)?)[:\s\-]*(\d{6,12})', re.I)
RE_FOREST_HEAD = re.compile(r'^\s*(\d{7,10})\s', re.M)  # número al inicio de filename

def extract_forest_rad(text: str, filename: str = "") -> str | None:
    if filename:
        m = re.match(r'(\d{7,10})\b', filename)
        if m:
            return m.group(1)
    if text:
        m = RE_FOREST_NUM.search(text[:2000])
        if m:
            return m.group(1)
    return None

# ─── Análisis por caso ────────────────────────────────────────────────

def analyze_case(case: Case, db: Session) -> dict:
    """Aplica Fases A+B+C al case. Devuelve dict de campos extraídos."""
    folder = Path(case.folder_path)
    if not folder.exists():
        return {}

    fields = {}
    docs = db.query(Document).filter(Document.case_id == case.id).all()

    # Cargar texto de todos los docs relevantes una vez
    doc_texts = {}  # filename → (text, pages)
    for d in docs:
        p = Path(d.file_path)
        if not p.exists(): continue
        suf = p.suffix.lower()
        if suf == '.pdf':
            txt, pages = extract_pdf_pages(p, first=5, last=3)
            doc_texts[d.filename] = (txt, pages, d.doc_type)
        elif suf in ('.md',):
            try:
                txt = p.read_text(encoding='utf-8', errors='ignore')[:5000]
                doc_texts[d.filename] = (txt, 1, d.doc_type)
            except: pass
        elif suf in ('.docx','.doc'):
            try:
                from docx import Document as Docx
                dx = Docx(p)
                txt = "\n".join(p.text for p in dx.paragraphs if p.text.strip())[:5000]
                doc_texts[d.filename] = (txt, 1, d.doc_type)
            except: pass

    # FASE A: Identidad (Auto Avoca → accionante, juzgado, ciudad)
    # Cascada: Auto Avoca > Auto Vincula/Requiere > Sentencia 1ra > Sentencia 2da > Escrito Tutela
    PRIORITY = [
        ('PDF_AUTO_ADMISORIO', AUTO_AVOCA_FNAME, AUTO_AVOCA_CONTENT),
        ('PDF_AUTO_VINCULA', None, None),
        ('PDF_AUTO_REQUIERE', None, None),
        ('PDF_FALLO_1RA', FALLO_1RA_FNAME, None),
        ('PDF_FALLO_2DA', FALLO_2DA_FNAME, None),
        ('PDF_ESCRITO_TUTELA', None, None),
    ]
    identity_text = None
    identity_source = None
    for tipo, fname_hints, content_hints in PRIORITY:
        for fname, (txt, pages, dt) in doc_texts.items():
            if dt == tipo:
                identity_text = txt
                identity_source = (tipo, fname)
                break
            if fname_hints and is_anchor(fname, txt, fname_hints, content_hints or [], total=pages):
                identity_text = txt
                identity_source = (tipo, fname)
                break
        if identity_text: break

    if identity_text:
        accionante = extract_accionante(identity_text)
        if accionante:
            fields['accionante'] = accionante
        juz, ciu = extract_juzgado_y_ciudad(identity_text)
        if juz:
            fields['juzgado'] = juz
        if ciu:
            fields['ciudad'] = ciu
        # Fecha ingreso = fecha del primer doc legal
        f = extract_fecha(identity_text[:3000])
        if f:
            fields['fecha_ingreso'] = f
        # Accionados/Vinculados solo desde Auto Avoca o Auto Vincula
        if identity_source[0] in ('PDF_AUTO_ADMISORIO', 'PDF_AUTO_VINCULA'):
            accd, vinc = extract_accionados_vinculados(identity_text)
            if accd:
                fields['accionados'] = accd
            if vinc:
                fields['vinculados'] = vinc

    # FASE B.1+B.2: Detectar fallos automáticamente (1ra y 2da)
    # Iteramos TODOS los docs candidatos a fallo (incluyendo PDF_OTRO con "sentencia"/"fallo")
    for fname, (txt, pages, dt) in doc_texts.items():
        if dt not in ('PDF_FALLO_1RA', 'PDF_FALLO_2DA') and not any(h in fname.lower() for h in FALLO_1RA_FNAME + FALLO_2DA_FNAME):
            continue
        sentido, inst = detect_fallo_in_doc(txt)
        ff = extract_fecha(txt[:3000])
        if inst == 1:
            if sentido and 'sentido_fallo_1st' not in fields:
                fields['sentido_fallo_1st'] = sentido
            if ff and 'fecha_fallo_1st' not in fields:
                fields['fecha_fallo_1st'] = ff
        elif inst == 2:
            if sentido and 'sentido_fallo_2nd' not in fields:
                fields['sentido_fallo_2nd'] = sentido
                fields['impugnacion'] = 'SI'
            if ff and 'fecha_fallo_2nd' not in fields:
                fields['fecha_fallo_2nd'] = ff
            if 'juzgado_2nd' not in fields:
                juz2, _ = extract_juzgado_y_ciudad(txt)
                if juz2:
                    fields['juzgado_2nd'] = juz2

    # FASE B.3: Impugnación (presencia)
    if 'impugnacion' not in fields:
        for fname, (txt, pages, dt) in doc_texts.items():
            if dt == 'PDF_IMPUGNACION' or 'impugnacion' in fname.lower():
                fields['impugnacion'] = 'SI'
                # Forest del oficio de impugnación
                fr = extract_forest_rad(txt, fname)
                if fr:
                    fields['forest_impugnacion'] = fr
                break
        else:
            # No hay doc de impugnación
            if 'sentido_fallo_1st' in fields:
                fields['impugnacion'] = 'NO'

    # FASE B.4: Incidente (presencia)
    for fname, (txt, pages, dt) in doc_texts.items():
        if dt == 'PDF_INCIDENTE' or any(h in fname.lower() for h in INCID_FNAME):
            fields['incidente'] = 'SI'
            ff = extract_fecha(txt[:3000])
            if ff:
                fields['fecha_apertura_incidente'] = ff
            break
    else:
        fields.setdefault('incidente', 'NO')

    # FASE B.5: Carta-Respuesta DOCX → fecha_respuesta + forest
    for fname, (txt, pages, dt) in doc_texts.items():
        if dt == 'DOCX_RESPUESTA' or any(h in fname.lower() for h in RESP_DOCX_FNAME):
            if Path(fname).suffix.lower() not in ('.docx','.doc'): continue
            ff = extract_fecha(txt[:1000])
            if ff:
                fields['fecha_respuesta'] = ff
            fr = extract_forest_rad(txt, fname)
            if fr:
                fields['radicado_forest'] = fr
            break

    # FASE C: EMAIL_MD → abogado + fallback identidad/fecha_fallo
    email_data = {}
    for fname, (txt, pages, dt) in doc_texts.items():
        if dt == 'EMAIL_MD' or fname.lower().endswith('.md'):
            # abogado solo desde el primer email
            if 'abogado_responsable' not in fields:
                ab = extract_abogado_from_email_md(txt)
                if ab:
                    fields['abogado_responsable'] = ab
            # extraer info estructurada
            info = extract_from_email_md(txt)
            # acumular por tipo (queremos el email del fallo 1ra para fecha_fallo_1st)
            if info.get('_is_fallo1_email') and info.get('email_fecha') and 'fecha_fallo_1st' not in fields:
                fields['fecha_fallo_1st'] = info['email_fecha']
            if info.get('_is_fallo2_email') and info.get('email_fecha') and 'fecha_fallo_2nd' not in fields:
                fields['fecha_fallo_2nd'] = info['email_fecha']
                fields['impugnacion'] = 'SI'
            if info.get('_is_avoca_email') and info.get('email_fecha') and 'fecha_ingreso' not in fields:
                fields['fecha_ingreso'] = info['email_fecha']
            if info.get('_is_incidente_email') and info.get('email_fecha') and 'fecha_apertura_incidente' not in fields:
                fields['fecha_apertura_incidente'] = info['email_fecha']
                fields['incidente'] = 'SI'
            # Fallback accionante / juzgado / ciudad
            if info.get('accionante') and 'accionante' not in fields:
                fields['accionante'] = info['accionante']
            if info.get('juzgado') and 'juzgado' not in fields:
                fields['juzgado'] = info['juzgado']
            if info.get('ciudad') and 'ciudad' not in fields:
                fields['ciudad'] = info['ciudad']

    # INFERENCIAS

    # quien_impugno: si impugnacion=SI, default ACCIONADO (la SED suele impugnar fallo CONCEDE)
    if fields.get('impugnacion') == 'SI':
        # Si tenemos Carta-Impugnación DOCX firmada por SED → ACCIONADO
        # Si solo hay PDF_IMPUGNACION (auto del juzgado), inferir desde fallo:
        # Si fallo 1ra fue CONCEDE → impugna ACCIONADO; si NIEGA → impugna ACCIONANTE
        f1 = fields.get('sentido_fallo_1st', '')
        if f1 in ('CONCEDE', 'CONCEDE PARCIALMENTE', 'AMPARA'):
            fields['quien_impugno'] = 'ACCIONADO'
        elif f1 in ('NIEGA', 'IMPROCEDENTE', 'RECHAZA'):
            fields['quien_impugno'] = 'ACCIONANTE'

    # oficina_responsable: heurística — buscar dependencia SED en accionados+vinculados
    accd_vinc = ' '.join([fields.get('accionados','') or '', fields.get('vinculados','') or '']).upper()
    if 'SECRETAR' in accd_vinc and 'EDUCAC' in accd_vinc:
        fields['oficina_responsable'] = 'Secretaría de Educación de Santander'
    elif 'GOBERNACI' in accd_vinc and 'SANTANDER' in accd_vinc:
        fields['oficina_responsable'] = 'Gobernación de Santander'

    # categoria_tematica: heurística básica desde accionados+vinculados
    if not fields.get('categoria_tematica'):
        if 'EDUCACI' in accd_vinc or 'COLEGIO' in accd_vinc or 'ESCUELA' in accd_vinc or 'INSTITUCI[OÓ]N\s+EDUCATIVA' in accd_vinc:
            fields['categoria_tematica'] = 'EDUCACION'
        elif 'EPS' in accd_vinc or 'SALUD' in accd_vinc or 'NUEVA' in accd_vinc or 'SANITAS' in accd_vinc:
            fields['categoria_tematica'] = 'SALUD'
        elif 'PENSI' in accd_vinc or 'COLPENSIONES' in accd_vinc:
            fields['categoria_tematica'] = 'PENSIONES'

    # FASE B.6: derecho_vulnerado, asunto, pretensiones por regex/keywords (sin LLM)
    # Concatenar texto de los docs principales para búsqueda
    main_text = ""
    for tipo in ('PDF_AUTO_ADMISORIO', 'PDF_ESCRITO_TUTELA', 'PDF_FALLO_1RA'):
        for fname, (txt, pages, dt) in doc_texts.items():
            if dt == tipo and txt:
                main_text += "\n" + txt[:4000]
                break
    if not main_text and identity_text:
        main_text = identity_text[:5000]

    if main_text:
        # derecho_vulnerado
        derechos = extract_derechos(main_text)
        if derechos:
            fields['derecho_vulnerado'] = derechos
        # asunto
        asunto = extract_asunto(main_text, fields.get('derecho_vulnerado'), fields.get('categoria_tematica'))
        if asunto:
            fields['asunto'] = asunto

    # Pretensiones: SOLO desde Escrito de Tutela (no del fallo)
    escrito_text = None
    for fname, (txt, pages, dt) in doc_texts.items():
        # Escrito clasificado o PDFs largos (no auto/fallo) que contengan "PRETENSIONES" en mayúsculas
        if dt == 'PDF_ESCRITO_TUTELA':
            escrito_text = txt
            break
        if dt == 'PDF_OTRO' and pages and pages > 5 and 'PRETENSIONES' in (txt or '').upper():
            escrito_text = txt
            break
    if escrito_text:
        pret = extract_pretensiones_from_escrito(escrito_text)
        if pret:
            fields['pretensiones'] = pret

    # ESTADO default
    fields.setdefault('estado', 'ACTIVO')

    return fields

# ─── Main ─────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="Máximo casos a procesar (0=todos)")
    ap.add_argument("--dry-run", action="store_true", help="Solo imprime, no escribe DB")
    args = ap.parse_args()

    db: Session = SessionLocal()
    cases = db.query(Case).filter(Case.processing_status == 'PENDIENTE').order_by(Case.id).all()
    if args.limit:
        cases = cases[:args.limit]
    print(f"Procesando {len(cases)} casos PENDIENTES...")

    started = time.time()
    counts = {"ok": 0, "no_avoca": 0, "errors": 0, "fields_total": 0}

    for i, case in enumerate(cases, 1):
        try:
            fields = analyze_case(case, db)
            if not fields:
                counts["no_avoca"] += 1
            else:
                counts["fields_total"] += len(fields)
                counts["ok"] += 1

            if not args.dry_run:
                for k, v in fields.items():
                    setattr(case, k, v)
                case.processing_status = 'COMPLETO_DET'  # marca distintivo: determinístico
                if i % 50 == 0:
                    db.commit()

        except Exception as e:
            counts["errors"] += 1
            print(f"  [{i}] ERROR case#{case.id}: {e}")
            db.rollback()
            continue

        if i % 25 == 0 or i == len(cases):
            elapsed = time.time() - started
            avg = elapsed / i
            print(f"  [{i:>3}/{len(cases)}] avg={avg*1000:.0f}ms/caso  ok={counts['ok']}  no_avoca={counts['no_avoca']}  fields_total={counts['fields_total']}")

    if not args.dry_run:
        db.commit()

    elapsed = time.time() - started
    print(f"\n=== RESULTADO ===")
    print(f"  Casos procesados: {len(cases)}")
    print(f"  OK: {counts['ok']}  Sin Auto Avoca: {counts['no_avoca']}  Errores: {counts['errors']}")
    print(f"  Total campos llenados: {counts['fields_total']}")
    print(f"  Promedio campos/caso: {counts['fields_total']/max(1,counts['ok']):.1f}")
    print(f"  Tiempo total: {elapsed/60:.1f} min  ({elapsed/len(cases)*1000:.0f}ms/caso)")
    db.close()

if __name__ == "__main__":
    main()
