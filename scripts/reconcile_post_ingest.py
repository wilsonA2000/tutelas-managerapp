#!/usr/bin/env python3
"""F6 — Backstop de reconciliación post-ingesta (anti-duplicados Gmail).

Corre DESPUÉS de cada ingesta (manual o monitor) y detecta casos duplicados
creados por las dos rutas de ingesta / shells sin reconciliar / emails partidos.

Distingue:
  - DUPLICADO CONCLUSIVO  -> auto-fusiona (solo con --apply): cascarón vacío,
    rad23 idéntico (23 díg.), shell adoptado por su caso con rad23.
  - CONFLACIÓN (rad corto igual, JUZGADO distinto) -> NO toca, son tutelas
    distintas; solo informa.
  - REVISIÓN (ambiguo, accionante distinto, email partido) -> solo marca.

Diseño defensivo (mismas reglas que la limpieza manual 2026-05-21):
  * Pure stdlib (sqlite3) — corre sin venv.
  * Dry-run por defecto; --apply ejecuta SOLO la clase conclusiva.
  * Backup automático antes de aplicar.
  * sha256 dedup: archivos byte-idénticos van a cuarentena, no se borran.
  * Re-apunta TODA tabla con FK a cases (documents, emails, audit_log, ...).
  * Imprime cola de revisión para lo no-conclusivo.

Uso:
    python3 scripts/reconcile_post_ingest.py                 # dry-run (reporte)
    python3 scripts/reconcile_post_ingest.py --apply         # fusiona conclusivos
    python3 scripts/reconcile_post_ingest.py --since-id 430  # solo casos id>430
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sqlite3
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "tutelas.db"
QUARANTINE = ROOT / "data" / "quarantine_misfiled" / "reconcile_post_ingest"


# ───────────────────────── helpers de radicado ─────────────────────────

def _digits(rad: str | None) -> str:
    return re.sub(r"\D", "", rad or "")


def _rad21(rad: str | None) -> str | None:
    """Primeros 21 dígitos = proceso sin sufijo de recurso (1ra=00, 2da=01)."""
    d = _digits(rad)
    return d[:21] if len(d) >= 21 else None


def _juzgado(rad: str | None) -> str | None:
    """Dígitos 5-12 del rad23 = código del despacho (DANE muni + entidad+esp+desp)."""
    d = _digits(rad)
    return d[5:12] if len(d) >= 12 else None


def _rad_corto_from_rad23(rad: str | None) -> str | None:
    d = _digits(rad)
    return f"{d[12:16]}-{d[16:21]}" if len(d) >= 21 else None


_FOLDER_RAD = re.compile(r"\b(20\d{2})[\s\-]?0*(\d{3,5})\b")


def _rad_corto_from_folder(folder: str | None) -> str | None:
    if not folder:
        return None
    m = _FOLDER_RAD.search(folder)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(5)}"
    return None


def _norm_name(s: str | None) -> str:
    if not s:
        return ""
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s.upper()).strip()


def _sha(path: str | None) -> str | None:
    try:
        if path and os.path.exists(path):
            return hashlib.sha256(open(path, "rb").read()).hexdigest()
    except Exception:
        pass
    return None


# ───────────────────────── modelo de caso ─────────────────────────

class CaseRow:
    __slots__ = ("id", "rad23", "accionante", "folder_name", "forest",
                 "n_docs", "n_emails", "status", "rad_corto", "juzgado", "rad21")

    def __init__(self, row, n_docs, n_emails):
        self.id = row["id"]
        self.rad23 = row["radicado_23_digitos"]
        self.accionante = row["accionante"]
        self.folder_name = row["folder_name"]
        self.forest = row["radicado_forest"]
        self.status = row["processing_status"]
        self.n_docs = n_docs
        self.n_emails = n_emails
        self.rad_corto = _rad_corto_from_rad23(self.rad23) or _rad_corto_from_folder(self.folder_name)
        self.juzgado = _juzgado(self.rad23)
        self.rad21 = _rad21(self.rad23)

    @property
    def is_empty(self):
        return self.n_docs == 0 and self.n_emails == 0

    @property
    def has_rad23(self):
        return bool(self.rad21)

    def __repr__(self):
        return (f"c{self.id}[docs={self.n_docs} {self.status} "
                f"rad={self.rad23 or '∅'} acc={(self.accionante or '∅')[:22]}]")


def load_cases(db, since_id=0):
    rows = db.execute(
        "SELECT id,radicado_23_digitos,accionante,folder_name,radicado_forest,processing_status "
        "FROM cases WHERE id>? ORDER BY id", (since_id,)
    ).fetchall()
    out = []
    for r in rows:
        nd = db.execute("SELECT COUNT(*) FROM documents WHERE case_id=?", (r["id"],)).fetchone()[0]
        ne = db.execute("SELECT COUNT(*) FROM emails WHERE case_id=?", (r["id"],)).fetchone()[0]
        out.append(CaseRow(r, nd, ne))
    return out


# ───────────────────────── detección ─────────────────────────

def survivor_of(members: list[CaseRow]) -> CaseRow:
    """Elige el caso que sobrevive: con rad23 > más docs > id menor (más antiguo)."""
    return sorted(members, key=lambda c: (not c.has_rad23, -c.n_docs, c.id))[0]


def classify_group(members: list[CaseRow]) -> list[dict]:
    """Devuelve acciones {kind, survivor, src, reason} para un grupo con mismo rad_corto.

    Identidad de proceso = rad21 (díg. 0-20: municipio+juzgado+año+consecutivo). Dos
    casos son la MISMA tutela sii rad21 igual (solo difiere el sufijo de recurso 00/01).
    rad21 distinto con mismo rad_corto = CONFLACIÓN (tutelas de municipios distintos).
    """
    actions = []
    surv = survivor_of(members)
    rad21s = {m.rad21 for m in members if m.rad21}
    is_conflacion_cluster = len(rad21s) > 1

    def _same_acc(a: CaseRow, b: CaseRow) -> bool:
        na, nb = _norm_name(a.accionante), _norm_name(b.accionante)
        return bool(na) and na == nb and len(na) >= 6

    for m in members:
        if m.id == surv.id:
            continue
        # CONFLACIÓN: ambos con rad23 y rad21 DISTINTO -> tutelas distintas, NO tocar.
        if m.rad21 and surv.rad21 and m.rad21 != surv.rad21:
            actions.append({"kind": "CONFLACION", "survivor": surv, "src": m,
                            "reason": f"rad21 distinto (municipios distintos) — tutelas separadas"})
            continue
        # CONCLUSIVO 1: rad21 IDÉNTICO (misma tutela, 1ra/2da instancia).
        if m.rad21 and surv.rad21 and m.rad21 == surv.rad21:
            actions.append({"kind": "MERGE_RAD21", "survivor": surv, "src": m,
                            "reason": f"rad21 idéntico {m.rad21}"})
            continue
        # CONCLUSIVO 2: cascarón vacío (0 docs). Solo si NO es cluster de conflación
        #   ambiguo (sin un único hogar claro) o el accionante coincide.
        if m.is_empty:
            if (not is_conflacion_cluster) or _same_acc(m, surv):
                actions.append({"kind": "MERGE_EMPTY", "survivor": surv, "src": m,
                                "reason": "cascarón vacío (0 docs/0 emails)"})
            else:
                actions.append({"kind": "REVIEW", "survivor": surv, "src": m,
                                "reason": "cascarón vacío en cluster de conflación (hogar ambiguo)"})
            continue
        # CONCLUSIVO 3: shell (sin rad23) adoptado por el caso con rad23 — SOLO si el
        #   accionante coincide Y el grupo NO es cluster de conflación (sin rad23 no
        #   conozco el juzgado real del shell; con varios rad21 sería ambiguo a cuál va).
        if not m.rad21 and surv.rad21:
            if _same_acc(m, surv) and not is_conflacion_cluster:
                actions.append({"kind": "MERGE_SHELL", "survivor": surv, "src": m,
                                "reason": "shell sin rad23, accionante idéntico (grupo sin conflación)"})
            else:
                why = "accionante no coincide" if not _same_acc(m, surv) else "cluster de conflación (hogar ambiguo)"
                actions.append({"kind": "REVIEW", "survivor": surv, "src": m,
                                "reason": f"shell sin rad23, {why} (verificar)"})
            continue
        # Lo demás -> revisión humana.
        actions.append({"kind": "REVIEW", "survivor": surv, "src": m,
                        "reason": "no concluyente (revisar accionante/juzgado)"})
    return actions


def find_actions(cases: list[CaseRow]) -> tuple[list[dict], list[dict]]:
    """Agrupa por rad_corto y clasifica. Devuelve (conclusivos, revisar/conflacion)."""
    groups = defaultdict(list)
    for c in cases:
        if c.rad_corto:
            groups[c.rad_corto].append(c)
    conclusive, review = [], []
    for rc, members in groups.items():
        if len(members) < 2:
            continue
        for a in classify_group(members):
            a["rad_corto"] = rc
            if a["kind"].startswith("MERGE_"):
                conclusive.append(a)
            else:
                review.append(a)
    return conclusive, review


def find_split_emails(db) -> list[dict]:
    """Emails cuyos documentos quedaron repartidos en >1 caso (síntoma de split)."""
    rows = db.execute(
        "SELECT email_id, GROUP_CONCAT(DISTINCT case_id) cids, COUNT(*) n "
        "FROM documents WHERE email_id IS NOT NULL AND case_id IS NOT NULL "
        "GROUP BY email_id HAVING COUNT(DISTINCT case_id)>1"
    ).fetchall()
    return [{"email_id": r["email_id"], "cases": r["cids"], "n_docs": r["n"]} for r in rows]


# ───────────────────────── fusión (solo --apply) ─────────────────────────

def _fk_tables_to_cases(db) -> list[tuple[str, str]]:
    """Tablas/columnas con FK a cases.id (para re-apuntar antes de borrar)."""
    out = []
    for (tbl,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        cols = [c[1] for c in db.execute(f"PRAGMA table_info({tbl})").fetchall()]
        if "case_id" in cols:
            out.append((tbl, "case_id"))
        for fk in db.execute(f"PRAGMA foreign_key_list({tbl})").fetchall():
            # fk: (id, seq, table, from, to, ...)
            if fk[2] == "cases" and fk[3] != "case_id":
                out.append((tbl, fk[3]))
    return out


# Campos escalares del cuadro a migrar del src al survivor (NO rad23/accionante/folder:
# esos los manda el survivor). FOREST/forest_impugnacion son por-radicación → si chocan,
# se preservan como nota en observaciones (no se pierde la 2da radicación).
_SCALAR_FIELDS = (
    "radicado_forest", "accionados", "vinculados", "juzgado", "juzgado_2nd", "ciudad",
    "fecha_ingreso", "asunto", "pretensiones", "derecho_vulnerado", "categoria_tematica",
    "oficina_responsable", "dependencia_canonical", "direccion", "grupo", "equipo",
    "abogado_responsable", "abogado_canonical", "estado", "fecha_respuesta", "impugnacion",
    "quien_impugno", "forest_impugnacion", "sentido_fallo_1st", "fecha_fallo_1st",
    "sentido_fallo_2nd", "fecha_fallo_2nd", "incidente", "fecha_apertura_incidente",
    "responsable_desacato", "abogado_incidente", "decision_incidente",
)
_FOREST_LIKE = {"radicado_forest", "forest_impugnacion"}


def _migrate_scalars(db, src_id: int, surv_id: int) -> dict:
    """Migra campos escalares EXCLUSIVOS (survivor vacío + src con valor) antes de borrar.
    Conflictos en campos FOREST (por-radicación) → nota en observaciones. observaciones se
    concatena. Cumple la regla 'reconciliación tras traslado' (no perder campos exclusivos)."""
    cols = {c[1] for c in db.execute("PRAGMA table_info(cases)").fetchall()}
    s = db.execute("SELECT * FROM cases WHERE id=?", (src_id,)).fetchone()
    t = db.execute("SELECT * FROM cases WHERE id=?", (surv_id,)).fetchone()
    migrated, notes = [], []
    for f in _SCALAR_FIELDS:
        if f not in cols:
            continue
        sv, tv = s[f], t[f]
        sv_ok = sv not in (None, "") and str(sv).strip()
        tv_ok = tv not in (None, "") and str(tv).strip()
        if sv_ok and not tv_ok:
            db.execute(f"UPDATE cases SET {f}=? WHERE id=?", (sv, surv_id))
            migrated.append(f)
        elif sv_ok and tv_ok and str(sv).strip() != str(tv).strip() and f in _FOREST_LIKE:
            notes.append(f"{f} alterno (de c{src_id}): {sv}")
    # observaciones: concatenar las del src si aportan algo distinto + notas de conflicto.
    extra = []
    so = (s["observaciones"] or "").strip() if "observaciones" in cols else ""
    to = (t["observaciones"] or "").strip() if "observaciones" in cols else ""
    if so and so not in to:
        extra.append(so)
    extra.extend(notes)
    if extra:
        new_obs = (to + "\n\n" + "\n".join(extra)).strip() if to else "\n".join(extra)
        db.execute("UPDATE cases SET observaciones=? WHERE id=?", (new_obs, surv_id))
    return {"migrated": migrated, "notes": len(notes)}


def merge_case(db, src_id: int, surv_id: int, fk_tables, base_dir: Path) -> dict:
    """Fusiona src -> surv. sha-dedup de archivos, re-apunta FK, migra escalares, borra src."""
    QUARANTINE.mkdir(parents=True, exist_ok=True)
    surv_dir = None
    r = db.execute("SELECT file_path FROM documents WHERE case_id=? AND file_path IS NOT NULL LIMIT 1", (surv_id,)).fetchone()
    if r:
        surv_dir = os.path.dirname(r["file_path"])
    surv_sha = {}
    for d in db.execute("SELECT id,file_path FROM documents WHERE case_id=?", (surv_id,)).fetchall():
        s = _sha(d["file_path"])
        if s:
            surv_sha[s] = d["id"]

    moved = dups = 0
    for d in db.execute("SELECT id,file_path,filename FROM documents WHERE case_id=?", (src_id,)).fetchall():
        s = _sha(d["file_path"])
        if s and s in surv_sha:  # byte-idéntico -> cuarentena
            if d["file_path"] and os.path.exists(d["file_path"]):
                shutil.move(d["file_path"], str(QUARANTINE / f"c{src_id}_doc{d['id']}_{os.path.basename(d['file_path'])}"))
            db.execute("DELETE FROM documents WHERE id=?", (d["id"],))
            dups += 1
        else:
            dest = os.path.join(surv_dir, os.path.basename(d["file_path"])) if (d["file_path"] and surv_dir) else None
            if dest and os.path.exists(d["file_path"]):
                if os.path.abspath(d["file_path"]) != os.path.abspath(dest):
                    if os.path.exists(dest):
                        stem, ext = os.path.splitext(os.path.basename(d["file_path"]))
                        dest = os.path.join(surv_dir, f"{stem}_{src_id}{ext}")
                    shutil.move(d["file_path"], dest)
                db.execute("UPDATE documents SET case_id=?, file_path=? WHERE id=?", (surv_id, dest, d["id"]))
            else:
                db.execute("UPDATE documents SET case_id=? WHERE id=?", (surv_id, d["id"]))
            if s:
                surv_sha[s] = d["id"]
            moved += 1

    # Migrar campos escalares exclusivos del src ANTES de borrarlo (regla "reconciliación
    # tras traslado": no perder campos que el survivor no tiene).
    mig = _migrate_scalars(db, src_id, surv_id)

    # Re-apuntar el resto de FK (emails, audit_log, etc.) ANTES de borrar.
    for tbl, col in fk_tables:
        if tbl == "documents":
            continue
        db.execute(f"UPDATE {tbl} SET {col}=? WHERE {col}=?", (surv_id, src_id))

    # Carpeta vacía del src.
    fn = db.execute("SELECT folder_name FROM cases WHERE id=?", (src_id,)).fetchone()
    db.execute("DELETE FROM cases WHERE id=?", (src_id,))
    if fn and fn["folder_name"]:
        p = base_dir / fn["folder_name"]
        try:
            if p.is_dir() and not os.listdir(p):
                p.rmdir()
        except Exception:
            pass
    return {"moved": moved, "dups_quarantined": dups, "migrated": mig.get("migrated", [])}


# ───────────────────────── dedup de docs byte-idénticos (F4) ─────────────────────────

def _fk_tables_to_documents(db) -> list[tuple[str, str]]:
    """Tablas/columnas con FK a documents.id (re-apuntar antes de borrar un doc)."""
    out = []
    for (tbl,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        for fk in db.execute(f"PRAGMA foreign_key_list({tbl})").fetchall():
            if fk[2] == "documents":
                out.append((tbl, fk[3]))
    return out


def dedup_docs(db, apply: bool) -> dict:
    """Dedup de Documents byte-idénticos DENTRO del mismo caso (mismo file_hash).
    Conserva la copia canónica (con email_id + texto + id menor); cuarentena el resto.
    Re-apunta cualquier FK a documents.id hacia la canónica antes de borrar."""
    groups = db.execute(
        "SELECT case_id, file_hash, COUNT(*) n, GROUP_CONCAT(id) ids "
        "FROM documents WHERE file_hash IS NOT NULL AND file_hash!='' "
        "GROUP BY case_id, file_hash HAVING COUNT(*)>1"
    ).fetchall()
    fk_docs = _fk_tables_to_documents(db)
    qdir = ROOT / "data" / "quarantine_misfiled" / "dedup_docs"
    if apply:
        qdir.mkdir(parents=True, exist_ok=True)
    n_groups = removed = 0
    for g in groups:
        ids = [int(x) for x in g["ids"].split(",")]
        docs = [db.execute(
            "SELECT id,filename,file_path,email_id,LENGTH(extracted_text) tl FROM documents WHERE id=?",
            (i,)).fetchone() for i in ids]
        canon = sorted(docs, key=lambda d: (d["email_id"] is None, (d["tl"] or 0) == 0, d["id"]))[0]
        n_groups += 1
        for d in docs:
            if d["id"] == canon["id"]:
                continue
            removed += 1
            if apply:
                # re-apuntar FK -> canónica
                for tbl, col in fk_docs:
                    db.execute(f"UPDATE {tbl} SET {col}=? WHERE {col}=?", (canon["id"], d["id"]))
                # cuarentena del archivo físico (si difiere del de la canónica)
                fp = d["file_path"]
                if fp and os.path.exists(fp) and os.path.abspath(fp) != os.path.abspath(canon["file_path"] or ""):
                    try:
                        shutil.move(fp, str(qdir / f"c{g['case_id']}_doc{d['id']}_{os.path.basename(fp)}"))
                    except Exception:
                        pass
                db.execute("DELETE FROM documents WHERE id=?", (d["id"],))
    if apply:
        db.commit()
    return {"groups": n_groups, "removed": removed}


# ───────────────────────── main ─────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Ejecuta auto-merge de conclusivos (default: dry-run)")
    ap.add_argument("--since-id", type=int, default=0, help="Solo casos con id > este valor")
    ap.add_argument("--dedup-docs", action="store_true", help="Dedup de Documents byte-idénticos en el mismo caso")
    args = ap.parse_args()

    base_dir = Path(os.environ.get("BASE_DIR", "")) if os.environ.get("BASE_DIR") else None
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")

    # base_dir = carpeta padre de cualquier folder_path existente
    if base_dir is None:
        r = db.execute("SELECT file_path FROM documents WHERE file_path IS NOT NULL LIMIT 1").fetchone()
        base_dir = Path(os.path.dirname(os.path.dirname(r["file_path"]))) if r else ROOT

    cases = load_cases(db, args.since_id)
    conclusive, review = find_actions(cases)
    splits = find_split_emails(db)

    print("=" * 70)
    print(f"RECONCILIADOR POST-INGESTA  ({'APPLY' if args.apply else 'DRY-RUN'})  "
          f"casos analizados: {len(cases)}  base_dir: {base_dir}")
    print("=" * 70)

    print(f"\n🟢 CONCLUSIVOS (auto-fusión): {len(conclusive)}")
    for a in conclusive:
        print(f"  [{a['kind']:12}] c{a['src'].id} → c{a['survivor'].id}  ({a['rad_corto']}) — {a['reason']}")

    print(f"\n🟡 REVISIÓN MANUAL: {len([r for r in review if r['kind']=='REVIEW'])}")
    for a in [r for r in review if r["kind"] == "REVIEW"]:
        print(f"  c{a['src'].id} ?→ c{a['survivor'].id} ({a['rad_corto']}) — {a['reason']}")
        print(f"       src={a['src']!r}\n       surv={a['survivor']!r}")

    print(f"\n✅ CONFLACIONES legítimas (NO tocar): {len([r for r in review if r['kind']=='CONFLACION'])}")
    for a in [r for r in review if r["kind"] == "CONFLACION"]:
        print(f"  c{a['src'].id} / c{a['survivor'].id} ({a['rad_corto']}) — {a['reason']}")

    print(f"\n🔵 EMAILS PARTIDOS entre casos: {len(splits)}")
    for s in splits[:20]:
        print(f"  email#{s['email_id']} en casos [{s['cases']}] ({s['n_docs']} docs)")

    dd = dedup_docs(db, apply=False) if args.dedup_docs else {"groups": 0, "removed": 0}
    if args.dedup_docs:
        print(f"\n🟣 DOCS byte-idénticos en mismo caso: {dd['groups']} grupos, {dd['removed']} filas redundantes")

    if not args.apply:
        print(f"\n(dry-run — nada modificado. --apply fusiona {len(conclusive)} conclusivos"
              f"{' y depura ' + str(dd['removed']) + ' docs dup' if args.dedup_docs else ''}.)")
        db.close()
        return 0

    if not conclusive and not (args.dedup_docs and dd["removed"]):
        print("\nNada conclusivo que aplicar.")
        db.close()
        return 0

    # Backup antes de tocar.
    bak = DB_PATH.with_suffix(f".db.bak_pre_reconcile_{time.strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(DB_PATH, bak)
    print(f"\nbackup: {bak.name}")

    fk_tables = _fk_tables_to_cases(db)
    done = 0
    # Ordenar: fusionar primero hacia survivors que NO sean a su vez src de otra acción.
    src_ids = {a["src"].id for a in conclusive}
    ordered = sorted(conclusive, key=lambda a: a["survivor"].id in src_ids)
    for a in ordered:
        # Revalidar que ambos sigan existiendo (cadenas de merge).
        ex = db.execute("SELECT COUNT(*) FROM cases WHERE id IN (?,?)", (a["src"].id, a["survivor"].id)).fetchone()[0]
        if ex < 2:
            continue
        res = merge_case(db, a["src"].id, a["survivor"].id, fk_tables, base_dir)
        db.commit()
        done += 1
        mig = f" migrados={res['migrated']}" if res.get("migrated") else ""
        print(f"  ✓ [{a['kind']}] c{a['src'].id}→c{a['survivor'].id}  movidos={res['moved']} dups={res['dups_quarantined']}{mig}")

    print(f"\nFusionados: {done}/{len(conclusive)}.")

    if args.dedup_docs:
        res = dedup_docs(db, apply=True)
        print(f"Docs dedup: {res['removed']} filas redundantes depuradas ({res['groups']} grupos).")

    print(f"Backup en {bak.name}.")
    print("Corre la safety net: venv/bin/python scripts/v9_test_db.py")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
