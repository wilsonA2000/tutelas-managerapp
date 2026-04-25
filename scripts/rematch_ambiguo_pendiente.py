#!/usr/bin/env python3
"""Re-aplica el matcher v6.0.1 (pesos subidos) sobre emails AMBIGUO + PENDIENTE
    del experimento TUTELAS 2026 B. Rescata los que ahora alcanzan HIGH.

Uso:
    TUTELAS_ENV_FILE=.env.experiment_b python3 scripts/rematch_ambiguo_pendiente.py
    TUTELAS_ENV_FILE=.env.experiment_b python3 scripts/rematch_ambiguo_pendiente.py --dry-run
    TUTELAS_ENV_FILE=.env.experiment_b python3 scripts/rematch_ambiguo_pendiente.py --also-ignore  # aplica IGNORE_SUBJECTS/SENDERS ampliado

Salida: JSON con before/after, delta por status, emails rescatados.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.database.database import SessionLocal
from backend.database.models import Case, Email
from backend.email.case_lookup_cache import get_cache
from backend.email.gmail_monitor import (
    _normalize_typos,
    _should_ignore,
    classify_email_type,
    extract_accionante,
    extract_forest,
    extract_radicado,
)
from backend.email.matcher import EmailSignals, resolve_thread_parent, score_case_match
from backend.email.rad_utils import reconcile as rad_reconcile
from backend.agent.regex_library import CC_ACCIONANTE


def extract_signals_from_row(email: Email) -> EmailSignals:
    """Re-extrae señales desde subject + body_preview guardados en DB."""
    subject = _normalize_typos(email.subject or "")
    body = email.body_preview or ""
    full_text = f"{subject} {body}"

    rad_data = extract_radicado(full_text)
    # attachments eran JSON [{"filename":...}, ...]
    att_names = []
    try:
        if email.attachments:
            att_names = [
                a.get("filename", "") if isinstance(a, dict) else str(a)
                for a in (email.attachments or [])
            ]
    except Exception:
        pass
    forest = extract_forest(body, att_names)

    # Reconcile rad23 <-> rad_corto
    r23, rc = rad_reconcile(rad_data.get("radicado_23", ""), rad_data.get("radicado_corto", ""))

    # CC
    cc = ""
    try:
        cc_m = CC_ACCIONANTE.pattern.search(f"{subject}\n{body[:5000]}")
        if cc_m:
            cc = cc_m.group(1)
    except Exception:
        pass

    acc = extract_accionante(subject, body)

    return EmailSignals(
        rad23=r23,
        rad_corto=rc,
        forest=forest,
        cc_accionante=cc,
        accionante_name=acc,
        sender=email.sender or "",
        thread_parent_case_id=None,  # se resuelve abajo
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="No escribe cambios")
    ap.add_argument("--also-ignore", action="store_true",
                    help="Aplica IGNORE_SUBJECTS/SENDERS ampliado (marca IGNORED los que antes estaban procesados)")
    ap.add_argument("--create-new-cases", action="store_true",
                    help="Para huérfanos con rad_corto o forest pero sin match, crea caso nuevo")
    ap.add_argument("--min-score", type=int, default=70, help="Umbral para auto-match (default 70)")
    args = ap.parse_args()

    db = SessionLocal()
    cache = get_cache()
    cache.build(db)
    print(f"[cache] {cache.size()}")

    # Traer emails candidatos
    targets = db.query(Email).filter(
        Email.status.in_(["AMBIGUO", "PENDIENTE"]),
        Email.case_id.is_(None),  # solo los que NO tienen caso
    ).all()

    before = Counter(e.status for e in targets)
    print(f"[input] candidatos: {len(targets)} — {dict(before)}")

    rescued_auto = []
    rescued_ignored = []
    promoted_ambiguo = []
    new_cases_created = []
    still_orphan = []

    for e in targets:
        subject = _normalize_typos(e.subject or "")
        sender = e.sender or ""

        # Opción: aplicar IGNORE ampliado
        if args.also_ignore and _should_ignore(subject, sender):
            rescued_ignored.append({
                "id": e.id, "subject": subject[:80], "sender": sender[:50],
            })
            if not args.dry_run:
                e.status = "IGNORED"
            continue

        signals = extract_signals_from_row(e)

        # Thread parent (por si ahora existe el padre)
        if e.in_reply_to or e.references_header:
            try:
                signals.thread_parent_case_id = resolve_thread_parent(
                    db, e.in_reply_to, e.references_header,
                )
            except Exception:
                pass

        if not signals.has_any():
            still_orphan.append({
                "id": e.id, "subject": subject[:80], "reason": "sin señales",
            })
            continue

        match = score_case_match(db, cache, signals)

        if match.case_id and match.score >= args.min_score:
            rescued_auto.append({
                "id": e.id,
                "subject": subject[:80],
                "score_before": e.match_score,
                "score_after": match.score,
                "case_id": match.case_id,
                "breakdown": match.breakdown,
                "prev_status": e.status,
            })
            if not args.dry_run:
                e.case_id = match.case_id
                e.status = "ASIGNADO"
                e.match_score = match.score
                e.match_confidence = "HIGH"
                e.match_signals_json = match.to_signals_json()
        elif match.case_id and match.score >= 40:
            promoted_ambiguo.append({
                "id": e.id,
                "subject": subject[:80],
                "score_after": match.score,
                "case_suggested": match.case_id,
                "prev_status": e.status,
            })
            if not args.dry_run and e.status == "PENDIENTE":
                # Promover PENDIENTE a AMBIGUO (ahora al menos hay sugerencia)
                e.status = "AMBIGUO"
                e.match_score = match.score
                e.match_confidence = "MEDIUM"
                e.match_signals_json = match.to_signals_json()
        elif args.create_new_cases and (signals.rad_corto or signals.forest):
            # Sin match pero tiene señal suficiente para crear caso
            from backend.email.gmail_monitor import create_new_case
            rad_data = {
                "radicado_23": signals.rad23,
                "radicado_corto": signals.rad_corto,
                "forest": signals.forest,
                "cc_accionante": signals.cc_accionante,
            }
            if not args.dry_run:
                try:
                    case = create_new_case(db, rad_data, signals.accionante_name or "")
                    if case:
                        db.flush()
                        e.case_id = case.id
                        e.status = "ASIGNADO"
                        e.match_score = 0  # creación, no match
                        e.match_confidence = "NEW_CASE"
                        # Actualizar cache
                        cache.refresh_one(db, case.id)
                        new_cases_created.append({
                            "email_id": e.id, "case_id": case.id,
                            "folder": case.folder_name,
                            "rad_corto": signals.rad_corto, "forest": signals.forest,
                        })
                        continue
                except Exception as ex:
                    print(f"[WARN] create_new_case fail email {e.id}: {ex}")
            else:
                new_cases_created.append({
                    "email_id": e.id, "would_create_for": signals.rad_corto or signals.forest,
                    "subject": subject[:80],
                })
                continue
            still_orphan.append({
                "id": e.id, "subject": subject[:80],
                "score": match.score,
                "rad23": signals.rad23[:20], "rad_corto": signals.rad_corto,
                "forest": signals.forest,
            })
        else:
            still_orphan.append({
                "id": e.id, "subject": subject[:80],
                "score": match.score,
                "rad23": signals.rad23[:20], "rad_corto": signals.rad_corto,
                "forest": signals.forest,
            })

    if not args.dry_run:
        db.commit()

    # Resumen
    after_db = Counter(e.status for e in db.query(Email).all())
    report = {
        "dry_run": args.dry_run,
        "input_count": len(targets),
        "status_before": dict(before),
        "rescued_auto": len(rescued_auto),
        "rescued_ignored": len(rescued_ignored),
        "promoted_ambiguo": len(promoted_ambiguo),
        "new_cases_created": len(new_cases_created),
        "still_orphan": len(still_orphan),
        "final_status_dist": dict(after_db),
        "samples": {
            "auto": rescued_auto[:10],
            "ignored": rescued_ignored[:10],
            "promoted": promoted_ambiguo[:10],
            "new_cases": new_cases_created[:10],
            "orphan": still_orphan[:10],
        },
    }
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
