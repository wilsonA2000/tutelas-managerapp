#!/usr/bin/env python3
"""Remap paths WSL → Linux nativo después de migración Win→Linux.

Cambia:
    /mnt/c/Users/wilso/Documents/  →  /home/wilsonarguello/Documentos/

Afecta:
    - Document.file_path  (4122 filas)
    - Case.folder_path    (221 filas)

Uso:
    python3 scripts/remap_paths_wsl_to_linux.py             # dry-run
    python3 scripts/remap_paths_wsl_to_linux.py --apply     # aplica
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal
from backend.database.models import Case, Document

OLD_PREFIX = "/mnt/c/Users/wilso/Documents/"
NEW_PREFIX = "/home/wilsonarguello/Documentos/"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        # Documents
        docs = db.query(Document).filter(Document.file_path.like(f"{OLD_PREFIX}%")).all()
        print(f"Documents a remapear: {len(docs)}")
        sample_doc_path = None
        for d in docs:
            new_path = d.file_path.replace(OLD_PREFIX, NEW_PREFIX, 1)
            if sample_doc_path is None:
                sample_doc_path = (d.file_path, new_path, Path(new_path).exists())
            if args.apply:
                d.file_path = new_path
        if sample_doc_path:
            old, new, exists = sample_doc_path
            print(f"  Sample old: {old}")
            print(f"  Sample new: {new}")
            print(f"  Existe en disco: {exists}")

        # Cases
        cases = db.query(Case).filter(Case.folder_path.like(f"{OLD_PREFIX}%")).all()
        print(f"Cases a remapear:     {len(cases)}")
        sample_case_path = None
        for c in cases:
            new_path = c.folder_path.replace(OLD_PREFIX, NEW_PREFIX, 1)
            if sample_case_path is None:
                sample_case_path = (c.folder_path, new_path, Path(new_path).exists())
            if args.apply:
                c.folder_path = new_path
        if sample_case_path:
            old, new, exists = sample_case_path
            print(f"  Sample old: {old}")
            print(f"  Sample new: {new}")
            print(f"  Existe en disco: {exists}")

        if args.apply:
            db.commit()
            print("\n✅ Cambios aplicados")
        else:
            print("\n(dry-run — pasar --apply para aplicar)")

        # Validar que la mayoría existen
        if args.apply:
            from sqlalchemy import func
            total = db.query(func.count(Document.id)).scalar()
            ok = sum(1 for d in db.query(Document).all() if d.file_path and Path(d.file_path).exists())
            print(f"\nValidación: {ok}/{total} documentos tienen path válido en disco")
    finally:
        db.close()


if __name__ == "__main__":
    main()
