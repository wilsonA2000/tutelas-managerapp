#!/usr/bin/env python3
"""
Auditoría completa del estado de tutelas-app.
Reporta TODAS las anomalías de salud en una pasada sin tocar la DB ni disco.

Salidas:
  data/audit_estado_completo.json   — dump JSON con todos los buckets
  data/audit_estado_completo.txt    — resumen legible
"""
from __future__ import annotations
import json, re, sqlite3
from collections import defaultdict, Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "tutelas.db"
BASE_DIR = Path("/home/wilsonarguello/Documentos/GOBERNACION DE SANTANDER/V9_PRODUCCION")
OUT_JSON = ROOT / "data" / "audit_estado_completo.json"
OUT_TXT = ROOT / "data" / "audit_estado_completo.txt"

CANONICAL_ABOGADOS = json.loads((ROOT / "backend" / "data" / "abogados_canonicos.json").read_text())
CANON_NAMES = set()
for a in CANONICAL_ABOGADOS:
    CANON_NAMES.add(a['canonical'].upper())
    for al in a.get('aliases', []):
        CANON_NAMES.add(al.upper())

FOLDER_JUNK_PATTERNS = [
    r'\bCORREO ELECTRONI\b', r'\bACCIONANDO\b', r'\bAGENTE OFICIOS', r'\bFAVOR INFORMARLO\b',
    r'\bSE REMITE\b', r'\bACCIONADA\b', r'\bEMAIL\b', r'\bAGENCIADA\b', r'\bDOCUMENTOS\b',
    r'\bMINISTERIO DE EDUCACION NACIONAL NOTIFICACIONESJUD\b',
    r'\bY OTROS?\s*$', r'\bSEDE\s*$', r'\bCC\s*$', r'\bPERSONERO\b', r'\bCORDIAL SALUDO\b',
    r'\bIDENTIFICADO\b', r'\bSEÑOR\b', r'\bDR\.?\b', r'\bABOGADO\b',
]
JUNK_RE = re.compile('|'.join(FOLDER_JUNK_PATTERNS), re.I)

CERTIFICADOS = {'BUCARAMANGA', 'FLORIDABLANCA', 'GIRON', 'GIRÓN', 'PIEDECUESTA', 'BARRANCABERMEJA'}


def main():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.cursor()

    audit = {}

    # 1) Conteos base
    cur.execute("SELECT COUNT(*) FROM cases")
    audit['total_cases'] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM documents")
    audit['total_docs'] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM emails")
    audit['total_emails'] = cur.fetchone()[0]

    # 2) FK violations
    cur.execute("PRAGMA foreign_key_check")
    audit['fk_violations'] = [tuple(r) for r in cur.fetchall()]

    # 3) Shells (cases sin docs)
    cur.execute("""
        SELECT c.id, c.folder_name, c.accionante, c.processing_status
        FROM cases c LEFT JOIN documents d ON d.case_id=c.id
        WHERE d.id IS NULL
    """)
    audit['shells_sin_docs'] = [dict(r) for r in cur.fetchall()]

    # 4) Huérfanos (docs sin case válido) — FK_ON debería prevenir, pero chequeo
    cur.execute("""
        SELECT d.id, d.filename, d.case_id FROM documents d
        LEFT JOIN cases c ON c.id=d.case_id WHERE c.id IS NULL
    """)
    audit['docs_huerfanos'] = [dict(r) for r in cur.fetchall()]

    # 5) folder_path roto o NULL
    cur.execute("SELECT id, folder_name, folder_path FROM cases")
    cases_folder_issues = []
    cases_folder_paths = {}  # path -> [case_ids]
    for r in cur.fetchall():
        cid, fn, fp = r['id'], r['folder_name'], r['folder_path']
        if not fp:
            cases_folder_issues.append({'case_id': cid, 'folder_name': fn, 'issue': 'NULL_folder_path'})
        elif not Path(fp).exists():
            cases_folder_issues.append({'case_id': cid, 'folder_name': fn, 'folder_path': fp, 'issue': 'PATH_NOT_FOUND'})
        else:
            cases_folder_paths.setdefault(fp, []).append(cid)
    audit['cases_folder_path_issues'] = cases_folder_issues
    audit['folders_compartidos'] = {p: ids for p, ids in cases_folder_paths.items() if len(ids) > 1}

    # 6) Folders físicos en disco sin case en DB
    if BASE_DIR.exists():
        all_folders_db = {Path(r['folder_path']).name for r in conn.execute("SELECT folder_path FROM cases WHERE folder_path IS NOT NULL")}
        all_folders_disk = {p.name for p in BASE_DIR.iterdir() if p.is_dir()}
        audit['folders_disco_sin_case'] = sorted(all_folders_disk - all_folders_db)
        audit['cases_db_sin_folder_disco'] = sorted(all_folders_db - all_folders_disk)
    else:
        audit['folders_disco_sin_case'] = []
        audit['cases_db_sin_folder_disco'] = []

    # 7) file_path roto en documents
    cur.execute("SELECT id, case_id, filename, file_path FROM documents WHERE file_path IS NOT NULL")
    file_path_broken = []
    for r in cur.fetchall():
        if not Path(r['file_path']).exists():
            file_path_broken.append(dict(r))
    audit['docs_file_path_roto'] = file_path_broken

    # 8) Conflación rad-corto cross-juzgado
    # Derivar rad_corto desde rad23 (formato (20\d{2})(\d{5}))
    rad_corto_pat = re.compile(r'(20\d{2})(\d{5})')
    cases_by_rad = defaultdict(list)
    cur.execute("SELECT id, folder_name, accionante, juzgado, radicado_23_digitos FROM cases")
    for r in cur.fetchall():
        rad = r['radicado_23_digitos'] or ''
        m = rad_corto_pat.search(rad)
        if m:
            rad_corto = f'{m.group(1)}-{m.group(2)}'
        else:
            # Intentar derivar del folder_name (formato AAAA-NNNNN al inicio)
            m2 = re.match(r'^(\d{4})-(\d{5})', r['folder_name'] or '')
            rad_corto = f'{m2.group(1)}-{m2.group(2)}' if m2 else None
        if rad_corto:
            cases_by_rad[rad_corto].append({
                'id': r['id'], 'folder': r['folder_name'], 'accionante': r['accionante'], 'juzgado': r['juzgado']
            })
    conflict_rad = {}
    for rc, lst in cases_by_rad.items():
        if len(lst) > 1:
            juzgados = {(c['juzgado'] or '').strip().upper() for c in lst}
            if len(juzgados) > 1:
                conflict_rad[rc] = lst
    audit['conflacion_rad_corto_cross_juzgado'] = conflict_rad

    # 9) DESCONOCIDO totales y por case
    cur.execute("SELECT COUNT(*) FROM documents WHERE doc_type='DESCONOCIDO'")
    audit['desconocido_total'] = cur.fetchone()[0]
    cur.execute("""
        SELECT case_id, COUNT(*) AS n FROM documents WHERE doc_type='DESCONOCIDO'
        GROUP BY case_id ORDER BY n DESC LIMIT 30
    """)
    audit['desconocido_top_cases'] = [dict(r) for r in cur.fetchall()]

    # 10) extracted_text vacío
    cur.execute("""
        SELECT id, case_id, filename, doc_type FROM documents
        WHERE (extracted_text IS NULL OR LENGTH(extracted_text) = 0)
        AND file_path IS NOT NULL
    """)
    audit['docs_text_vacio'] = [dict(r) for r in cur.fetchall()]

    # 11) abogado_responsable no canónico
    cur.execute("SELECT id, abogado_responsable, abogado_canonical FROM cases WHERE abogado_responsable IS NOT NULL")
    non_canon = []
    for r in cur.fetchall():
        nresp = (r['abogado_responsable'] or '').upper().strip()
        ncan = (r['abogado_canonical'] or '').upper().strip()
        in_canon = nresp in CANON_NAMES
        canon_match = ncan in CANON_NAMES
        if not in_canon:
            non_canon.append({'case_id': r['id'], 'abogado_responsable': r['abogado_responsable'],
                              'abogado_canonical': r['abogado_canonical'], 'issue': 'NON_CANONICAL_RESP'})
        elif ncan and not canon_match:
            non_canon.append({'case_id': r['id'], 'abogado_responsable': r['abogado_responsable'],
                              'abogado_canonical': r['abogado_canonical'], 'issue': 'NON_CANONICAL_CAN'})
        elif ncan and nresp != ncan and ncan not in CANON_NAMES:
            non_canon.append({'case_id': r['id'], 'abogado_responsable': r['abogado_responsable'],
                              'abogado_canonical': r['abogado_canonical'], 'issue': 'MISMATCH'})
    audit['abogado_no_canonico'] = non_canon

    # 12) Sentencias sin sentido o sentido sin fecha
    cur.execute("""
        SELECT id, folder_name, sentido_fallo_1st, fecha_fallo_1st, sentido_fallo_2nd, fecha_fallo_2nd
        FROM cases
    """)
    fallo_incons = []
    for r in cur.fetchall():
        s1, f1 = r['sentido_fallo_1st'], r['fecha_fallo_1st']
        s2, f2 = r['sentido_fallo_2nd'], r['fecha_fallo_2nd']
        if (s1 and not f1):
            fallo_incons.append({'case_id': r['id'], 'folder': r['folder_name'], 'issue': 'sentido_1st sin fecha'})
        if (f1 and not s1):
            fallo_incons.append({'case_id': r['id'], 'folder': r['folder_name'], 'issue': 'fecha_1st sin sentido'})
        if (s2 and not f2):
            fallo_incons.append({'case_id': r['id'], 'folder': r['folder_name'], 'issue': 'sentido_2nd sin fecha'})
        if (f2 and not s2):
            fallo_incons.append({'case_id': r['id'], 'folder': r['folder_name'], 'issue': 'fecha_2nd sin sentido'})
    audit['fallo_inconsistente'] = fallo_incons

    # 13) folder_name con basura
    cur.execute("SELECT id, folder_name FROM cases WHERE folder_name IS NOT NULL")
    sucios = []
    for r in cur.fetchall():
        fn = r['folder_name']
        m = JUNK_RE.search(fn)
        if m:
            sucios.append({'case_id': r['id'], 'folder_name': fn, 'junk_match': m.group(0)})
    audit['folder_names_sucios'] = sucios

    # 14) Cases en municipio certificado (no competencia SED Santander)
    cur.execute("SELECT id, folder_name, ciudad, accionados, estado FROM cases")
    no_competencia = []
    for r in cur.fetchall():
        ciudad = (r['ciudad'] or '').upper().strip()
        accionados = (r['accionados'] or '').upper()
        if ciudad in CERTIFICADOS:
            # Marca si SED Santander es accionada (sospecha falta legitimación)
            if 'SECRETAR' in accionados and 'SANTANDER' in accionados:
                no_competencia.append({'case_id': r['id'], 'folder': r['folder_name'],
                                       'ciudad': ciudad, 'estado': r['estado']})
    audit['posible_falta_legitimacion'] = no_competencia

    # 15) Estado vs fecha consistencia
    cur.execute("""
        SELECT id, folder_name, estado, incidente, decision_incidente
        FROM cases
        WHERE (incidente='NO' AND decision_incidente IS NOT NULL AND decision_incidente != '')
           OR (incidente='SI' AND decision_incidente IS NULL)
    """)
    audit['incidente_inconsistente'] = [dict(r) for r in cur.fetchall()]

    # 16) Cases con rad23 NULL o vacío
    cur.execute("SELECT id, folder_name FROM cases WHERE radicado_23_digitos IS NULL OR radicado_23_digitos=''")
    audit['cases_sin_rad23'] = [dict(r) for r in cur.fetchall()]

    # 17) Folders vacíos físicamente
    folders_vacios = []
    if BASE_DIR.exists():
        for p in BASE_DIR.iterdir():
            if p.is_dir() and not any(p.iterdir()):
                folders_vacios.append(p.name)
    audit['folders_disco_vacios'] = folders_vacios

    # Escribir JSON
    OUT_JSON.write_text(json.dumps(audit, indent=2, ensure_ascii=False, default=str))

    # Resumen TXT
    summary = []
    summary.append(f"=== AUDIT ESTADO COMPLETO @ {sqlite3.connect(':memory:').execute('SELECT datetime()').fetchone()[0]} ===\n")
    summary.append(f"Total cases:   {audit['total_cases']}")
    summary.append(f"Total docs:    {audit['total_docs']}")
    summary.append(f"Total emails:  {audit['total_emails']}")
    summary.append(f"FK violations: {len(audit['fk_violations'])}\n")
    summary.append(f"--- INTEGRIDAD ---")
    summary.append(f"  Shells (case sin docs):              {len(audit['shells_sin_docs'])}")
    summary.append(f"  Docs huérfanos (sin case):           {len(audit['docs_huerfanos'])}")
    summary.append(f"  Cases con folder_path NULL/roto:     {len(audit['cases_folder_path_issues'])}")
    summary.append(f"  Folders físicos sin case en DB:      {len(audit['folders_disco_sin_case'])}")
    summary.append(f"  Cases DB sin folder físico:          {len(audit['cases_db_sin_folder_disco'])}")
    summary.append(f"  docs con file_path roto:             {len(audit['docs_file_path_roto'])}")
    summary.append(f"  Folders compartidos (>1 case):       {len(audit['folders_compartidos'])}")
    summary.append(f"  Folders disco vacíos:                {len(audit['folders_disco_vacios'])}")
    summary.append(f"\n--- CONFLACIONES Y CALIDAD ---")
    summary.append(f"  Conflación rad-corto cross-juzgado:  {len(audit['conflacion_rad_corto_cross_juzgado'])}")
    summary.append(f"  Cases sin rad23:                     {len(audit['cases_sin_rad23'])}")
    summary.append(f"\n--- DOC TYPES Y TEXTO ---")
    summary.append(f"  DESCONOCIDO total:                   {audit['desconocido_total']}")
    summary.append(f"  Docs con extracted_text vacío:       {len(audit['docs_text_vacio'])}")
    summary.append(f"\n--- ABOGADOS Y FALLOS ---")
    summary.append(f"  abogado_responsable no canónico:     {len(audit['abogado_no_canonico'])}")
    summary.append(f"  Fallo inconsistente (sentido/fecha): {len(audit['fallo_inconsistente'])}")
    summary.append(f"  Incidente inconsistente:             {len(audit['incidente_inconsistente'])}")
    summary.append(f"\n--- COMPETENCIA ---")
    summary.append(f"  Posible falta legitimación pasiva:   {len(audit['posible_falta_legitimacion'])}")
    summary.append(f"\n--- FOLDER NAMES ---")
    summary.append(f"  folder_name con basura:              {len(audit['folder_names_sucios'])}")
    OUT_TXT.write_text('\n'.join(summary))
    print('\n'.join(summary))
    print(f"\n-> {OUT_JSON.name}")
    print(f"-> {OUT_TXT.name}")


if __name__ == '__main__':
    main()
