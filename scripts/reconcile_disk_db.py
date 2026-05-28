#!/usr/bin/env python3
"""Reconciliador DISCO ↔ DB (post-ingesta / post-desconflación).

Complemento de `reconcile_post_ingest.py`. Ese trabaja a nivel DB (fusiona casos
duplicados, deduplica docs byte-idénticos dentro del mismo caso). ESTE reconcilia
el sistema de archivos contra la tabla `documents`/`cases`:

  - `documents.file_path` stale (apunta a una ruta que ya no existe — típico tras
    renombrar la carpeta: el path quedó con el nombre viejo).
  - Archivos huérfanos (en disco, sin fila en `documents`).
  - `cases.folder_path` NULL, apuntando a carpeta inexistente, o compartido por
    2+ casos (residuo de una desconflación / shell sin limpiar).

Diseño defensivo (mismas reglas que la limpieza manual):
  * Pure stdlib — corre sin venv.
  * Dry-run por defecto; --apply ejecuta SOLO la clase segura. Backup antes de tocar.
  * Re-link por sha256: NUNCA mueve archivos; solo corrige el metadato `file_path`
    cuando el contenido (sha256 == documents.file_hash) coincide byte a byte.
  * Lo ambiguo (folder_path compartido, archivos sin rastro, orphans no atribuibles)
    va a una COLA DE REVISIÓN (CSV) para verlo caso por caso. No se auto-resuelve.

Categorías de fix (--apply):
  [SAFE-RELINK]    doc con file_path roto + 1 archivo byte-idéntico dentro de la
                   carpeta de SU caso → actualiza file_path (resuelve missing+orphan
                   de un solo golpe; cubre el caso c501 renombrado).
  [SAFE-FOLDER]    cases.folder_path NULL / inexistente / compartido → lo apunta a
                   BASE/folder_name si esa carpeta existe y no es de otro caso.

Cola de revisión (solo reporta):
  [REVIEW-SHARED]  folder_path compartido sin carpeta propia clara.
  [REVIEW-GONE]    doc con file_path roto y sin archivo byte-idéntico en disco.
  [REVIEW-ORPHAN]  archivo en disco sin fila documents, no atribuible por sha256.

Uso:
    python3 scripts/reconcile_disk_db.py                 # dry-run (reporte + CSV)
    python3 scripts/reconcile_disk_db.py --apply         # aplica SAFE-*
    BASE_DIR=/ruta python3 scripts/reconcile_disk_db.py  # fuerza la raíz de carpetas
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import shutil
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "tutelas.db"
REVIEW_CSV = ROOT / "data" / "reconcile_disk_db_revision.csv"
QUARANTINE = ROOT / "data" / "quarantine_misfiled" / "reconcile_disk_orphans"

_TOMBSTONE = re.compile(r"^MERGED_INTO_CASE_\d+$")
_IGNORE_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}


# ───────────────────────── helpers ─────────────────────────

def _sha(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def resolve_base_dir(db) -> Path:
    """BASE = env BASE_DIR, o el padre más común de los folder_path que existen."""
    env = os.environ.get("BASE_DIR")
    if env and Path(env).is_dir():
        return Path(env)
    parents = Counter()
    for (fp,) in db.execute("SELECT folder_path FROM cases WHERE folder_path IS NOT NULL"):
        if fp and not _TOMBSTONE.match(os.path.basename(fp)) and Path(fp).is_dir():
            parents[os.path.dirname(os.path.abspath(fp))] += 1
    if parents:
        return Path(parents.most_common(1)[0][0])
    return ROOT


# ───────────────────────── índice de disco ─────────────────────────

def build_disk_index(base: Path):
    """Recorre BASE una vez. Devuelve (path->sha, sha->[paths], set(abspaths))."""
    path_sha: dict[str, str] = {}
    sha_paths: dict[str, list[str]] = defaultdict(list)
    all_paths: set[str] = set()
    for root, _dirs, files in os.walk(base):
        for f in files:
            if f in _IGNORE_FILES:
                continue
            p = os.path.abspath(os.path.join(root, f))
            all_paths.add(p)
            s = _sha(p)
            if s:
                path_sha[p] = s
                sha_paths[s].append(p)
    return path_sha, sha_paths, all_paths


# ───────────────────────── detección ─────────────────────────

def analyze(db, base: Path, disk):
    path_sha, sha_paths, all_paths = disk
    cases = {r["id"]: dict(r) for r in db.execute(
        "SELECT id,folder_name,folder_path,processing_status FROM cases")}
    docs = [dict(r) for r in db.execute(
        "SELECT id,case_id,file_path,file_hash,filename FROM documents")]

    # mapa carpeta(abspath) -> [case_id] según folder_path real
    folder_owner: dict[str, list[int]] = defaultdict(list)
    for c in cases.values():
        fp = c["folder_path"]
        if fp and not _TOMBSTONE.match(os.path.basename(fp)):
            folder_owner[os.path.abspath(fp)].append(c["id"])

    safe_relink, review_gone = [], []
    known_paths = {os.path.abspath(d["file_path"]) for d in docs if d["file_path"]
                   and os.path.exists(d["file_path"])}

    # (1) docs con file_path roto -> re-link por sha256
    for d in docs:
        if not d["file_path"] or os.path.exists(d["file_path"]):
            continue
        h = d["file_hash"]
        cands = list(sha_paths.get(h, [])) if h else []
        c = cases.get(d["case_id"])
        owner = os.path.abspath(c["folder_path"]) if (c and c["folder_path"]) else None
        in_owner = [p for p in cands if owner and os.path.dirname(p) == owner]
        if len(in_owner) == 1:
            safe_relink.append({"doc_id": d["id"], "case_id": d["case_id"],
                                "filename": d["filename"], "old": d["file_path"],
                                "new": in_owner[0]})
            known_paths.add(in_owner[0])
        elif len(cands) == 1 and owner and os.path.dirname(cands[0]) == owner:
            safe_relink.append({"doc_id": d["id"], "case_id": d["case_id"],
                                "filename": d["filename"], "old": d["file_path"],
                                "new": cands[0]})
            known_paths.add(cands[0])
        else:
            review_gone.append({"doc_id": d["id"], "case_id": d["case_id"],
                                "filename": d["filename"], "old": d["file_path"],
                                "sha_hits": len(cands)})

    # dónde residen físicamente los docs de cada caso (dir de sus file_path válidos,
    # ya re-linkeados arriba). Usado para no crear misfiling al mover folder_path.
    relinked = {r["doc_id"]: r["new"] for r in safe_relink}
    doc_dirs: dict[int, set[str]] = defaultdict(set)
    for d in docs:
        fp = relinked.get(d["id"]) or d["file_path"]
        if fp and os.path.exists(fp):
            doc_dirs[d["case_id"]].add(os.path.dirname(os.path.abspath(fp)))

    # (2) folder_path: NULL / inexistente / compartido
    #   SAFE solo si: NULL o inexistente (NUNCA "compartido") + carpeta destino libre +
    #   los docs del caso ya residen ahí (o el caso no tiene docs). Repuntar una carpeta
    #   compartida o cuyos docs viven en otra parte = decisión de dueño/fusión → REVIEW.
    safe_folder, review_shared = [], []
    shared = {p: ids for p, ids in folder_owner.items() if len(ids) > 1}
    for c in cases.values():
        cid, fn, fp = c["id"], c["folder_name"], c["folder_path"]
        if fp and _TOMBSTONE.match(os.path.basename(fp)):
            continue  # tombstone de merge, no es bug
        desired = os.path.abspath(base / fn) if fn else None
        desired_ok = bool(desired) and os.path.isdir(desired)
        desired_free = desired_ok and folder_owner.get(desired, [cid]) == [cid]
        is_null = not fp
        is_missing = bool(fp) and not os.path.isdir(fp)
        is_shared = bool(fp) and os.path.abspath(fp) in shared
        if not (is_null or is_missing or is_shared):
            continue
        why = "NULL" if is_null else ("inexistente" if is_missing else "compartido")
        resident = doc_dirs.get(cid, set())
        docs_here = (not resident) or resident == {desired}
        if (is_null or is_missing) and desired_free and docs_here:
            safe_folder.append({"case_id": cid, "folder_name": fn, "old": fp or "∅",
                                "new": desired, "why": why})
        else:
            review_shared.append({"case_id": cid, "folder_name": fn, "old": fp or "∅",
                                  "why": why, "desired_exists": desired_ok,
                                  "sharers": shared.get(os.path.abspath(fp) if fp else "", []),
                                  "doc_dirs": sorted(os.path.basename(x) for x in resident)})

    # hashes de docs del caso CUYO file_path EXISTE (copia válida en disco). Guard:
    # un orphan solo es "redundante" si su caso ya tiene ese contenido con archivo
    # vivo en otra ruta — así nunca cuarentenamos la única copia (caso c429).
    case_live_hashes: dict[int, set[str]] = defaultdict(set)
    for d in docs:
        fp = relinked.get(d["id"]) or d["file_path"]
        if d["file_hash"] and fp and os.path.exists(fp):
            case_live_hashes[d["case_id"]].add(d["file_hash"])

    # (3) orphans: archivos en disco sin fila documents (tras los re-links).
    #   redundant_orphan = byte-idéntico a un doc YA registrado (con copia viva) del
    #   caso dueño de su carpeta → cuarentenable. El resto va a revisión.
    review_orphan, redundant_orphan = [], []
    for p in sorted(all_paths - known_paths):
        d = os.path.dirname(p)
        owners = folder_owner.get(d, [])
        owner = owners[0] if len(owners) == 1 else None
        s = path_sha.get(p)
        if owner and s and s in case_live_hashes.get(owner, set()):
            redundant_orphan.append({"path": p, "folder": os.path.basename(d),
                                     "case_id": owner, "sha": s})
        else:
            review_orphan.append({"path": p, "folder": os.path.basename(d),
                                  "owner_cases": owners})

    return {"safe_relink": safe_relink, "safe_folder": safe_folder,
            "review_gone": review_gone, "review_shared": review_shared,
            "review_orphan": review_orphan, "redundant_orphan": redundant_orphan,
            "n_cases": len(cases), "n_docs": len(docs), "n_files": len(all_paths)}


# ───────────────────────── reporte ─────────────────────────

def print_report(res, base, apply):
    print("=" * 72)
    print(f"RECONCILIADOR DISCO↔DB  ({'APPLY' if apply else 'DRY-RUN'})  "
          f"casos={res['n_cases']} docs={res['n_docs']} archivos={res['n_files']}")
    print(f"BASE_DIR: {base}")
    print("=" * 72)

    print(f"\n🟢 SAFE-RELINK (file_path roto → archivo byte-idéntico en su carpeta): "
          f"{len(res['safe_relink'])}")
    by_case = Counter(r["case_id"] for r in res["safe_relink"])
    for cid, n in by_case.most_common(12):
        print(f"   c{cid}: {n} docs")

    print(f"\n🟢 SAFE-FOLDER (folder_path → BASE/folder_name): {len(res['safe_folder'])}")
    for r in res["safe_folder"][:20]:
        print(f"   c{r['case_id']} [{r['why']}] → {os.path.basename(r['new'])}")

    print(f"\n🟡 REVIEW-SHARED (folder_path ambiguo, sin carpeta propia clara): "
          f"{len(res['review_shared'])}")
    for r in res["review_shared"][:20]:
        print(f"   c{r['case_id']} [{r['why']}] sharers={r['sharers']} "
              f"propia-existe={r['desired_exists']} docs-en={r.get('doc_dirs')} — {r['folder_name']}")

    print(f"\n🟡 REVIEW-GONE (file_path roto, sin archivo byte-idéntico en disco): "
          f"{len(res['review_gone'])}")
    gb = Counter(r["case_id"] for r in res["review_gone"])
    for cid, n in gb.most_common(12):
        print(f"   c{cid}: {n} docs")

    print(f"\n🟠 REDUNDANT-ORPHAN (archivo dup de un doc ya registrado del caso): "
          f"{len(res.get('redundant_orphan', []))}  [--quarantine-redundant-orphans]")
    rb = Counter(r["folder"] for r in res.get("redundant_orphan", []))
    for folder, n in rb.most_common(12):
        print(f"   {n:>3}  {folder}")

    print(f"\n🟡 REVIEW-ORPHAN (archivo en disco sin fila documents, no atribuible): "
          f"{len(res['review_orphan'])}")
    ob = Counter(r["folder"] for r in res["review_orphan"])
    for folder, n in ob.most_common(15):
        print(f"   {n:>3}  {folder}")


def write_review_csv(res):
    with open(REVIEW_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["categoria", "case_id", "folder", "doc_id", "filename",
                    "detalle", "path"])
        for r in res["review_shared"]:
            w.writerow(["REVIEW-SHARED", r["case_id"], r["folder_name"], "", "",
                        f"{r['why']} sharers={r['sharers']} propia_existe={r['desired_exists']}",
                        r["old"]])
        for r in res["review_gone"]:
            w.writerow(["REVIEW-GONE", r["case_id"], "", r["doc_id"], r["filename"],
                        f"sha_hits={r['sha_hits']}", r["old"]])
        for r in res["review_orphan"]:
            w.writerow(["REVIEW-ORPHAN", "", r["folder"], "", os.path.basename(r["path"]),
                        f"owner_cases={r['owner_cases']}", r["path"]])
    print(f"\n📄 Cola de revisión: {REVIEW_CSV.relative_to(ROOT)} "
          f"({len(res['review_shared'])+len(res['review_gone'])+len(res['review_orphan'])} filas)")


# ───────────────────────── apply ─────────────────────────

def apply_fixes(db, res):
    bak = DB_PATH.with_suffix(f".db.bak_pre_reconcile_disk_{time.strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(DB_PATH, bak)
    print(f"\nbackup: {bak.name}")
    n_relink = n_folder = 0
    for r in res["safe_relink"]:
        db.execute("UPDATE documents SET file_path=? WHERE id=?", (r["new"], r["doc_id"]))
        n_relink += 1
    for r in res["safe_folder"]:
        db.execute("UPDATE cases SET folder_path=? WHERE id=?", (r["new"], r["case_id"]))
        n_folder += 1
    db.commit()
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"✓ SAFE-RELINK aplicados: {n_relink}")
    print(f"✓ SAFE-FOLDER aplicados: {n_folder}")
    print(f"backup en {bak.name}. Corre la red de seguridad: "
          f"venv/bin/python scripts/v9_test_db.py")


def quarantine_redundant_orphans(res) -> int:
    """Mueve a cuarentena los archivos huérfanos byte-idénticos a un doc YA registrado
    (con copia viva) del caso dueño de su carpeta. No toca la DB — son archivos sin fila.
    Reversible: los archivos quedan en data/quarantine_misfiled/reconcile_disk_orphans/."""
    items = res.get("redundant_orphan", [])
    if not items:
        print("\nNo hay orphans redundantes que cuarentenar.")
        return 0
    QUARANTINE.mkdir(parents=True, exist_ok=True)
    moved = 0
    for r in items:
        src = r["path"]
        if not os.path.exists(src):
            continue
        dest = QUARANTINE / f"c{r['case_id']}_{r['folder']}_{os.path.basename(src)}"
        n = 1
        while dest.exists():
            dest = QUARANTINE / f"c{r['case_id']}_{r['folder']}_{n}_{os.path.basename(src)}"
            n += 1
        shutil.move(src, str(dest))
        moved += 1
    print(f"\n🟠 REDUNDANT-ORPHAN cuarentenados: {moved} → "
          f"{QUARANTINE.relative_to(ROOT)}")
    return moved


# ───────────────────────── main ─────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Aplica SAFE-* (default: dry-run)")
    ap.add_argument("--quarantine-redundant-orphans", action="store_true",
                    help="Mueve a cuarentena los orphans byte-idénticos a un doc ya "
                         "registrado del caso (requiere --apply)")
    args = ap.parse_args()

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")

    base = resolve_base_dir(db)
    print(f"Indexando disco bajo {base} …")
    disk = build_disk_index(base)
    res = analyze(db, base, disk)

    print_report(res, base, args.apply)
    write_review_csv(res)

    if not args.apply:
        n = len(res["safe_relink"]) + len(res["safe_folder"])
        extra = (f" + {len(res.get('redundant_orphan', []))} orphans redundantes a cuarentena"
                 if args.quarantine_redundant_orphans else "")
        print(f"\n(dry-run — nada modificado. --apply aplica {n} fixes seguros{extra}.)")
        db.close()
        return 0

    if res["safe_relink"] or res["safe_folder"]:
        apply_fixes(db, res)
    else:
        print("\nNada seguro que aplicar en DB.")
    if args.quarantine_redundant_orphans:
        quarantine_redundant_orphans(res)
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
