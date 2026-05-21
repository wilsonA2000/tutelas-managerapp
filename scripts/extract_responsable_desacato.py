"""Extractor de `responsable_desacato` desde autos de incidente.

Lee literalmente lo que dice el juez en docs INCIDENTE_DESACATO/AUTO_INCIDENTE.
Reglas:
  1. Buscar verbo decisorio ("se ordena REQUERIR a", "REQUIERA a", "incidente de
     desacato en contra de", "imponer sanción a") seguido del nombre del responsable.
  2. Si no hay verbo decisorio pero hay etiqueta "ACCIONADO[S]: …", tomar la primera
     entidad del listado.
  3. Si hay varios autos en el case, consolidar por votos (más frecuente gana).

Output: data/datasets/responsable_desacato/ con
  - dataset.jsonl (case_id, doc_id, fragment, label, pattern, confidence)
  - summary.csv (case_id, folder, label_proposed, label_current, votes_json)
"""
from __future__ import annotations
import sqlite3, re, unicodedata, json, csv
from collections import Counter
from pathlib import Path

# Nombre de persona: 2-6 palabras en mayúsculas iniciales, longitud razonable.
_NAME_TOKEN = r'[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\.]{1,30}'
_NAME = rf'(?:{_NAME_TOKEN}\s+){{1,5}}{_NAME_TOKEN}'

# P1 (MÁS FUERTE): "DAR APERTURA AL INCIDENTE DE DESACATO ... en contra del Dr. NOMBRE"
# Patrón canónico identificado en cid 72 (Juzgado Promiscuo Municipal Santa Bárbara).
# Es la decisión dispositiva primaria del juez. El primer nombre tras "en contra de(l)" es
# el responsable principal nombrado.
PAT_APERTURA = re.compile(
    rf'(?ims)(?:dar\s+)?apertura\s+(?:al\s+)?incidente\s+(?:de\s+)?desacato'
    rf'[^.]{{0,500}}?\b(?:en\s+contra|contra)\s+(?:de(?:l)?\s+)?'
    rf'(?:la\s+|el\s+|los\s+|las\s+)?(?:dra?\.?\s+|doctora?\s+|sr\.?\s+|señora?\s+|señor\s+)?'
    rf'({_NAME})'
)
# Verbos decisorios del juez
PAT_ORDENA = re.compile(rf'(?ims)(?:se\s+)?ordena\s+REQUERIR\s+a\s+({_NAME})')
PAT_CONTRA = re.compile(rf'(?ims)incidente\s+(?:de\s+)?desacato\s+(?:formalmente\s+)?(?:en\s+)?contra\s+(?:de\s+)?(?:la\s+|el\s+|los\s+|las\s+)?(?:doctora?\s+|dra?\.?\s+|señora?\s+|sr\.?\s+|señor\s+)?({_NAME})')
PAT_REQUERIRA = re.compile(rf'(?im)REQUERIR(?:[ÁA])?S?[EAÁ]?\s+(?:previamente\s+)?a\s+(?:la\s+|el\s+|los\s+|las\s+)?(?:dra?\.?\s+|doctora?\s+|señora?\s+|sr\.?\s+|señor\s+)?({_NAME})')
PAT_SANCION = re.compile(rf'(?im)(?:impone(?:r|n)?|imp[óo]nese|sanci[óo]n[ae][rs]?(?:e|a)?|sancionar)\s+(?:la\s+)?(?:sanci[óo]n\s+)?(?:de\s+arresto[^,\n]{{0,40}})?\s*a\s+(?:la\s+|el\s+)?(?:doctora?\s+|dra?\.?\s+)?({_NAME})')
# Entidad: ACCIONADO[S]:
PAT_ACCIONADOS = re.compile(r'(?im)(?:^|\n)\s*Accionad[oa]s?\s*\(?s?\)?\s*[:\.]\s*([^\n]{6,200})')
# INCIDENTADOS: usado por juzgados administrativos (cid 145)
PAT_INCIDENTADOS = re.compile(r'(?im)(?:^|\n)\s*Incidentad[oa]s?\s*[:\.]\s*([^\n]{6,200})')

# Cuando el cargo aparece tras el nombre como aposición ("- Secretaria", ", en su calidad")
_CARGO_TAIL = re.compile(r'(?i)\s*[-,;]?\s*(?:secretari[ao]\b|director\w*|gobernador\b|jefe\b|rector\w*|subdirector\w*|coordinador\w*|personero\w*|en\s+(?:su\s+)?(?:calidad|condici[oó]n)\b|identificad[oa]\b|cedula\b|c\.?c\.?\s|para\s+que\b|y\s+(?:al|otros?|dem)\b|portador[a]?\b).*$')

def _strip_accents_upper(s: str) -> str:
    n = unicodedata.normalize('NFD', s.upper())
    return ''.join(c for c in n if unicodedata.category(c) != 'Mn')

# Palabras que NO pueden estar en un nombre de funcionario (basura sintáctica)
_NAME_STOPWORDS = {
    'DEL', 'DE', 'LA', 'EL', 'LOS', 'LAS', 'Y', 'QUE', 'HAYA', 'LUGAR', 'PREVIO',
    'ACCIONADOS', 'ACCIONADA', 'ACCIONADO', 'DEMAS', 'DEMÁS', 'OTROS', 'OTRAS',
    'PARA', 'POR', 'CONTRA', 'COMO', 'EN', 'SUS', 'SU', 'CALIDAD', 'CONDICION', 'CONDICIÓN',
    'IDENTIFICADO', 'IDENTIFICADA', 'CÉDULA', 'CEDULA', 'PORTADOR', 'PORTADORA',
    'MAYOR', 'EDAD', 'MENOR', 'NUMERO', 'NÚMERO', 'NO',
}

def normalize_name(raw: str | None) -> str | None:
    if not raw:
        return None
    v = re.sub(r'\s+', ' ', raw).strip()
    v = re.sub(r'^(?:dra?\.?\s+|doctora?\s+|señora?\s+|sr\.?\s+|señor\s+|don\s+|doña\s+|y\s+(?:al\s+)?)', '', v, flags=re.I)
    v = _CARGO_TAIL.sub('', v).strip(' .,;:-|')
    # Correcciones comunes
    v = re.sub(r'(?i)\bJUVENTAL\b', 'JUVENAL', v)
    v = re.sub(r'(?i)\bDIAZ\s+MATEUS\b', 'DÍAZ MATEUS', v)
    v = re.sub(r'(?i)\bARA[UÚ]JO\b', 'ARAUJO', v)
    # Validar: 2-6 palabras, primera mayúscula, sin stopwords en cualquier posición
    words = v.split()
    if not (2 <= len(words) <= 6):
        return None
    if not all(re.match(r'^[A-ZÁÉÍÓÚÑ]', w) for w in words):
        return None
    # Si alguna palabra es stopword → no es nombre de persona (es frase)
    norm_words = [_strip_accents_upper(w).strip('.,;:') for w in words]
    if any(w in _NAME_STOPWORDS for w in norm_words):
        return None
    # No puede empezar ni terminar en preposición / artículo
    if norm_words[0] in {'DE', 'DEL', 'LA', 'EL', 'LOS', 'LAS', 'Y'} or \
       norm_words[-1] in {'DE', 'DEL', 'LA', 'EL', 'LOS', 'LAS', 'Y'}:
        return None
    if not (6 <= len(v) <= 60):
        return None
    # OCR roto: contiene caracteres no-alfa/no-espacio
    if re.search(r'[<>\\|/]', v):
        return None
    return v.upper()

def normalize_entity(raw: str | None) -> str | None:
    if not raw:
        return None
    v = re.sub(r'\s+', ' ', raw).strip(' .,;:|–-')
    v = re.split(r'\s*[–\-]\s*|\s+y\s+(?:la\s+|el\s+|los\s+|las\s+)?', v)[0].strip(' .,;:')
    # OCR roto
    if re.search(r'[<>\\|/]', v):
        return None
    # No puede terminar en preposición
    if re.search(r'\s+(?:de|del|la|el|los|las|y)\s*$', v, re.I):
        # Intentar cortar antes de la preposición trailing
        v = re.sub(r'\s+(?:de|del|la|el|los|las|y)\s*$', '', v, flags=re.I).strip()
    if 8 <= len(v) <= 100 and re.search(r'(?i)secretar|gobernaci[oó]n|alcald|ministeri|instituci[oó]n|colegio|escuela|oficina|direcci[oó]n|grupo|equipo|fondo|empresa|eps\b', v):
        return v.upper()
    return None

def _head_tail(text: str, head_chars: int = 8000, tail_chars: int = 8000) -> str:
    """Regla operativa Wilson 2026-05-18: leer solo primeras N + últimas N chars
    (≈ primeras 5 pp + últimas 5 pp). Lo relevante de un auto siempre está en los
    extremos: cabezal (incidentados) + RESUELVE final. El medio es exposición."""
    if not text:
        return ''
    if len(text) <= head_chars + tail_chars:
        return text
    return text[:head_chars] + '\n\n[...]\n\n' + text[-tail_chars:]


def extract(text: str) -> tuple[str | None, str | None, str | None]:
    """Returns (label, pattern, fragment) o (None, None, None).

    Aplica regla head+tail al texto largo. Patrones priorizados:
      P1. DAR APERTURA AL INCIDENTE DESACATO ... en contra de NOMBRE  (decisión dispositiva)
      P2. ORDENA REQUERIR a NOMBRE                                    (requerimiento previo)
      P3. incidente desacato (en) contra de NOMBRE                   (apertura informal)
      P4. REQUERIRÁ a NOMBRE                                          (variante imperativa)
      P5. SANCIÓN/IMPONER a NOMBRE                                    (fallo sancionatorio)
      P6. ACCIONADO[S] | INCIDENTADOS                                 (entidad cabecera)
    """
    if not text:
        return None, None, None
    text_ht = _head_tail(text)
    for name, pat in (
        ('APERTURA', PAT_APERTURA),       # P1 — más fuerte
        ('ORDENA_REQUERIR', PAT_ORDENA),
        ('CONTRA', PAT_CONTRA),
        ('REQUERIRA', PAT_REQUERIRA),
        ('SANCION', PAT_SANCION),
    ):
        for m in pat.finditer(text_ht):
            cand = normalize_name(m.group(1))
            if cand:
                i = m.start()
                return cand, name, text_ht[max(0, i - 100):i + 200].replace('\n', ' ')[:300]
    # Fallback entidad: INCIDENTADOS (admin) o ACCIONADOS
    for ent_name, ent_pat in (('INCIDENTADOS', PAT_INCIDENTADOS), ('ACCIONADOS', PAT_ACCIONADOS)):
        m = ent_pat.search(text_ht)
        if m:
            ent = normalize_entity(m.group(1))
            if ent:
                return ent, ent_name, text_ht[max(0, m.start() - 30):m.end() + 30].replace('\n', ' ')[:300]
    return None, None, None

# Peso por doc_type: los autos de incidente pesan más; otros docs son evidencia menor.
_DOC_WEIGHT = {
    'INCIDENTE_DESACATO': 3,   # auto del juez — más autoridad
    'AUTO_INCIDENTE': 3,
    'RESPUESTA': 2,            # la SED contesta — suele nombrar accionado
    'AUTO_ADMISORIO': 1,
    'NOTIFICACION': 1,
    'NOTIFICACION_FALLO': 1,
    'OFICIO_CUMPLIMIENTO': 1,
    'SENTENCIA_1RA': 1,
    'SENTENCIA_2DA': 1,
}

# Peso por patrón regex: las decisiones DISPOSITIVAS del juez pesan más que
# las etiquetas/cabeceras. El bloque RESUELVE/PRIMERO con "DAR APERTURA en
# contra de X" es donde el juez señala al responsable; ACCIONADOS/INCIDENTADOS
# son etiquetas del cabezal que pueden ser genéricas (entidades).
_PATTERN_WEIGHT = {
    'APERTURA': 5,         # "DAR APERTURA AL INCIDENTE DE DESACATO ... en contra de X" — máxima autoridad
    'SANCION': 5,          # "IMPONER sanción a X" — fallo sancionatorio
    'ORDENA_REQUERIR': 4,
    'REQUERIRA': 4,
    'CONTRA': 3,           # "incidente desacato contra X" (puede ser solicitud accionante)
    'INCIDENTADOS': 2,
    'ACCIONADOS': 1,       # etiqueta cabezal — peso mínimo
}


def extract_for_case(con: sqlite3.Connection, case_id: int) -> dict:
    """Lee TODOS los docs del case con peso por doc_type y consolida.

    Estrategia (Wilson 2026-05-18: leer y decidir según realidad):
      - Autos INCIDENTE/AUTO_INCIDENTE pesan 3× (autoridad del juez).
      - RESPUESTA pesa 2× (la SED nombra al accionado).
      - Otros docs pesan 1×.
      - Si solo hay entidades, prevalece la persona del auto del juez.
    """
    docs = con.execute("""SELECT id, doc_type, filename, extracted_text FROM documents
                          WHERE case_id=? AND doc_type IS NOT NULL
                          ORDER BY id""", (case_id,)).fetchall()
    per_doc = []
    weighted: Counter[str] = Counter()
    raw_votes: Counter[str] = Counter()
    patterns: dict[str, str] = {}
    fragments: dict[str, str] = {}
    sources: dict[str, set[str]] = {}
    for d in docs:
        w_doc = _DOC_WEIGHT.get(d['doc_type'], 0)
        if w_doc == 0:
            continue
        lab, pat, frag = extract(d['extracted_text'] or '')
        # Peso combinado: doc_type × pattern (patrón es señal de calidad de la extracción)
        w_pat = _PATTERN_WEIGHT.get(pat or '', 1)
        w = w_doc * w_pat
        per_doc.append({
            'doc_id': d['id'], 'doc_type': d['doc_type'], 'filename': d['filename'],
            'label': lab, 'pattern': pat, 'fragment': frag, 'weight': w,
        })
        if lab:
            weighted[lab] += w
            raw_votes[lab] += 1
            patterns.setdefault(lab, pat or '')
            fragments.setdefault(lab, frag or '')
            sources.setdefault(lab, set()).add(d['doc_type'])
    if not weighted:
        return {'label': None, 'confidence': 0.0, 'votes': {}, 'per_doc': per_doc}
    top_label, top_w = weighted.most_common(1)[0]
    total_w = sum(weighted.values())
    confidence = top_w / total_w
    # Boost de confianza si el voto viene de auto de incidente
    if 'INCIDENTE_DESACATO' in sources.get(top_label, set()) or 'AUTO_INCIDENTE' in sources.get(top_label, set()):
        confidence = min(1.0, confidence + 0.1)
    return {
        'label': top_label,
        'pattern': patterns[top_label],
        'fragment': fragments[top_label],
        'confidence': round(confidence, 2),
        'votes': dict(raw_votes),
        'weighted_votes': dict(weighted),
        'sources': {k: sorted(v) for k, v in sources.items()},
        'per_doc': per_doc,
    }


def main():
    con = sqlite3.connect('data/tutelas.db')
    con.row_factory = sqlite3.Row
    out_dir = Path('data/datasets/responsable_desacato')
    out_dir.mkdir(parents=True, exist_ok=True)

    # Todos los cases con incidente=SI (o cualquier nivel) o con doc de incidente.
    # Esto cubre tanto los que tienen auto formal como los que tienen solo email/respuesta.
    cases = con.execute("""SELECT DISTINCT c.id, c.folder_name, c.responsable_desacato, c.incidente
                           FROM cases c
                           LEFT JOIN documents d ON d.case_id=c.id
                           WHERE c.incidente='SI' OR c.incidente_2='SI' OR c.incidente_3='SI'
                              OR d.doc_type IN ('INCIDENTE_DESACATO','AUTO_INCIDENTE')
                           ORDER BY c.id""").fetchall()
    rows = []
    jsonl_path = out_dir / 'dataset.jsonl'
    with jsonl_path.open('w', encoding='utf-8') as fjsonl:
        for c in cases:
            result = extract_for_case(con, c['id'])
            row = {
                'case_id': c['id'],
                'folder': c['folder_name'],
                'incidente': c['incidente'],
                'label_current': c['responsable_desacato'],
                'label_proposed': result['label'],
                'confidence': result['confidence'],
                'pattern': result.get('pattern'),
                'fragment': result.get('fragment'),
                'votes': result['votes'],
                'per_doc': result['per_doc'],
            }
            rows.append(row)
            fjsonl.write(json.dumps(row, ensure_ascii=False) + '\n')

    # CSV resumen
    csv_path = out_dir / 'summary.csv'
    with csv_path.open('w', encoding='utf-8', newline='') as fc:
        w = csv.writer(fc)
        w.writerow(['case_id', 'folder', 'label_current', 'label_proposed', 'confidence', 'pattern', 'agrees'])
        for r in rows:
            current = (r['label_current'] or '').strip()
            prop = (r['label_proposed'] or '').strip()
            agrees = '' if not current or not prop else (
                'YES' if _strip_accents_upper(current) in _strip_accents_upper(prop) or
                         _strip_accents_upper(prop) in _strip_accents_upper(current) else 'NO'
            )
            w.writerow([r['case_id'], r['folder'], current, prop, r['confidence'], r['pattern'], agrees])

    # Stats
    total = len(rows)
    n_label = sum(1 for r in rows if r['label_proposed'])
    n_has_current = sum(1 for r in rows if r['label_current'])
    agrees = sum(1 for r in rows if r['label_current'] and r['label_proposed']
                 and (_strip_accents_upper(r['label_current']) in _strip_accents_upper(r['label_proposed'])
                      or _strip_accents_upper(r['label_proposed']) in _strip_accents_upper(r['label_current'])))
    n_high = sum(1 for r in rows if r['confidence'] >= 0.7 and r['label_proposed'])
    n_low = sum(1 for r in rows if 0 < r['confidence'] < 0.7 and r['label_proposed'])
    print(f"Cases con autos de incidente: {total}")
    print(f"  Con etiqueta propuesta:     {n_label} ({n_label/max(1,total):.0%})")
    print(f"  Con etiqueta actual en DB:  {n_has_current}")
    print(f"  Acuerdan actual==propuesta: {agrees}/{n_has_current}")
    print(f"  Alta confianza ≥0.7:        {n_high}")
    print(f"  Baja confianza <0.7:        {n_low}")
    print(f"\nDataset escrito:")
    print(f"  {jsonl_path}")
    print(f"  {csv_path}")
    con.close()


if __name__ == '__main__':
    main()
