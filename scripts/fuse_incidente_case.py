#!/usr/bin/env python3
"""Fusiona un case-shell que en realidad es el INCIDENTE DE DESACATO de otro case.

Cuando el juzgado asigna rad propio al incidente (p.ej. radicado del incidente
2026-00032 sobre la tutela 2026-00008), el matcher de Gmail crea un case shell
separado para ese rad. Lo correcto: los docs del incidente viven como
sub-carpeta `incidente_<rad_corto>` dentro del case de la tutela.

Este script:
  1. Crea (si no existe) la sub-carpeta `incidente_<rad_corto>` en el folder del case rector.
  2. Mueve todos los archivos físicos del case-shell a la sub-carpeta.
  3. Para cada doc: actualiza case_id + marca incidente_radicado=<rad_corto> + AuditLog.
  4. Reasigna los emails del case-shell al rector.
  5. Borra el case-shell + su carpeta vacía.
  6. (Opcional) re-extrae el case rector con v9.

Dry-run por defecto.

Uso:
    ./venv/bin/python3 scripts/fuse_incidente_case.py --shell 246 --rector 92 --incidente-rad 2026-00032
    ./venv/bin/python3 scripts/fuse_incidente_case.py --shell 246 --rector 92 --incidente-rad 2026-00032 --apply
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal  # noqa: E402
from backend.database.models import AuditLog, Case, Document, Email  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shell", type=int, required=True, help="case_id del shell a fusionar")
    ap.add_argument("--rector", type=int, required=True, help="case_id del rector (la tutela origen)")
    ap.add_argument("--incidente-rad", required=True, help="rad-corto del incidente (ej. 2026-00032)")
    ap.add_argument("--apply", action="store_true", help="ejecuta (sin esto: dry-run)")
    ap.add_argument("--reextract", action="store_true", help="tras fusionar, re-extrae el rector con v9")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        shell = db.get(Case, args.shell)
        rector = db.get(Case, args.rector)
        if not shell or not rector:
            print(f"ERROR: shell #{args.shell} o rector #{args.rector} no existen", file=sys.stderr)
            return 1
        if shell.id == rector.id:
            print("ERROR: shell y rector son el mismo case", file=sys.stderr)
            return 1
        if not rector.folder_path or not os.path.exists(rector.folder_path):
            print(f"ERROR: folder del rector no existe: {rector.folder_path}", file=sys.stderr)
            return 1

        docs = db.query(Document).filter(Document.case_id == shell.id).all()
        emails = db.query(Email).filter(Email.case_id == shell.id).all()
        sub_folder = Path(rector.folder_path) / f"incidente_{args.incidente_rad}"

        print(f"Shell #{shell.id} «{shell.folder_name}»")
        print(f"  folder: {shell.folder_path}")
        print(f"  docs: {len(docs)}, emails: {len(emails)}")
        print(f"\nRector #{rector.id} «{rector.folder_name}»")
        print(f"  folder: {rector.folder_path}")
        print(f"\nSub-carpeta destino: {sub_folder}")
        print(f"\nModo: {'APPLY' if args.apply else 'DRY-RUN'}")

        if not args.apply:
            for d in docs[:6]:
                print(f"   doc#{d.id:5d} {d.doc_type:<20} {d.filename}")
            if len(docs) > 6:
                print(f"   … y {len(docs)-6} docs más")
            print("\n(dry-run — nada se modificó)")
            return 0

        # 1) crear sub-carpeta
        sub_folder.mkdir(parents=True, exist_ok=True)

        # 2-3) mover docs físicos + actualizar DB
        moved = 0
        for d in docs:
            new_path = sub_folder / d.filename
            i = 1
            orig = new_path
            while new_path.exists() and (not d.file_path or os.path.realpath(new_path) != os.path.realpath(d.file_path)):
                new_path = sub_folder / f"{orig.stem}_moved{i}{orig.suffix}"
                i += 1
            if d.file_path and os.path.exists(d.file_path):
                shutil.move(d.file_path, str(new_path))
                d.file_path = str(new_path)
            # Actualizar caseref + marca de incidente
            old_case = d.case_id
            d.case_id = rector.id
            d.incidente_radicado = args.incidente_rad
            d.verificacion = "OK"
            d.verificacion_detalle = (
                f"Movido desde case-shell #{old_case} (fusión incidente {args.incidente_rad} → tutela #{rector.id}). "
                f"El rad {args.incidente_rad} es el radicado del incidente, no de una tutela separada."
            )
            db.add(AuditLog(
                case_id=rector.id,
                field_name="documento",
                old_value=f"case_id={old_case} doc_id={d.id}",
                new_value=f"case_id={rector.id} doc_id={d.id} incidente_radicado={args.incidente_rad}",
                action="MANUAL_MOVE",
                source=f"fuse_incidente_case:{args.incidente_rad}",
            ))
            moved += 1

        # 4) reasignar emails
        for e in emails:
            e.case_id = rector.id
            if not e.status or e.status != "ASIGNADO":
                e.status = "ASIGNADO"

        # 5) borrar case-shell
        # Manejar FK de compliance_tracking (NOT NULL — debe vaciarse antes)
        from sqlalchemy import text
        db.execute(text("DELETE FROM compliance_tracking WHERE case_id=:cid"), {"cid": shell.id})
        old_folder = shell.folder_path
        db.delete(shell)
        db.commit()

        if old_folder and os.path.exists(old_folder):
            # Borrar carpeta si quedó vacía
            try:
                # Cualquier archivo residual (sub-carpetas vacías, etc.) — borrar todo el árbol
                shutil.rmtree(old_folder)
                print(f"  ✓ carpeta shell borrada: {old_folder}")
            except Exception as e:
                print(f"  ⚠ no se pudo borrar carpeta shell: {e}")

        print(f"\n✓ Fusión completada: {moved} docs + {len(emails)} emails → #{rector.id}")
        print(f"  Sub-carpeta: {sub_folder}")
        print(f"  Case-shell #{shell.id} borrado.")

        if args.reextract:
            print("\n→ Re-extracting #{rector.id} con v9…")
            from backend.v9.pipeline import extract_case
            res = extract_case(db, rector.id, dry_run=False, use_llm=False)
            db.commit()
            print(f"  ✓ {res.summary()}")

        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
