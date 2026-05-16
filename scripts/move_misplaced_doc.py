#!/usr/bin/env python3
"""Mover un documento mal colocado a su case correcto.

A diferencia de `sibling_mover.move_document_or_package`, que SIEMPRE mueve el
paquete completo del email cuando el doc tiene email_id, este helper acepta dos
modos:

  --mode=solo     : mueve solo ese doc, deja el email_id intacto (el doc
                    queda asociado al email original aunque el case cambie).
                    Útil cuando un email contiene docs mezclados de dos
                    expedientes (ej. juzgado multiplexa notificaciones).

  --mode=package  : mueve el paquete completo (equivalente a sibling_mover).
                    Útil cuando todos los docs del email pertenecen al destino.

Dry-run por defecto. Idempotente: si el doc ya está en el destino, no hace nada.

Uso:
    ./venv/bin/python3 scripts/move_misplaced_doc.py --doc 4336 --target 316
    ./venv/bin/python3 scripts/move_misplaced_doc.py --doc 4336 --target 316 --apply
    ./venv/bin/python3 scripts/move_misplaced_doc.py --doc 2331 --target 259 --mode=package --apply
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal  # noqa: E402
from backend.database.models import AuditLog, Case, Document, Email  # noqa: E402


def move_doc_solo(db, doc: Document, target: Case, reason: str) -> dict:
    """Mueve un solo doc físico + DB row, sin tocar email ni hermanos."""
    out = {"moved": [], "errors": []}
    old_case = doc.case_id
    target_folder = Path(target.folder_path)
    if not target_folder.exists():
        out["errors"].append(f"Target folder no existe: {target_folder}")
        return out

    if doc.file_path and Path(doc.file_path).exists():
        old_path = Path(doc.file_path)
        new_path = target_folder / doc.filename
        # Evitar colisión: agregar _moved1, _moved2, ...
        i = 1
        orig = new_path
        while new_path.exists():
            new_path = target_folder / f"{orig.stem}_moved{i}{orig.suffix}"
            i += 1
        shutil.move(str(old_path), str(new_path))
        doc.file_path = str(new_path)
        out["moved"].append({"doc_id": doc.id, "old_path": str(old_path), "new_path": str(new_path)})
    else:
        out["moved"].append({"doc_id": doc.id, "old_path": None, "new_path": None,
                              "note": "archivo no existe en disco — solo actualizo DB"})

    doc.case_id = target.id
    doc.verificacion = "OK"
    doc.verificacion_detalle = f"Movido desde case {old_case} (modo solo, email_id={doc.email_id} intacto). Razón: {reason}"
    doc.suggested_target_case_id = None
    doc.suggested_reason = None

    db.add(AuditLog(
        case_id=target.id,
        field_name="documento",
        old_value=f"case_id={old_case} doc_id={doc.id}",
        new_value=f"case_id={target.id} doc_id={doc.id}",
        action="MANUAL_MOVE",
        source=f"move_misplaced_doc:solo:{reason}",
    ))
    return out


def move_package(db, doc: Document, target: Case, reason: str) -> dict:
    """Delega en sibling_mover.move_document_or_package."""
    from backend.services.sibling_mover import move_document_or_package
    return move_document_or_package(db, doc.id, target.id, reason=reason)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--doc", type=int, required=True, help="ID del doc a mover")
    ap.add_argument("--target", type=int, required=True, help="case_id destino")
    ap.add_argument("--mode", choices=("solo", "package"), default="solo",
                    help="solo = mueve solo este doc; package = mueve todo el email")
    ap.add_argument("--reason", default="cleanup_misplaced",
                    help="texto para AuditLog y verificacion_detalle")
    ap.add_argument("--apply", action="store_true", help="ejecuta (sin esto: dry-run)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        doc = db.get(Document, args.doc)
        if not doc:
            print(f"ERROR: doc#{args.doc} no existe", file=sys.stderr)
            return 1
        target = db.get(Case, args.target)
        if not target:
            print(f"ERROR: case#{args.target} no existe", file=sys.stderr)
            return 1

        if doc.case_id == target.id:
            print(f"NO-OP: doc#{doc.id} ya está en case#{target.id}")
            return 0

        src = db.get(Case, doc.case_id)
        print(f"doc#{doc.id} [{doc.doc_type}] {doc.filename}")
        print(f"  archivo: {doc.file_path}")
        print(f"  email_id: {doc.email_id}")
        print(f"  desde: case#{src.id} «{src.folder_name}»")
        print(f"  hacia: case#{target.id} «{target.folder_name}»")
        print(f"  modo:  {args.mode}")

        if args.mode == "package" and doc.email_id is not None:
            # Mostrar todos los hermanos
            sibs = db.query(Document).filter(Document.email_id == doc.email_id).all()
            print(f"  paquete email#{doc.email_id} ({len(sibs)} doc(s)):")
            for s in sibs:
                marker = ' ← origen' if s.id == doc.id else ''
                print(f"    doc#{s.id:5d} {s.doc_type:<18} {s.filename}{marker}")

        if not args.apply:
            print("\n(dry-run — nada se modificó)")
            return 0

        if args.mode == "solo":
            r = move_doc_solo(db, doc, target, args.reason)
        else:
            r = move_package(db, doc, target, args.reason)

        if r.get("errors"):
            print(f"  ERRORES: {r['errors']}", file=sys.stderr)
            db.rollback()
            return 1

        # Si modo package y se movió el email .md, reasignar también el Email row
        if args.mode == "package" and doc.email_id:
            email = db.get(Email, doc.email_id)
            if email and email.case_id != target.id:
                email.case_id = target.id
                email.status = "ASIGNADO"

        db.commit()
        moved_count = len(r.get("moved", r.get("moved_ids", [])))
        print(f"\n  ✓ aplicado: {moved_count} doc(s) movido(s) → case#{target.id}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
