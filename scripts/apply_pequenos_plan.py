#!/usr/bin/env python3
"""
Aplica el plan consolidado de revisión de cases pequeños (1-4 docs).

Lee data/plan_consolidado_pequenos.json y ejecuta:
  - UPDATE: cambios de campos (normalizando columnas non-canónicas)
  - MERGE_INTO: mover docs, migrar audit_log, DELETE case
  - DELETE_AS_NON_TUTELA: cuarentenar docs, DELETE
  - QUARANTINE_DOCS: mover doc físico, DELETE documents row
  - NEED_HUMAN: solo registra en observaciones

Uso:
  python3 scripts/apply_pequenos_plan.py            # dry-run
  python3 scripts/apply_pequenos_plan.py --commit   # aplica
"""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, sqlite3, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "tutelas.db"
DEFAULT_PLAN = ROOT / "data" / "plan_consolidado_pequenos.json"
BASE_DIR = Path("/home/wilsonarguello/Documentos/GOBERNACION DE SANTANDER/V9_PRODUCCION")
QUAR_DIR_BASE = ROOT / "data" / "quarantine_misfiled"

CANONICAL_COLS = {
    'radicado_23_digitos', 'radicado_forest', 'abogado_responsable', 'accionante',
    'accionados', 'vinculados', 'derecho_vulnerado', 'juzgado', 'ciudad', 'fecha_ingreso',
    'asunto', 'pretensiones', 'oficina_responsable', 'direccion', 'grupo', 'equipo',
    'abogado_canonical', 'dependencia_canonical', 'estado', 'fecha_respuesta',
    'sentido_fallo_1st', 'fecha_fallo_1st', 'impugnacion', 'quien_impugno',
    'forest_impugnacion', 'juzgado_2nd', 'sentido_fallo_2nd', 'fecha_fallo_2nd',
    'incidente', 'fecha_apertura_incidente', 'responsable_desacato', 'decision_incidente',
    'incidente_2', 'fecha_apertura_incidente_2', 'responsable_desacato_2',
    'decision_incidente_2', 'incidente_3', 'fecha_apertura_incidente_3',
    'responsable_desacato_3', 'decision_incidente_3', 'observaciones',
    'categoria_tematica', 'folder_name', 'origen', 'estado_incidente',
    'processing_status', 'tipo_actuacion', 'abogado_incidente',
    'abogado_incidente_2', 'abogado_incidente_3', 'parte_resolutiva_1st',
    'parte_resolutiva_2nd', 'pii_mode', 'acumulado_a_case_id', 'tipo_acumulacion',
}

def file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()

def normalize_updates(case_id: int, updates: dict, current_obs: str | None) -> tuple[dict, str | None]:
    """Devuelve (cols_canónicas, nuevo_observaciones)."""
    cols = {}
    obs_parts: list[str] = []
    folder_rename = None
    for k, v in updates.items():
        if v is None or v == '':
            cols[k] = None if k in CANONICAL_COLS else None
            if k in CANONICAL_COLS:
                continue
        if k in CANONICAL_COLS:
            cols[k] = v
        elif k in ('observaciones_append', 'observaciones_add'):
            if v:
                obs_parts.append(str(v))
        elif k == 'observaciones_clean':
            if isinstance(v, str) and v.strip():
                cols['observaciones'] = v  # sobrescribe
        elif k in ('folder_rename_suggested', 'folder_name_rename_to'):
            folder_rename = v
            cols['folder_name'] = v
        elif k.endswith('_revisar') or k.endswith('_confirma') or k.endswith('_check'):
            obs_parts.append(f"[REVISAR {k}] {v}")
        elif k == 'tipo_proceso':
            cols.setdefault('categoria_tematica', v)
        elif k == 'verificacion':
            obs_parts.append(f"[verificacion] {v}")
        elif k.startswith('doc_type_fix'):
            # sub-acción para doc_reclassify
            obs_parts.append(f"[{k}] {v}")
        else:
            obs_parts.append(f"[{k}] {v}")
    # Aplicar observaciones_append
    if obs_parts:
        existing = cols.get('observaciones', current_obs) or ''
        sep = '\n\n' if existing.strip() else ''
        cols['observaciones'] = (existing + sep + '\n'.join(obs_parts)).strip()
    return cols, folder_rename

def fmt_action(action: str) -> str:
    return f"[{action}]".ljust(22)

class Applier:
    def __init__(self, commit: bool, plan_path: Path, quar_subdir: str):
        self.commit = commit
        self.plan_path = plan_path
        self.quar_dir = QUAR_DIR_BASE / quar_subdir
        self.quar_dir.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(DB))
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.cur = self.conn.cursor()
        self.log: list[str] = []
        self.stats = {
            'UPDATE': 0, 'MERGE_INTO': 0, 'DELETE_AS_NON_TUTELA': 0,
            'QUARANTINE_DOCS': 0, 'NEED_HUMAN': 0, 'KEEP': 0, 'MOVE_DOCS': 0,
            'docs_moved': 0, 'docs_quarantined': 0, 'cases_deleted': 0,
            'audit_log_migrated': 0, 'folders_renamed': 0, 'sha_dup_skipped': 0,
            'errors': 0,
        }

    def emit(self, line: str):
        self.log.append(line)
        print(line)

    def get_case(self, case_id: int) -> dict | None:
        self.cur.execute("SELECT * FROM cases WHERE id=?", (case_id,))
        row = self.cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in self.cur.description]
        return dict(zip(cols, row))

    def apply_update(self, item: dict):
        cid = item['case_id']
        case = self.get_case(cid)
        if not case:
            self.emit(f"  ⚠️ c{cid} no existe en DB")
            self.stats['errors'] += 1
            return
        updates = item.get('updates') or {}
        if not updates and not item.get('doc_moves') and not item.get('doc_quarantines') and not item.get('doc_reclassify'):
            self.emit(f"  c{cid} UPDATE vacío")
            return
        cols, folder_rename = normalize_updates(cid, updates, case.get('observaciones'))
        if cols:
            assigns = ", ".join(f"{k}=?" for k in cols.keys())
            params = list(cols.values()) + [cid]
            sql = f"UPDATE cases SET {assigns}, updated_at=CURRENT_TIMESTAMP WHERE id=?"
            if self.commit:
                self.cur.execute(sql, params)
            self.emit(f"  c{cid} UPDATE {len(cols)} cols: {list(cols.keys())}")
        # Folder rename físico
        if folder_rename and case.get('folder_path'):
            old = Path(case['folder_path'])
            new = old.parent / folder_rename
            if old != new and old.exists() and not new.exists():
                if self.commit:
                    old.rename(new)
                    self.cur.execute("UPDATE cases SET folder_path=? WHERE id=?", (str(new), cid))
                    # Actualizar file_paths
                    self.cur.execute(
                        "UPDATE documents SET file_path=REPLACE(file_path, ?, ?) WHERE case_id=?",
                        (str(old), str(new), cid)
                    )
                self.emit(f"     folder rename: {old.name} → {new.name}")
                self.stats['folders_renamed'] += 1
        # Sub-acciones
        for q in item.get('doc_quarantines') or []:
            self._quarantine_doc(q['doc_id'], q.get('reason', 'plan_pequenos'), cid)
        for r in item.get('doc_reclassify') or item.get('doc_reclassifications') or []:
            did = r.get('doc_id')
            dt = r.get('new_doc_type') or r.get('to') or r.get('doc_type')
            if did and dt and self.commit:
                self.cur.execute("UPDATE documents SET doc_type=? WHERE id=?", (dt, did))
            if did and dt:
                self.emit(f"     doc {did} doc_type → {dt}")
        self.stats['UPDATE'] += 1

    # Tablas con FK a cases.id (todas) — usar para migrar/borrar antes del DELETE case
    FK_TABLES = [
        'emails', 'case_actuaciones', 'compliance_tracking', 'corte_revision',
        'token_usage', 'pii_mappings', 'privacy_stats', 'extractions',
    ]

    def _migrate_fks(self, src: int, target: int):
        """Migra refs de todas las FK_TABLES de src → target."""
        total = 0
        for t in self.FK_TABLES:
            self.cur.execute(f"SELECT COUNT(*) FROM {t} WHERE case_id=?", (src,))
            n = self.cur.fetchone()[0]
            if not n:
                continue
            if self.commit:
                self.cur.execute(f"UPDATE {t} SET case_id=? WHERE case_id=?", (target, src))
            self.emit(f"     {t} migrado: {n} filas → c{target}")
            total += n
        # documents.suggested_target_case_id (NULL no rompe, pero limpiar)
        if self.commit:
            self.cur.execute("UPDATE documents SET suggested_target_case_id=NULL WHERE suggested_target_case_id=?", (src,))
        return total

    def _delete_fks(self, src: int):
        """Borra refs de todas las FK_TABLES."""
        total = 0
        for t in self.FK_TABLES:
            self.cur.execute(f"SELECT COUNT(*) FROM {t} WHERE case_id=?", (src,))
            n = self.cur.fetchone()[0]
            if not n:
                continue
            if self.commit:
                self.cur.execute(f"DELETE FROM {t} WHERE case_id=?", (src,))
            self.emit(f"     {t} borrado: {n} filas")
            total += n
        if self.commit:
            self.cur.execute("UPDATE documents SET suggested_target_case_id=NULL WHERE suggested_target_case_id=?", (src,))
        return total

    def _doc_row(self, doc_id: int) -> dict | None:
        self.cur.execute("SELECT id, case_id, file_path, file_hash, doc_type FROM documents WHERE id=?", (doc_id,))
        row = self.cur.fetchone()
        if not row:
            return None
        return dict(zip([d[0] for d in self.cur.description], row))

    def _quarantine_doc(self, doc_id: int, reason: str, source_case: int):
        d = self._doc_row(doc_id)
        if not d:
            self.emit(f"     ⚠️ doc {doc_id} no existe")
            return
        # Mover físico si existe
        if d['file_path']:
            fp = Path(d['file_path'])
            if fp.exists():
                dest = self.quar_dir / f"c{source_case}_d{doc_id}_{fp.name}"
                if self.commit:
                    shutil.move(str(fp), str(dest))
                self.emit(f"     QUAR doc {doc_id} -> {dest.name}: {reason[:60]}")
        if self.commit:
            self.cur.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        self.stats['docs_quarantined'] += 1

    def apply_merge(self, item: dict):
        src = item['case_id']
        # Detectar clave de target
        target = item.get('merge_target_case_id') or item.get('merge_into_case_id') or item.get('merge_into')
        if not target:
            self.emit(f"  ⚠️ c{src} MERGE sin target")
            self.stats['errors'] += 1
            return
        src_case = self.get_case(src)
        tgt_case = self.get_case(target)
        if not src_case or not tgt_case:
            self.emit(f"  ⚠️ c{src}→c{target} faltan cases")
            self.stats['errors'] += 1
            return

        self.emit(f"  c{src} MERGE_INTO c{target}")
        # Mover docs
        doc_moves = item.get('doc_moves') or []
        # Si no hay doc_moves explícito, migrar TODOS los docs del source
        if not doc_moves:
            self.cur.execute("SELECT id FROM documents WHERE case_id=?", (src,))
            doc_moves = [{'doc_id': r[0], 'to_case_id': target} for r in self.cur.fetchall()]
        # Obtener sha256 ya en target
        self.cur.execute("SELECT file_hash FROM documents WHERE case_id=? AND file_hash IS NOT NULL", (target,))
        target_hashes = {r[0] for r in self.cur.fetchall()}
        # Target folder
        tgt_folder = Path(tgt_case['folder_path']) if tgt_case.get('folder_path') else None

        for m in doc_moves:
            did = m['doc_id']
            d = self._doc_row(did)
            if not d:
                self.emit(f"     ⚠️ doc {did} no existe")
                continue
            # ¿Dup byte-idéntico ya en target?
            if d.get('file_hash') and d['file_hash'] in target_hashes:
                self.emit(f"     SKIP dup sha doc {did} (ya en c{target})")
                # Cuarentenar (no perder)
                self._quarantine_doc(did, f"dup_sha_already_in_c{target}", src)
                self.stats['sha_dup_skipped'] += 1
                continue
            # Mover físico al folder del target
            new_path = d['file_path']
            if d['file_path'] and tgt_folder and tgt_folder.exists():
                src_fp = Path(d['file_path'])
                if src_fp.exists():
                    dest = tgt_folder / src_fp.name
                    # Evitar colisión nombre
                    if dest.exists() and dest != src_fp:
                        dest = tgt_folder / f"merged_c{src}_{src_fp.name}"
                    if self.commit:
                        shutil.move(str(src_fp), str(dest))
                    new_path = str(dest)
            if self.commit:
                self.cur.execute("UPDATE documents SET case_id=?, file_path=? WHERE id=?",
                                 (target, new_path, did))
            self.emit(f"     MOVE doc {did} -> c{target}")
            self.stats['docs_moved'] += 1

        # Aplicar updates al target si los hay
        post = item.get('post_merge_updates_on_target') or {}
        post_merge_dict = item.get('post_merge', {})
        if post_merge_dict.get('case_191_update'):  # ad hoc clave c232
            post = {**post, **post_merge_dict['case_191_update']}
        if post:
            cols, _ = normalize_updates(target, post, tgt_case.get('observaciones'))
            if cols:
                assigns = ", ".join(f"{k}=?" for k in cols.keys())
                params = list(cols.values()) + [target]
                sql = f"UPDATE cases SET {assigns}, updated_at=CURRENT_TIMESTAMP WHERE id=?"
                if self.commit:
                    self.cur.execute(sql, params)
                self.emit(f"     UPDATE target c{target}: {list(cols.keys())}")

        # Migrar audit_log
        self.cur.execute("SELECT COUNT(*) FROM audit_log WHERE case_id=?", (src,))
        n_audit = self.cur.fetchone()[0]
        if self.commit and n_audit:
            self.cur.execute("UPDATE audit_log SET case_id=? WHERE case_id=?", (target, src))
        if n_audit:
            self.emit(f"     audit_log migrado: {n_audit} filas → c{target}")
            self.stats['audit_log_migrated'] += n_audit

        # Migrar resto de FKs (emails, case_actuaciones, etc)
        self._migrate_fks(src, target)

        # DELETE case source (los docs ya migrados; los huérfanos serían bug)
        # En dry-run, simular: orphan = real - movidos en este merge
        self.cur.execute("SELECT COUNT(*) FROM documents WHERE case_id=?", (src,))
        real_orphan = self.cur.fetchone()[0]
        orphan = real_orphan if self.commit else max(0, real_orphan - len(doc_moves))
        if orphan:
            self.emit(f"     ⚠️ c{src} aún tiene {orphan} docs huérfanos, NO se borra")
            self.stats['errors'] += 1
            return
        # Borrar folder físico si vacío
        if src_case.get('folder_path'):
            sfp = Path(src_case['folder_path'])
            if sfp.exists() and not any(sfp.iterdir()):
                if self.commit:
                    sfp.rmdir()
                self.emit(f"     rmdir folder vacío {sfp.name}")
        if self.commit:
            self.cur.execute("DELETE FROM cases WHERE id=?", (src,))
        self.emit(f"     DELETE case c{src}")
        self.stats['cases_deleted'] += 1
        self.stats['MERGE_INTO'] += 1

    def apply_delete_non_tutela(self, item: dict):
        cid = item['case_id']
        case = self.get_case(cid)
        if not case:
            self.emit(f"  ⚠️ c{cid} no existe")
            self.stats['errors'] += 1
            return
        self.emit(f"  c{cid} DELETE_NON_TUTELA")
        # Cuarentenar docs físicos con prefijo no_tutela_cXXX_
        self.cur.execute("SELECT id, file_path FROM documents WHERE case_id=?", (cid,))
        docs = self.cur.fetchall()
        for did, fp_str in docs:
            if fp_str:
                fp = Path(fp_str)
                if fp.exists():
                    dest = self.quar_dir / f"no_tutela_c{cid}_d{did}_{fp.name}"
                    if self.commit:
                        shutil.move(str(fp), str(dest))
                    self.emit(f"     QUAR doc {did} -> {dest.name}")
            if self.commit:
                self.cur.execute("DELETE FROM documents WHERE id=?", (did,))
            self.stats['docs_quarantined'] += 1
        # Borrar audit_log
        self.cur.execute("SELECT COUNT(*) FROM audit_log WHERE case_id=?", (cid,))
        n_audit = self.cur.fetchone()[0]
        if self.commit and n_audit:
            self.cur.execute("DELETE FROM audit_log WHERE case_id=?", (cid,))
        if n_audit:
            self.emit(f"     audit_log borrado: {n_audit} filas")
        # Borrar resto de FKs (emails, case_actuaciones, etc)
        self._delete_fks(cid)
        # Borrar folder físico si vacío
        if case.get('folder_path'):
            sfp = Path(case['folder_path'])
            if sfp.exists() and not any(sfp.iterdir()):
                if self.commit:
                    sfp.rmdir()
                self.emit(f"     rmdir folder vacío {sfp.name}")
            elif sfp.exists():
                self.emit(f"     ⚠️ folder NO vacío, dejado: {sfp}")
        if self.commit:
            self.cur.execute("DELETE FROM cases WHERE id=?", (cid,))
        self.emit(f"     DELETE case c{cid}")
        self.stats['cases_deleted'] += 1
        self.stats['DELETE_AS_NON_TUTELA'] += 1

    def apply_quarantine_docs(self, item: dict):
        cid = item['case_id']
        self.emit(f"  c{cid} QUARANTINE_DOCS")
        for q in item.get('doc_quarantines') or []:
            self._quarantine_doc(q['doc_id'], q.get('reason', 'plan_pequenos'), cid)
        self.stats['QUARANTINE_DOCS'] += 1

    def apply_move_docs(self, item: dict):
        """Acción primaria MOVE_DOCS: mover lista de doc_moves a otro case."""
        src = item['case_id']
        self.emit(f"  c{src} MOVE_DOCS")
        for m in item.get('doc_moves') or []:
            did = m.get('doc_id')
            tgt = m.get('to_case_id') or m.get('to')
            if not did or not tgt:
                continue
            self.cur.execute("SELECT folder_path FROM cases WHERE id=?", (tgt,))
            row = self.cur.fetchone()
            tgt_folder = Path(row[0]) if row and row[0] else None
            d = self._doc_row(did)
            if not d:
                self.emit(f"     ⚠️ doc {did} no existe")
                continue
            new_path = d['file_path']
            if d['file_path'] and tgt_folder and tgt_folder.exists():
                src_fp = Path(d['file_path'])
                if src_fp.exists():
                    dest = tgt_folder / src_fp.name
                    if dest.exists() and dest != src_fp:
                        dest = tgt_folder / f"moved_from_c{src}_{src_fp.name}"
                    if self.commit:
                        shutil.move(str(src_fp), str(dest))
                    new_path = str(dest)
            if self.commit:
                self.cur.execute("UPDATE documents SET case_id=?, file_path=? WHERE id=?",
                                 (tgt, new_path, did))
            self.emit(f"     MOVE doc {did} c{src} -> c{tgt}")
            self.stats['docs_moved'] += 1
        self.stats['MOVE_DOCS'] += 1

    def apply_need_human(self, item: dict):
        cid = item['case_id']
        case = self.get_case(cid)
        if not case:
            return
        note = f"[NEED_HUMAN 2026-05-28] {item.get('reason', '')[:500]}"
        existing = case.get('observaciones') or ''
        sep = '\n\n' if existing.strip() else ''
        new_obs = (existing + sep + note).strip()
        if self.commit:
            self.cur.execute(
                "UPDATE cases SET observaciones=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (new_obs, cid)
            )
        self.emit(f"  c{cid} NEED_HUMAN -> nota en observaciones")
        self.stats['NEED_HUMAN'] += 1

    def run(self):
        with open(self.plan_path) as f:
            plan = json.load(f)
        items = plan['items']
        # Orden de aplicación: UPDATE → MOVE → QUARANTINE → MERGE → DELETE → NEED_HUMAN
        order = {'UPDATE': 0, 'MOVE_DOCS': 1, 'QUARANTINE_DOCS': 2, 'MERGE_INTO': 3, 'DELETE_AS_NON_TUTELA': 4, 'NEED_HUMAN': 5, 'KEEP': 6}
        items.sort(key=lambda it: order.get(it['action'], 99))
        for it in items:
            a = it['action']
            try:
                if a == 'KEEP':
                    self.stats['KEEP'] += 1
                elif a == 'UPDATE':
                    self.apply_update(it)
                elif a == 'MOVE_DOCS':
                    self.apply_move_docs(it)
                elif a == 'MERGE_INTO':
                    self.apply_merge(it)
                elif a == 'DELETE_AS_NON_TUTELA':
                    self.apply_delete_non_tutela(it)
                elif a == 'QUARANTINE_DOCS':
                    self.apply_quarantine_docs(it)
                elif a == 'NEED_HUMAN':
                    self.apply_need_human(it)
            except Exception as e:
                self.emit(f"  ❌ ERROR c{it['case_id']} {a}: {e}")
                self.stats['errors'] += 1
        if self.commit:
            self.conn.commit()
        # FK check
        self.cur.execute("PRAGMA foreign_key_check")
        fk = self.cur.fetchall()
        self.emit(f"\nFK violations: {len(fk)}")
        if fk:
            for f in fk[:20]:
                self.emit(f"  {f}")
        # Resumen
        self.emit("\n=== STATS ===")
        for k, v in self.stats.items():
            self.emit(f"  {k}: {v}")
        # Conteos finales
        for q in ("SELECT COUNT(*) FROM cases", "SELECT COUNT(*) FROM documents",
                  "SELECT COUNT(*) FROM documents WHERE doc_type='DESCONOCIDO'"):
            self.cur.execute(q)
            self.emit(f"  {q}: {self.cur.fetchone()[0]}")
        self.conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--commit', action='store_true', help='Aplicar cambios (default dry-run)')
    ap.add_argument('--plan', default=str(DEFAULT_PLAN), help='Ruta al plan JSON consolidado')
    ap.add_argument('--quar-subdir', default='pequenos_20260528', help='Subdir bajo quarantine_misfiled/')
    ap.add_argument('--label', default='pequenos', help='Etiqueta para backup nombrado')
    args = ap.parse_args()
    mode = "COMMIT" if args.commit else "DRY-RUN"
    print(f"=== {mode} {args.label} plan @ {datetime.now().isoformat(timespec='seconds')} ===\n")
    print(f"Plan: {args.plan}")
    print(f"Quar subdir: {args.quar_subdir}\n")
    if args.commit:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = DB.parent / f"tutelas.db.bak_pre_apply_{args.label}_{ts}"
        shutil.copy2(DB, backup)
        print(f"Backup: {backup.name}\n")
    Applier(commit=args.commit, plan_path=Path(args.plan), quar_subdir=args.quar_subdir).run()


if __name__ == '__main__':
    main()
