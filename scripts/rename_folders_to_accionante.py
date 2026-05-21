#!/usr/bin/env python3
"""Renombra carpetas SIN_ACCIONANTE → '<rad_corto> <ACCIONANTE>' de forma atómica.

- Mueve el directorio en disco, reescribe cases.folder_name/folder_path y el
  prefijo de cada documents.file_path. Normaliza homóglifos cirílicos en el
  nombre del accionante (y corrige el campo accionante en DB si cambia).
- Dry-run por defecto. --apply ejecuta (hace backup de la DB antes).
- Colisión (destino ya existe) o doc fuera del folder_path => caso se SALTA.
- Si una operación de disco falla, revierte los moves ya hechos y aborta.

Uso:
  ./venv/bin/python scripts/rename_folders_to_accionante.py            # dry-run
  ./venv/bin/python scripts/rename_folders_to_accionante.py --apply
"""
import sqlite3, os, re, sys, shutil, datetime

DB = "data/tutelas.db"
APPLY = "--apply" in sys.argv

# IDs renombrables confirmados (excluye sin-accionante, sin-rad y flags de revisión)
TARGET_IDS = [29, 200, 288, 292, 321, 325, 338, 404, 406, 407, 408, 409,
              411, 413, 414, 415, 440, 444, 447, 450, 457, 461, 465, 470, 477]

# Cirílico -> Latín (homóglifos comunes de OCR)
HOMO = {
    'А':'A','В':'B','С':'C','Е':'E','Н':'H','К':'K','М':'M','О':'O','Р':'P',
    'Т':'T','Х':'X','У':'Y','І':'I','Ј':'J','Ѕ':'S','а':'a','е':'e','о':'o',
    'с':'c','р':'p','х':'x','у':'y','к':'k','м':'m','н':'h','т':'t','в':'b',
}

def delatin(s: str) -> str:
    return ''.join(HOMO.get(ch, ch) for ch in (s or ''))

def clean(s: str) -> str:
    s = delatin(s).strip()
    s = ' '.join(s.split())
    s = re.sub(r'[/\\:*?"<>|]', '', s)   # chars ilegales en nombre de carpeta
    return s

def rad_prefix(folder_name: str) -> str:
    """Primer radicado corto 'YYYY-NNNNN' del folder (descarta extras tipo
    código de juzgado que se hayan colado, p.ej. '2026-00059 408801')."""
    m = re.search(r'\d{4}-\d{4,5}', folder_name or '')
    if m:
        return m.group(0)
    # fallback: lo anterior a SIN_ACCIONANTE / '['
    parts = re.split(r'\s*(?:SIN[ _]ACCIONANTE|\[)', folder_name, maxsplit=1)
    return parts[0].strip()


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    plan = []   # (cid, old_path, new_path, new_name, acc_clean, acc_db_old, ndocs, note)
    for cid in TARGET_IDS:
        r = cur.execute("SELECT id,accionante,folder_name,folder_path FROM cases WHERE id=?", (cid,)).fetchone()
        old_path = r['folder_path']
        acc_db = r['accionante']
        acc = clean(acc_db)
        rad = rad_prefix(r['folder_name'] or '')
        new_name = f"{rad} {acc}".strip()
        parent = os.path.dirname(old_path)
        new_path = os.path.join(parent, new_name)
        notes = []
        if not os.path.isdir(old_path):
            notes.append("ORIGEN-NO-EXISTE")
        if os.path.exists(new_path) and os.path.abspath(new_path) != os.path.abspath(old_path):
            notes.append("DESTINO-COLISIONA")
        if delatin(acc_db or '') != (acc_db or ''):
            notes.append("FIX-HOMOGLIFO")
        # docs fuera del folder_path
        docs = cur.execute("SELECT id,file_path FROM documents WHERE case_id=?", (cid,)).fetchall()
        outside = [d['id'] for d in docs if d['file_path'] and not d['file_path'].startswith(old_path)]
        if outside:
            notes.append(f"DOCS-FUERA={outside}")
        plan.append((cid, old_path, new_path, new_name, acc, acc_db, len(docs), notes))

    # Mostrar plan
    print(f"{'='*100}\nPLAN DE RENOMBRADO ({len(plan)} casos) — modo {'APPLY' if APPLY else 'DRY-RUN'}\n{'='*100}")
    blockers = []
    for cid, old, new, name, acc, acc_db, nd, notes in plan:
        flag = ' | '.join(notes) if notes else 'OK'
        if any(n.startswith(('ORIGEN-NO-EXISTE','DESTINO-COLISIONA','DOCS-FUERA')) for n in notes):
            blockers.append(cid)
        print(f"c{cid:>3} [{nd:>2} docs] {flag}")
        print(f"      {os.path.basename(old)!r}")
        print(f"   -> {name!r}")
        if 'FIX-HOMOGLIFO' in notes:
            print(f"      accionante DB: {acc_db!r} -> {acc!r}")

    if blockers:
        print(f"\n⚠️  {len(blockers)} casos con bloqueadores: {blockers} — se SALTAN en apply.")

    if not APPLY:
        print("\n(dry-run) nada modificado. Re-ejecuta con --apply para aplicar.")
        con.close()
        return

    # Backup
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{DB}.bak_pre_rename_folders_{ts}"
    shutil.copy2(DB, bak)
    print(f"\nbackup DB -> {bak}")

    done_moves = []  # (old, new) ya movidos para posible reversa
    try:
        for cid, old, new, name, acc, acc_db, nd, notes in plan:
            if cid in blockers:
                print(f"  SKIP c{cid} (bloqueador)")
                continue
            shutil.move(old, new)
            done_moves.append((old, new))
            # DB updates
            cur.execute("UPDATE cases SET folder_name=?, folder_path=?, accionante=?, updated_at=? WHERE id=?",
                        (name, new, acc, datetime.datetime.now().isoformat(), cid))
            cur.execute(
                "UPDATE documents SET file_path = ? || substr(file_path, ?) WHERE case_id=? AND file_path LIKE ?",
                (new, len(old) + 1, cid, old + '%'))
            cur.execute(
                "INSERT INTO audit_log (case_id,field_name,old_value,new_value,action,source,timestamp,entity_type,entity_id,description) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (cid, 'folder_name', os.path.basename(old), name, 'RENAME', 'manual',
                 datetime.datetime.now().isoformat(), 'case', cid,
                 f'Rename folder SIN_ACCIONANTE -> accionante. Docs file_path reescritos.'))
            print(f"  OK c{cid} -> {name!r}")
        con.commit()
        print(f"\n✅ commit OK. {len(done_moves)} carpetas renombradas.")
    except Exception as e:
        con.rollback()
        print(f"\n❌ ERROR: {e}\nRevirtiendo {len(done_moves)} moves de disco...")
        for old, new in reversed(done_moves):
            try:
                shutil.move(new, old)
            except Exception as e2:
                print(f"   no pude revertir {new} -> {old}: {e2}")
        print("DB con rollback. Revisa el backup si hace falta.")
        raise
    finally:
        con.close()


if __name__ == "__main__":
    main()
