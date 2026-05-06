"""Detector v6.0.18D — Patrón INGRID: docs SOSPECHOSO cuyo filename
menciona accionante de OTRO case en la DB.

Estrategia:
  1. Indexar palabras significativas (≥4 chars, no stopwords) de cada accionante.
  2. Para cada doc SOSPECHOSO/NO_PERTENECE en cases COMPLETO:
     - Extraer palabras significativas del filename
     - Calcular score = #palabras compartidas con accionante de otro case
  3. Reportar matches con score≥3 (alta confianza).

Uso:
    python3 scripts/find_pattern_ingrid.py            # solo reporte
    python3 scripts/find_pattern_ingrid.py --execute  # mueve docs
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

STOPWORDS = {
    "ACCION", "TUTELA", "FALLO", "AUTO", "SENTENCIA", "OFICIO", "RESPUESTA", "FOREST",
    "GMAIL", "EMAIL", "NOTIFICA", "ADMITE", "CONCEDE", "NIEGA", "IMPUGNA", "INCIDENTE",
    "DESACATO", "RV", "RE", "URGENTE", "CONTESTACION", "ESCRITO", "DEMANDA", "ANEXOS",
    "CERTIFICACION", "DOCUMENTO", "RADICADO", "RADICACION", "NOTIFICACION", "CITACION",
    "PROVIDENCIA", "REQUERIMIENTO", "EDUCACION", "SANTANDER", "GOBERNACION", "SECRETARIA",
    "MUNICIPAL", "PERSONERIA", "ALCALDIA", "JUZGADO", "TRIBUNAL", "PROMISCUO", "CIRCUITO",
    "PENAL", "CIVIL", "FAMILIA", "CONOCIMIENTO", "SEGUNDA", "PRIMERA", "INSTANCIA",
    "DISTRITAL", "DEPARTAMENTAL", "DEPARTAMENTO", "NACIONAL", "PARA", "CON", "SIN", "DEL",
    "DE", "LA", "EL", "LOS", "LAS", "MENOR", "REPRESENTANTE", "REPRESENTACION", "AGENTE",
    "OFICIOSO", "LEGAL", "COMO", "NOMBRE", "ACTA", "GRADO", "TITULOS", "DOCENTES",
    "ESTUDIANTES", "COLEGIO", "ESCUELA", "INSTITUCION", "DOCENTE", "RECTOR", "OFICIAL",
    "PUBLICO", "PRIVADO", "COMPLETO", "NUEVA", "EPS", "SALUD", "FINANCIERA",
    "ADMINISTRATIVA", "FECHA", "HORA", "PAGINA", "FOLIO", "ANEXO", "COPIA", "PLANTILLA",
    "FORMATO", "CARTA", "REF", "ASUNTO", "PROC", "TERCERO", "CONSEC", "CONTROL",
    "GARANTIAS", "FUNCIONES", "BUCARAMANGA", "BARRANCABERMEJA", "CONCEPCION",
    "FLORIDABLANCA", "PIEDECUESTA", "GIRON", "SAN", "GIL", "BETULIA", "SOCORRO", "OIBA",
    "GAMBITA", "CIMITARRA", "MERGED", "MOVED", "ACCIONANTE", "ACCIONADO",
    "MINISTERIO", "CONSEJO", "SECCIONAL", "DESPACHO",
    "PARRA", "SUAREZ", "JIMENEZ", "RODRIGUEZ", "MARTINEZ", "GOMEZ", "LOPEZ", "HERNANDEZ",
    "SIERRA", "DIAZ", "PEREZ", "CASTRO", "RAMIREZ", "MORALES", "SOLANO", "BOHORQUEZ",
    "AMADOR", "CABRERA", "SERRANO", "GARCIA", "TORRES",
    "CORREO", "ELECTRONICO", "CONTACTO", "DATOS", "NUMERO", "RESOLUCION", "DECRETO",
    "RES", "NRO", "NUM", "REPRESENT", "REGRESO", "ENVIADOS", "BANDEJA", "ENTRADA",
    "AUTORIDAD", "ENTIDAD", "FUNCIONARIO", "PERSONERO", "PERSONERA", "JEFE", "DIRECTOR",
    "ABOGADO", "ABOGADA", "MAGISTRADO", "TRASLADO", "NOTIFICADOR",
}

MIN_SCORE = 3


def norm(s):
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").upper()


def find_candidates(db_path):
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    acc_words_to_case = defaultdict(set)
    all_cases = list(con.execute(
        "SELECT id, accionante FROM cases WHERE accionante IS NOT NULL AND processing_status='COMPLETO'"
    ))
    for c in all_cases:
        words = [w for w in re.findall(r'[A-ZÁÉÍÓÚÑ]{4,}', norm(c['accionante'])) if w not in STOPWORDS]
        for w in words[:5]:
            acc_words_to_case[w].add(c['id'])
    docs = con.execute("""
        SELECT d.id, d.case_id, d.filename, d.verificacion FROM documents d
        JOIN cases c ON c.id=d.case_id
        WHERE d.verificacion IN ('SOSPECHOSO','NO_PERTENECE') AND c.processing_status='COMPLETO'
    """).fetchall()
    candidates = []
    for d in docs:
        fn_words = set(w for w in re.findall(r'[A-ZÁÉÍÓÚÑ]{4,}', norm(d['filename'] or '')) if w not in STOPWORDS)
        if len(fn_words) < 2:
            continue
        matched = defaultdict(int)
        for w in fn_words:
            for cid in acc_words_to_case.get(w, set()):
                if cid != d['case_id']:
                    matched[cid] += 1
        strong = {cid: cnt for cid, cnt in matched.items() if cnt >= MIN_SCORE}
        if not strong:
            continue
        best_cid = max(strong, key=strong.get)
        best_score = strong[best_cid]
        current = next((c for c in all_cases if c['id'] == d['case_id']), None)
        if current and current['accionante']:
            cw = set(w for w in re.findall(r'[A-ZÁÉÍÓÚÑ]{4,}', norm(current['accionante'])) if w not in STOPWORDS)
            if len(cw & fn_words) >= best_score:
                continue
        candidates.append({
            'doc_id': d['id'], 'current_case': d['case_id'], 'filename': d['filename'],
            'verificacion': d['verificacion'], 'best_target_case': best_cid, 'score': best_score,
        })
    con.close()
    return candidates


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--execute', action='store_true')
    p.add_argument('--db', default=str(ROOT / 'data/tutelas.db'))
    args = p.parse_args()
    cands = find_candidates(Path(args.db))
    print(f'Candidatos: {len(cands)}')
    for c in cands[:30]:
        print(f"  doc {c['doc_id']:5d} score={c['score']} → case {c['best_target_case']}")
        print(f"    fn: {c['filename'][:75]}")
    if args.execute and cands:
        from backend.database.database import SessionLocal
        from backend.services.sibling_mover import move_document_or_package
        ok = err = 0
        for c in cands:
            db = SessionLocal()
            try:
                r = move_document_or_package(db, c['doc_id'], c['best_target_case'],
                                              reason="find_pattern_ingrid_v6018D")
                if r.get('errors'):
                    err += 1; db.rollback()
                else:
                    db.commit(); ok += 1
            finally:
                db.close()
        print(f'\nMovidos: {ok} | Errores: {err}')


if __name__ == '__main__':
    main()
