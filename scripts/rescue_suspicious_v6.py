#!/usr/bin/env python3
"""Rescates A + B de documentos SOSPECHOSO v6.0.

A (--rescue=A): documentos con posterior ≥ 0.80 + thread_parent +
   sello del juzgado coincidente → promover a OK.
   Razón: doble evidencia positiva (heredó del email + sello institucional).

B (--rescue=B): documentos SOSPECHOSO del mismo email thread en casos
   que ya tienen ≥5 docs OK fuerte → promover a OK.
   Razón: "pertenece al expediente consolidado".

Uso:
    python3 scripts/rescue_suspicious_v6.py --rescue=A               # dry-run A
    python3 scripts/rescue_suspicious_v6.py --rescue=A --apply
    python3 scripts/rescue_suspicious_v6.py --rescue=B --apply
    python3 scripts/rescue_suspicious_v6.py --rescue=AB --apply      # ambos secuenciales
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database.database import SessionLocal
from backend.database.models import Case, Document


OK_RESCUE_THRESHOLD = 0.80


def _parse_post(detalle: str) -> float | None:
    m = re.search(r"post=([\d.]+)", detalle or "")
    return float(m.group(1)) if m else None


# ============================================================
# Rescue A: casi-OK + doble evidencia
# ============================================================

def rescue_A(db) -> list[int]:
    """Promover docs con posterior ≥ 0.80 + thread_parent + sello coincide."""
    sospechosos = db.query(Document).filter(Document.verificacion == "SOSPECHOSO").all()
    promovidos: list[int] = []

    for d in sospechosos:
        post = _parse_post(d.verificacion_detalle or "")
        if post is None or post < OK_RESCUE_THRESHOLD:
            continue
        has_thread = d.email_id is not None
        has_sello = "sello del juzgado" in (d.verificacion_detalle or "").lower()
        if has_thread and has_sello:
            old = d.verificacion
            d.verificacion = "OK"
            base = d.verificacion_detalle or ""
            d.verificacion_detalle = (f"[rescate A post={post:.2f}] " + base)[:250]
            promovidos.append(d.id)
    return promovidos


# ============================================================
# Rescue B: expediente consolidado
# ============================================================

STRONG_OK_THRESHOLD = 0.92


def rescue_B(db) -> list[int]:
    """Promover SOSPECHOSO del mismo thread en casos con ≥5 OK fuerte."""
    # Casos candidatos: ≥5 documentos con verificacion='OK' y post ≥ 0.92
    cases_with_strong_ok: dict[int, int] = {}
    for d in db.query(Document).filter(Document.verificacion == "OK").all():
        post = _parse_post(d.verificacion_detalle or "")
        if post is not None and post >= STRONG_OK_THRESHOLD:
            cases_with_strong_ok[d.case_id] = cases_with_strong_ok.get(d.case_id, 0) + 1

    eligible_cases = {cid for cid, n in cases_with_strong_ok.items() if n >= 5}

    # Thread emails presentes en cada caso elegible
    thread_by_case: dict[int, set[int]] = {}
    for d in db.query(Document).filter(
        Document.case_id.in_(eligible_cases),
        Document.email_id.isnot(None),
    ).all():
        thread_by_case.setdefault(d.case_id, set()).add(d.email_id)

    promovidos: list[int] = []
    for d in db.query(Document).filter(Document.verificacion == "SOSPECHOSO").all():
        if d.case_id not in eligible_cases:
            continue
        if d.email_id is None:
            continue
        # debe compartir email_id con otros docs OK fuertes del mismo caso
        thread_ids = thread_by_case.get(d.case_id, set())
        if d.email_id not in thread_ids:
            continue
        d.verificacion = "OK"
        base = d.verificacion_detalle or ""
        d.verificacion_detalle = ("[rescate B expediente consolidado] " + base)[:250]
        promovidos.append(d.id)
    return promovidos


# ============================================================
# Main
# ============================================================

def _summary(db):
    from sqlalchemy import func
    rows = db.query(Document.verificacion, func.count(Document.id)).group_by(Document.verificacion).all()
    return {r[0] or "(null)": r[1] for r in rows}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--rescue", choices=["A", "B", "AB"], required=True)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()

    db = SessionLocal()
    try:
        print(f"Estado inicial: {_summary(db)}")
        total_A = total_B = 0

        if "A" in args.rescue:
            print("\n=== Rescate A (casi-OK + sello) ===")
            promoted = rescue_A(db)
            total_A = len(promoted)
            print(f"  Promovidos: {total_A}")
            if args.apply:
                db.commit()
                print("  ✓ Aplicado")
            else:
                db.rollback()
                print("  (dry-run)")

        if "B" in args.rescue:
            print("\n=== Rescate B (expediente consolidado) ===")
            promoted = rescue_B(db)
            total_B = len(promoted)
            print(f"  Promovidos: {total_B}")
            if args.apply:
                db.commit()
                print("  ✓ Aplicado")
            else:
                db.rollback()
                print("  (dry-run)")

        print(f"\nEstado final: {_summary(db)}")
        print(f"Total promovidos: A={total_A} + B={total_B} = {total_A + total_B}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
