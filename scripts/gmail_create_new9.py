"""Crea los 9 casos NUEVOS de TIER 3 + ingesta sus correos. Cada uno verificado como
SIN caso preexistente (excepto Marcelino, cuyo rad corto 2026-00083 colisiona con
c17/c264 de OTROS juzgados → se crea manualmente con su rad23 de Bucaramanga, sin pasar
por create_new_case que devolvería el caso equivocado).

Uso: gmail_create_new9.py [--apply]   (default dry-run)
"""
import sys, json, re
from pathlib import Path
from datetime import timezone, timedelta
from email.utils import parsedate_to_datetime
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.database.database import SessionLocal
from backend.database.models import Case, Email, AuditLog
from backend.email import gmail_monitor as gm
from backend.email.gmail_monitor import (
    _get_gmail_service, _extract_body_complete, download_attachments,
    save_email_md, _normalize_typos, _utcnow, create_new_case, BASE_DIR,
)

APPLY = "--apply" in sys.argv
def norm(rc):
    m = re.match(r"(20\d{2})[-]?0*(\d+)", rc or ""); return f"{m.group(1)}:{m.group(2)}" if m else ""

NEW = {"2026:127", "2026:357", "2026:128", "2026:99", "2026:125", "2025:279", "2025:207", "2025:755"}
prop = json.load(open("data/gmail_ingest_proposal.json"))
tiers = json.load(open("data/gmail_ingest_tiers.json"))

# Agrupar por case-key
groups = {}  # key -> list of entries
for o in prop:
    k = norm(o.get("rad_corto"))
    if k in NEW:
        groups.setdefault(k, []).append(o)
for o in tiers["t2"]:  # Marcelino
    groups.setdefault("MARCELINO", []).append(o)

db = SessionLocal()
service = _get_gmail_service()
existing_ids = {e.message_id for e in db.query(Email.message_id).all()}

def best(entries):
    """Elige la entrada con rad23 más largo y accionante no vacío para semilla del caso."""
    rad = max((e.get("rad23") or "" for e in entries), key=lambda r: len(re.sub(r"\D", "", r)))
    acc = next((e.get("accionante") for e in entries if (e.get("accionante") or "").strip()), "")
    rc = next((e.get("rad_corto") for e in entries if e.get("rad_corto")), "")
    return rad, acc, rc

def ingest_email(o, case):
    gid = o["gid"]
    msg = service.users().messages().get(userId="me", id=gid, format="full").execute()
    h = {x["name"]: x["value"] for x in msg.get("payload", {}).get("headers", [])}
    mid = h.get("Message-ID", h.get("Message-Id", gid))
    subj = _normalize_typos(h.get("Subject", "")); sndr = h.get("From", ""); dstr = h.get("Date", "")
    try:
        dr = parsedate_to_datetime(dstr).astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        dr = _utcnow()
    body = _extract_body_complete(msg.get("payload", {}))
    if mid in existing_ids:
        print(f"      skip email dup (message_id) | {subj[:40]}"); return 0
    if not APPLY:
        print(f"      + email | {subj[:48]}"); return 0
    em = Email(message_id=mid, subject=subj, sender=sndr, date_received=dr, body_preview=body or "",
               case_id=case.id, attachments=[], status="ASIGNADO", processed_at=_utcnow(),
               in_reply_to=h.get("In-Reply-To") or None, references_header=h.get("References") or None,
               match_confidence="VERIFIED_NEW",
               match_signals_json=json.dumps({"route": "create_new_tier3"}, ensure_ascii=False))
    db.add(em); db.flush()
    guardados, ign = download_attachments(service, gid, case, db, email_id=em.id, email_message_id=mid)
    em.attachments = guardados
    if case.folder_path and body:
        save_email_md(Path(case.folder_path),
                      {"subject": subj, "sender": sndr, "date": dstr, "folder_name": case.folder_name},
                      body, guardados, db=db, case_id=case.id, email_id=em.id, email_message_id=mid)
    db.add(AuditLog(case_id=case.id, action="IMPORT_EMAIL_NEW", source="gmail_create_new9",
                    new_value=f"Email: {subj[:90]}"))
    existing_ids.add(mid)
    print(f"      → {len(guardados)} adjuntos ({len(ign)} dedup) | {subj[:40]}")
    return len(guardados)

created = 0; total_att = 0
for key, entries in groups.items():
    rad23, acc, rc = best(entries)
    rad23n = re.sub(r"\D", "", rad23)
    print(f"\n=== {key}: rc={rc} rad23={rad23 or '-'} acc={acc or '(vacío)'} ({len(entries)} email) ===")
    if not APPLY:
        for o in entries: ingest_email(o, None)
        continue
    if key == "MARCELINO":
        folder = f"2026-00083 MARCELINO MORENO GUARIN"
        fp = BASE_DIR / folder
        fp.mkdir(parents=True, exist_ok=True)
        case = Case(folder_name=folder, folder_path=str(fp), accionante="MARCELINO MORENO GUARÍN",
                    radicado_23_digitos=rad23n, processing_status="PENDIENTE", estado="ACTIVO",
                    tipo_actuacion="TUTELA")
        db.add(case); db.flush()
        db.add(AuditLog(case_id=case.id, action="CREAR", source="gmail_create_new9",
                        new_value="Caso nuevo Marcelino (rad corto 2026-00083 colisiona c17/c264, juzgado Bucaramanga)"))
        db.commit()
        print(f"  CREADO c{case.id} {folder}")
    else:
        rd = {"radicado_corto": rc, "radicado_23": rad23n if len(rad23n) >= 18 else ""}
        case = create_new_case(db, rd, acc or "")
        if not case:
            print(f"  ⚠️ no se pudo crear (sin rad_corto)"); continue
        print(f"  CREADO/EXISTENTE c{case.id} {case.folder_name}")
    created += 1
    for o in entries:
        total_att += ingest_email(o, case)

if APPLY:
    db.commit()
    print(f"\nCREADOS: {created} casos, {total_att} adjuntos ingestados")
else:
    print(f"\nDRY: {len(groups)} casos a crear")
db.close()
