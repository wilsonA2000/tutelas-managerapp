#!/usr/bin/env python3
"""
Aplica el plan de los 9 cases nuevos/merge desde cuarentena.

Lee data/plan_9_nuevos_cases.json. Para cada item:
  - CREATE_NEW: INSERT case + mkdir folder + mv archivos + INSERT documents
  - MERGE_INTO_EXISTING: mv archivos al target + INSERT documents + UPDATE target

Uso:
  python3 scripts/apply_9_nuevos_cases.py            # dry-run
  python3 scripts/apply_9_nuevos_cases.py --commit
"""
from __future__ import annotations
import argparse, hashlib, json, re, shutil, sqlite3, unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "tutelas.db"
PLAN = ROOT / "data" / "plan_9_nuevos_cases.json"
BASE_DIR = Path("/home/wilsonarguello/Documentos/GOBERNACION DE SANTANDER/V9_PRODUCCION")
QUAR_DIR = ROOT / "data" / "quarantine_misfiled"

ALLOWED_COLS = {
    'radicado_23_digitos', 'radicado_forest', 'abogado_responsable', 'accionante',
    'accionados', 'vinculados', 'derecho_vulnerado', 'juzgado', 'ciudad', 'fecha_ingreso',
    'asunto', 'pretensiones', 'oficina_responsable', 'direccion', 'grupo', 'equipo',
    'abogado_canonical', 'dependencia_canonical', 'estado', 'fecha_respuesta',
    'sentido_fallo_1st', 'fecha_fallo_1st', 'impugnacion', 'quien_impugno',
    'forest_impugnacion', 'juzgado_2nd', 'sentido_fallo_2nd', 'fecha_fallo_2nd',
    'incidente', 'fecha_apertura_incidente', 'responsable_desacato', 'decision_incidente',
    'observaciones', 'categoria_tematica', 'folder_name', 'origen', 'estado_incidente',
    'processing_status', 'parte_resolutiva_1st', 'parte_resolutiva_2nd', 'folder_path',
    'abogado_incidente',
}

DOC_COLS_TEMPLATE = {
    'filename': None, 'file_path': None, 'doc_type': None,
    'file_size': 0, 'extraction_method': 'cuarentena_recovered',
}

def normalize_for_folder(text: str) -> str:
    """Quita tildes, valida caracteres seguros para nombre de folder."""
    nfkd = unicodedata.normalize('NFKD', text)
    ascii_only = nfkd.encode('ASCII', 'ignore').decode('ASCII')
    return ''.join(c for c in ascii_only if c.isalnum() or c in ' -_').strip()

def file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()

class Applier:
    def __init__(self, commit: bool):
        self.commit = commit
        self.conn = sqlite3.connect(str(DB))
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.cur = self.conn.cursor()
        self.stats = {
            'create_new': 0, 'merge_into': 0, 'docs_inserted': 0,
            'docs_skipped_dup': 0, 'docs_missing': 0, 'folders_created': 0,
            'errors': 0,
        }
        self.created_case_ids: list[int] = []

    def emit(self, line: str):
        print(line)

    def _quar_path(self, name: str) -> Path:
        # Allow subdirs under quarantine, search recursively
        direct = QUAR_DIR / name
        if direct.exists():
            return direct
        for sub in QUAR_DIR.iterdir():
            if sub.is_dir():
                candidate = sub / name
                if candidate.exists():
                    return candidate
        return direct

    def _insert_case(self, fields: dict) -> int | None:
        cols = {k: v for k, v in fields.items() if k in ALLOWED_COLS}
        # Forzar valores por defecto si no vienen
        cols.setdefault('processing_status', 'COMPLETO')
        cols.setdefault('origen', 'TUTELA')
        cols.setdefault('estado', 'ACTIVO')
        cols['created_at'] = datetime.utcnow().isoformat()
        cols['updated_at'] = cols['created_at']
        keys = list(cols.keys())
        ph = ', '.join('?' for _ in keys)
        sql = f"INSERT INTO cases ({', '.join(keys)}) VALUES ({ph})"
        if self.commit:
            self.cur.execute(sql, list(cols.values()))
            new_id = self.cur.lastrowid
            return new_id
        # En dry-run: simular el ID que tendría
        self.cur.execute("SELECT COALESCE(MAX(id),0)+1+? FROM cases", (len(self.created_case_ids),))
        return self.cur.fetchone()[0]

    def _insert_doc(self, case_id: int, file_path: Path, filename: str, doc_type: str, file_hash: str):
        size = file_path.stat().st_size if file_path.exists() else 0
        sql = """INSERT INTO documents (case_id, filename, file_path, doc_type, file_size,
                 extraction_method, file_hash, extraction_date)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
        params = (case_id, filename, str(file_path), doc_type, size,
                  'cuarentena_recovered', file_hash, datetime.utcnow().isoformat())
        if self.commit:
            self.cur.execute(sql, params)
        self.stats['docs_inserted'] += 1

    def apply_create_new(self, item: dict):
        cf = item['case_fields']
        rad_corto_field = cf.get('radicado_corto') or ''
        rad23 = cf.get('radicado_23_digitos') or ''
        accionante = cf.get('accionante', item['accionante_solicitado'])
        # rad_corto NO es columna canónica, derivamos folder con regex año+consec
        if not rad_corto_field and rad23:
            m = re.search(r'(20\d{2})(\d{5})', rad23)
            if m:
                rad_corto_field = f'{m.group(1)}-{m.group(2)}'
        # Normalizar a formato AAAA-NNNNN
        m2 = re.match(r'^(\d{4})-?0*(\d+)$', (rad_corto_field or '').replace(' ',''))
        if m2:
            rad_corto_field = f'{m2.group(1)}-{int(m2.group(2)):05d}'
        rad_corto_field = rad_corto_field or 'SIN_RAD'
        folder_name = f"{rad_corto_field} {normalize_for_folder(accionante)}"
        folder_path = BASE_DIR / folder_name

        self.emit(f"\n[CREATE_NEW] #{item['id']} {accionante}")
        self.emit(f"  folder: {folder_name}")

        # Quitar campos non-canonical
        cf_clean = {k: v for k, v in cf.items() if k != 'radicado_corto'}
        cf_clean['folder_name'] = folder_name
        cf_clean['folder_path'] = str(folder_path)

        new_id = self._insert_case(cf_clean)
        self.created_case_ids.append(new_id)
        self.emit(f"  -> case_id {new_id}")

        # mkdir
        if self.commit:
            folder_path.mkdir(parents=True, exist_ok=True)
        self.emit(f"  mkdir {folder_path.name}")
        self.stats['folders_created'] += 1

        # Move files + INSERT documents
        for di in item['doc_inserts']:
            src = self._quar_path(di['from_quar'])
            dest = folder_path / di['filename']
            if not src.exists():
                self.emit(f"  ⚠️ MISSING {di['from_quar']}")
                self.stats['docs_missing'] += 1
                continue
            h = file_sha256(src)
            if self.commit:
                if dest.exists() and dest != src:
                    dest = folder_path / f"recovered_{di['filename']}"
                shutil.move(str(src), str(dest))
            self.emit(f"  + doc {di['doc_type']:25s} {di['filename'][:60]} sha={h[:8]}")
            self._insert_doc(new_id, dest, di['filename'], di['doc_type'], h)
        self.stats['create_new'] += 1

    def apply_merge(self, item: dict):
        target = item['target_case_id']
        self.cur.execute("SELECT folder_path, folder_name, observaciones FROM cases WHERE id=?", (target,))
        row = self.cur.fetchone()
        if not row:
            self.emit(f"  ⚠️ target c{target} no existe")
            self.stats['errors'] += 1
            return
        folder_path_str, folder_name, obs_existing = row
        folder_path = Path(folder_path_str) if folder_path_str else None
        if not folder_path or not folder_path.exists():
            self.emit(f"  ⚠️ folder target no existe: {folder_path}")
            self.stats['errors'] += 1
            return

        self.emit(f"\n[MERGE_INTO] #{item['id']} {item['accionante_solicitado']} -> c{target} ({folder_name})")

        # sha existing in target
        self.cur.execute("SELECT file_hash FROM documents WHERE case_id=? AND file_hash IS NOT NULL", (target,))
        target_hashes = {r[0] for r in self.cur.fetchall()}

        for di in item['doc_inserts']:
            src = self._quar_path(di['from_quar'])
            if not src.exists():
                self.emit(f"  ⚠️ MISSING {di['from_quar']}")
                self.stats['docs_missing'] += 1
                continue
            h = file_sha256(src)
            if h in target_hashes:
                self.emit(f"  SKIP dup sha {di['filename'][:60]}")
                self.stats['docs_skipped_dup'] += 1
                # Mover a cuarentena vieja con sufijo
                if self.commit:
                    dup_name = QUAR_DIR / f"dup_in_c{target}_{di['from_quar']}"
                    shutil.move(str(src), str(dup_name))
                continue
            dest = folder_path / di['filename']
            if dest.exists() and dest != src:
                dest = folder_path / f"recovered_{di['filename']}"
            if self.commit:
                shutil.move(str(src), str(dest))
            self.emit(f"  + doc {di['doc_type']:25s} {di['filename'][:60]} sha={h[:8]}")
            self._insert_doc(target, dest, di['filename'], di['doc_type'], h)

        # Apply case_field_updates if any
        cf_updates = item.get('case_field_updates') or {}
        if cf_updates:
            cols = {k: v for k, v in cf_updates.items() if k in ALLOWED_COLS}
            if cols:
                assigns = ', '.join(f'{k}=?' for k in cols.keys())
                if self.commit:
                    self.cur.execute(
                        f"UPDATE cases SET {assigns}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        list(cols.values()) + [target]
                    )
                self.emit(f"  UPDATE c{target} fields: {list(cols.keys())}")

        # Nota a observaciones
        note = f"[merge_from_cuarentena 2026-05-28] {item['accionante_solicitado']}: {len(item['doc_inserts'])} docs recuperados. {item.get('notes', '')[:300]}"
        new_obs = (obs_existing or '') + ('\n\n' if obs_existing else '') + note
        if self.commit:
            self.cur.execute("UPDATE cases SET observaciones=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                             (new_obs.strip(), target))
        self.emit(f"  +obs nota merge")
        self.stats['merge_into'] += 1

    def run(self):
        plan = json.load(open(PLAN))
        items = plan['plan']
        # CREATE_NEW primero (para no chocar con MERGE de cases nuevos potencialmente)
        items.sort(key=lambda it: 0 if it.get('decision') == 'CREATE_NEW' else 1)
        for it in items:
            try:
                if it['decision'] == 'CREATE_NEW':
                    self.apply_create_new(it)
                elif it['decision'] == 'MERGE_INTO_EXISTING':
                    self.apply_merge(it)
                else:
                    self.emit(f"  ⚠️ Unknown decision: {it['decision']}")
                    self.stats['errors'] += 1
            except Exception as e:
                self.emit(f"  ❌ ERROR #{it['id']}: {e}")
                self.stats['errors'] += 1
                if self.commit:
                    raise
        if self.commit:
            self.conn.commit()
        # FK check
        self.cur.execute("PRAGMA foreign_key_check")
        fk = self.cur.fetchall()
        self.emit(f"\nFK violations: {len(fk)}")
        if fk:
            for f in fk[:20]:
                self.emit(f"  {f}")
        self.emit("\n=== STATS ===")
        for k, v in self.stats.items():
            self.emit(f"  {k}: {v}")
        for q in ("SELECT COUNT(*) FROM cases", "SELECT COUNT(*) FROM documents"):
            self.cur.execute(q)
            self.emit(f"  {q}: {self.cur.fetchone()[0]}")
        if self.created_case_ids:
            self.emit(f"  created_case_ids: {self.created_case_ids}")
        self.conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--commit', action='store_true')
    args = ap.parse_args()
    mode = 'COMMIT' if args.commit else 'DRY-RUN'
    print(f"=== {mode} 9-nuevos plan @ {datetime.now().isoformat(timespec='seconds')} ===")
    if args.commit:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = DB.parent / f"tutelas.db.bak_pre_9nuevos_{ts}"
        shutil.copy2(DB, backup)
        print(f"Backup: {backup.name}")
    Applier(args.commit).run()


if __name__ == '__main__':
    main()
