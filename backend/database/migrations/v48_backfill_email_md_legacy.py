"""Backfill v4.8 v2: vincular EMAIL_MD legacy (217 docs) sin email_id.

Heuristicas complementarias al backfill original:

D) Patron `Email_EXTRACCION_<hash>_<case>_<tipo>.md` — el <hash> es parte del
   gmail message_id. Match directo contra emails.message_id.

E) Patron `Email_YYYYMMDD_<subject>.md` — match por case_id + fecha proxima
   (tolerancia +-3 dias) + primeras 3 palabras del subject normalizadas.

Idempotente: skip docs ya vinculados.
"""

from __future__ import annotations

import argparse
import logging
import re
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from backend.database.database import SessionLocal
from backend.database.models import Document, Email

logger = logging.getLogger("tutelas.migrations")


def _normalize(s: str) -> str:
    if not s:
        return ""
    s = s.upper()
    for a, b in [("A", "A"), ("E", "E"), ("I", "I"), ("O", "O"), ("U", "U"), ("N", "N")]:
        s = s.replace(a, b)
    s = re.sub(r"[^A-Z0-9]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def _first_words_key(text: str, n: int = 3) -> str:
    """Tokens normalizados de las primeras N palabras reales."""
    norm = _normalize(text)
    parts = [p for p in norm.split("_") if p and len(p) >= 3]
    return "_".join(parts[:n])


def backfill_email_md_legacy(db: Session, dry_run: bool = False) -> dict:
    stats: dict = {
        "total_legacy_md": 0,
        "matched_D_message_hash": 0,
        "matched_E_subject_date": 0,
        "unmatched": 0,
        "dry_run": dry_run,
    }

    candidates = db.query(Document).filter(
        Document.doc_type == "EMAIL_MD",
        Document.email_id.is_(None),
    ).all()
    stats["total_legacy_md"] = len(candidates)
    if not candidates:
        return stats

    logger.info("legacy backfill: %d EMAIL_MD sin email_id", len(candidates))

    all_emails = db.query(Email).all()

    # Estrategia D: index por hash hex de message_id
    hash_index: dict = {}
    for em in all_emails:
        mid = em.message_id or ""
        for m in re.finditer(r"([0-9a-f]{12,})", mid.lower()):
            hash_index[m.group(1)] = em

    # Estrategia E: index por (case_id, YYYYMMDD, first_words)
    subject_index: dict = {}
    for em in all_emails:
        if not em.date_received or not em.case_id:
            continue
        date_key = em.date_received.strftime("%Y%m%d")
        fw = _first_words_key(em.subject or "", n=3)
        key = (em.case_id, date_key, fw)
        subject_index[key] = em

    for doc in candidates:
        if not doc.filename:
            stats["unmatched"] += 1
            continue

        fn = doc.filename
        matched = False

        for m in re.finditer(r"([0-9a-f]{12,})", fn.lower()):
            hash_token = m.group(1)
            if hash_token in hash_index:
                em = hash_index[hash_token]
                if not dry_run:
                    doc.email_id = em.id
                    doc.email_message_id = em.message_id
                stats["matched_D_message_hash"] += 1
                matched = True
                break

        if matched:
            continue

        m = re.match(r"Email_(\d{8})_(.+)\.md$", fn)
        if m and doc.case_id:
            date_token = m.group(1)
            subject_part = m.group(2)
            fw = _first_words_key(subject_part, n=3)
            key = (doc.case_id, date_token, fw)
            if key in subject_index:
                em = subject_index[key]
                if not dry_run:
                    doc.email_id = em.id
                    doc.email_message_id = em.message_id
                stats["matched_E_subject_date"] += 1
                matched = True
            else:
                try:
                    dt = datetime.strptime(date_token, "%Y%m%d")
                    for delta in range(-3, 4):
                        alt_date = (dt + timedelta(days=delta)).strftime("%Y%m%d")
                        alt_key = (doc.case_id, alt_date, fw)
                        if alt_key in subject_index:
                            em = subject_index[alt_key]
                            if not dry_run:
                                doc.email_id = em.id
                                doc.email_message_id = em.message_id
                            stats["matched_E_subject_date"] += 1
                            matched = True
                            break
                except ValueError:
                    pass

        if not matched:
            stats["unmatched"] += 1

    if not dry_run:
        db.commit()

    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    import json
    with SessionLocal() as db:
        result = backfill_email_md_legacy(db, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
