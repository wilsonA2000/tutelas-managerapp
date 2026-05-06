"""Imprime contexto detallado de los 20 docs estratificados para Fase 2."""
import json
import sqlite3
from pathlib import Path

ROOT = Path('/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026/tutelas-app')
sample = json.loads((ROOT / 'data/entropy_sample20.json').read_text())

con = sqlite3.connect(ROOT / 'data/tutelas.db')
con.row_factory = sqlite3.Row

print('=' * 100)
for i, r in enumerate(sample, 1):
    doc_id = int(r['doc_id'])
    case_id = int(r['case_id'])
    target_case_id = int(r['target_case_id']) if r['target_case_id'] else None

    doc = con.execute(
        'SELECT id, filename, doc_type, file_path, verificacion, verificacion_detalle, '
        'extracted_text, email_id FROM documents WHERE id=?',
        (doc_id,),
    ).fetchone()
    case = con.execute(
        'SELECT id, folder_name, accionante, accionados, radicado_23_digitos '
        'FROM cases WHERE id=?',
        (case_id,),
    ).fetchone()
    target = None
    if target_case_id:
        target = con.execute(
            'SELECT id, folder_name, accionante, accionados, radicado_23_digitos '
            'FROM cases WHERE id=?',
            (target_case_id,),
        ).fetchone()

    text_snippet = (doc['extracted_text'] or '')[:1200].replace('\n', ' ').replace('  ', ' ')

    print(f'\n[{i:2d}/20] verdict_auto={r["verdict_proposed"]}')
    print(f'  DOC #{doc["id"]} status={doc["verificacion"]} type={doc["doc_type"]}')
    print(f'    filename: {doc["filename"]}')
    print(f'    detalle:  {(doc["verificacion_detalle"] or "")[:120]}')
    print(f'  CASE actual #{case["id"]}: {case["folder_name"]}')
    print(f'    accionante: {case["accionante"]}')
    print(f'    accionados: {(case["accionados"] or "")[:80]}')
    print(f'    rad23: {case["radicado_23_digitos"]}')
    if target:
        print(f'  TARGET propuesto #{target["id"]}: {target["folder_name"]}')
        print(f'    accionante: {target["accionante"]}')
        print(f'    rad23: {target["radicado_23_digitos"]}')
    print(f'  rad23s_found: {r["rad23s_found"][:80]}')
    print(f'  rad_cortos_found: {r["rad_cortos_found"][:60]}')
    print(f'  TEXT preview: {text_snippet[:600]}')
    print('-' * 100)
con.close()
