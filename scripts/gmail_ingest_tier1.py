"""Ingesta dirigida TIER 1: adjunta correos a su caso YA VERIFICADO (rad23 idéntico
o sin conflación). Bypassa el matcher (usamos case_id confirmado). NO toca campos del
caso (sin update_case_fields → no pisa curado). NO marca leído en Gmail (el monitor lo
hará al verlos ya en DB). Idempotente: dedup por message_id + (case,subject,sender,fecha).

Uso: gmail_ingest_tier1.py [--apply]   (default dry-run)
"""
import sys, json
from pathlib import Path
from datetime import timezone, timedelta
from email.utils import parsedate_to_datetime
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.database.database import SessionLocal
from backend.database.models import Case, Email, AuditLog
from backend.email.gmail_monitor import (
    _get_gmail_service, _extract_body_complete, download_attachments,
    save_email_md, _normalize_typos, _utcnow,
)

APPLY = "--apply" in sys.argv
tiers = json.load(open("data/gmail_ingest_tiers.json"))
T1 = tiers["t1"]
db = SessionLocal()
service = _get_gmail_service()
existing_ids = {e.message_id for e in db.query(Email.message_id).all()}

done = skipped = total_att = 0
for o in T1:
    cid = o["match_case_id"]; gid = o["gid"]
    case = db.query(Case).filter(Case.id == cid).first()
    if not case:
        print(f"  SKIP c{cid}: no existe"); skipped += 1; continue
    msg = service.users().messages().get(userId="me", id=gid, format="full").execute()
    hdrs = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
    message_id = hdrs.get("Message-ID", hdrs.get("Message-Id", gid))
    subject = _normalize_typos(hdrs.get("Subject", ""))
    sender = hdrs.get("From", "")
    date_str = hdrs.get("Date", "")
    irt = hdrs.get("In-Reply-To", "") or hdrs.get("In-reply-to", "")
    refs = hdrs.get("References", "") or hdrs.get("references", "")
    try:
        dt = parsedate_to_datetime(date_str)
        date_received = dt.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        date_received = _utcnow()
    body = _extract_body_complete(msg.get("payload", {}))

    # Dedup
    if message_id in existing_ids:
        print(f"  SKIP c{cid}: message_id ya en DB | {subject[:45]}"); skipped += 1; continue
    win = timedelta(days=1)
    dup = db.query(Email).filter(
        Email.case_id == cid, Email.subject == subject, Email.sender == sender,
        Email.date_received >= date_received - win, Email.date_received <= date_received + win,
    ).first()
    if dup:
        print(f"  SKIP c{cid}: dup (subject/sender/fecha) | {subject[:45]}"); skipped += 1; continue

    sig = json.dumps({"score": None, "confidence": "VERIFIED_MANUAL",
                      "breakdown": {"route": "rad23_confirmed_or_no_conflation",
                                    "rad23": o.get("rad23", ""), "rad_corto": o.get("rad_corto", ""),
                                    "case_rad23": o.get("case_rad23"), "rad23_equal": o.get("rad23_equal")},
                      "alternatives": o.get("confl_short_rad", [])}, ensure_ascii=False)

    print(f"  {'INGEST' if APPLY else 'DRY'} c{cid} ({(case.accionante or '')[:22]}) att={o['n_att']} | {subject[:45]}")
    if not APPLY:
        continue

    em = Email(message_id=message_id, subject=subject, sender=sender,
               date_received=date_received, body_preview=body or "", case_id=cid,
               attachments=[], status="ASIGNADO", processed_at=_utcnow(),
               in_reply_to=irt or None, references_header=refs or None,
               match_confidence="VERIFIED_MANUAL", match_signals_json=sig)
    db.add(em); db.flush()
    guardados, ignorados = download_attachments(service, gid, case, db,
                                                email_id=em.id, email_message_id=message_id)
    em.attachments = guardados
    if case.folder_path and body:
        save_email_md(Path(case.folder_path),
                      {"subject": subject, "sender": sender, "date": date_str, "folder_name": case.folder_name},
                      body, guardados, db=db, case_id=cid, email_id=em.id, email_message_id=message_id)
    db.add(AuditLog(case_id=cid, action="IMPORT_EMAIL_TIER1", source="gmail_ingest_tier1",
                    new_value=f"Email: {subject[:90]}"))
    existing_ids.add(message_id)
    done += 1; total_att += len(guardados)
    print(f"      → {len(guardados)} adjuntos guardados, {len(ignorados)} ignorados (dedup)")

if APPLY:
    db.commit()
    print(f"\nINGESTADOS: {done} emails, {total_att} adjuntos, {skipped} skip")
else:
    print(f"\nDRY: {len(T1)} candidatos, {skipped} se saltarían")
db.close()
