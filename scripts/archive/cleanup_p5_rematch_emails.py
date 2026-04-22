"""P5 — Re-match emails huérfanos usando cognición v5.3.3.

Estrategia:
- Para cada email con case_id=NULL:
  - Extraer rad23, FOREST, accionante del subject + body.
  - Usar match_to_case() existente con datos enriquecidos.
  - Si falla, intentar con cognición sobre el body completo.
- NO modifica el body del email; solo actualiza FK case_id.

Dry-run por defecto.
"""

import argparse
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from sqlalchemy import text
from backend.database.database import SessionLocal
from backend.database.models import Email, Case, AuditLog


RAD23 = re.compile(r"\b(68[\d]{3,5}[-\s\.\u2013\u2014]?\d{2}[-\s\.\u2013\u2014]?\d{2}[-\s\.\u2013\u2014]?\d{3}[-\s\.\u2013\u2014]?\d{4}[-\s\.\u2013\u2014]?\d{5}[-\s\.\u2013\u2014]?\d{2})")
FOREST = re.compile(r"\b(2026\d{7})\b")
RAD_CORTO = re.compile(r"\b(20\d{2})-?(\d{4,5})\b")


def find_case_for_email(db, em: Email) -> tuple[int, str, float] | None:
    subject = em.subject or ""
    body = em.body_preview or ""
    haystack = subject + "\n" + body[:10000]

    # 1. Rad23 en subject/body
    m = RAD23.search(haystack)
    if m:
        rad = m.group(1)
        rd = re.sub(r"[^0-9]", "", rad)
        rows = db.execute(
            text("SELECT id, radicado_23_digitos FROM cases WHERE radicado_23_digitos IS NOT NULL")
        ).fetchall()
        for r in rows:
            db_rad = re.sub(r"[^0-9]", "", r[1] or "")
            if rd == db_rad:
                return (r[0], f"rad23:{rad}", 0.95)

    # 2. FOREST
    m = FOREST.search(haystack)
    if m:
        forest = m.group(1)
        r = db.execute(
            text("SELECT id FROM cases WHERE radicado_forest=:f LIMIT 1"),
            {"f": forest},
        ).fetchone()
        if r:
            return (r[0], f"forest:{forest}", 0.9)

    # 3. Radicado corto "2026-00XXX"
    m = RAD_CORTO.search(subject)  # solo en subject para evitar ruido
    if m:
        year = m.group(1)
        cons = m.group(2).zfill(5)
        short = f"{year}-{cons}"
        r = db.execute(
            text("SELECT id FROM cases WHERE folder_name LIKE :n LIMIT 2"),
            {"n": f"{short}%"},
        ).fetchall()
        if len(r) == 1:
            return (r[0][0], f"rad_corto:{short}", 0.8)

    # 4. Cognición: extraer accionante desde body
    try:
        from backend.cognition import extract_actors, classify_zones
        if len(body) > 200:
            actors = extract_actors(body[:8000], classify_zones(body[:8000]))
            if actors.accionantes:
                acc = actors.accionantes[0].name.strip().upper()
                r = db.execute(
                    text("SELECT id FROM cases WHERE UPPER(accionante) LIKE :n LIMIT 2"),
                    {"n": f"%{acc[:30]}%"},
                ).fetchall()
                if len(r) == 1:
                    return (r[0][0], f"accionante:{acc[:30]}", 0.7)
    except Exception:
        pass

    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        orphans = db.query(Email).filter(Email.case_id.is_(None)).all()
        print(f"Emails huérfanos: {len(orphans)}")
        print()

        matched = 0
        ambig = 0
        no_match = 0

        for em in orphans:
            target = find_case_for_email(db, em)
            if not target:
                no_match += 1
                continue
            case_id, reason, conf = target
            print(f"  email#{em.id} subject={em.subject[:50]!r}")
            print(f"    → case #{case_id} ({reason}, conf={conf:.2f})")
            if args.apply and conf >= 0.85:
                db.execute(
                    text("UPDATE emails SET case_id=:c WHERE id=:id"),
                    {"c": case_id, "id": em.id},
                )
                db.add(AuditLog(
                    case_id=case_id,
                    field_name=f"email_{em.id}",
                    old_value="null",
                    new_value=f"case_{case_id}",
                    action="P5_REMATCH_EMAIL",
                    source=f"cleanup_p5; {reason}",
                ))
                matched += 1
            elif conf < 0.85:
                ambig += 1

        if args.apply:
            db.commit()
            print(f"\n✅ Matched: {matched} | Ambiguos: {ambig} | Sin match: {no_match}")
        else:
            db.rollback()
            print(f"\n⚠️  DRY-RUN. {matched+ambig} candidatos | Sin match: {no_match}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
