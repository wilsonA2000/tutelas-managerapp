"""Crea 00043 y 00182 (tutelas nuevas cuyo rad corto colisiona con caso de OTRO
juzgado → create_new_case devolvería el equivocado, igual que Marcelino). Se crean
manualmente con su rad23 verificado. accionante vacío → la extracción lo llenará del
EscritoTutela. Uso: [--apply]."""
import sys, json, re
from pathlib import Path
from datetime import timezone
from email.utils import parsedate_to_datetime
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.database.database import SessionLocal
from backend.database.models import Case, Email, AuditLog
from backend.email.gmail_monitor import (
    _get_gmail_service, _extract_body_complete, download_attachments,
    save_email_md, _normalize_typos, _utcnow, BASE_DIR,
)

APPLY = "--apply" in sys.argv
# (gid, rad23, rad_corto, folder_accionante, juzgado_nota)
NEW = [
    ("19e84e6d1a40cd2f", "68773408900120260004300", "2026-00043", "PENDIENTE REVISION", "juzgado 68773"),
    ("19e84d34b3be60ad", "68615408900120260018200", "2026-00182", "CONSEJO PADRES IE FALTRIQUERA PLAYON", "El Playón 68615"),
]
db = SessionLocal()
service = _get_gmail_service()
existing_ids = {e.message_id for e in db.query(Email.message_id).all()}

for gid, rad23, rc, accfolder, nota in NEW:
    rad23n = re.sub(r"\D", "", rad23)
    folder = re.sub(r'[<>:"/\\|?*]', "", f"{rc} {accfolder}").strip()[:80]
    print(f"=== {rc} rad23={rad23n} ({nota}) → folder '{folder}' ===")
    if not APPLY:
        print("   (dry)"); continue
    fp = BASE_DIR / folder
    fp.mkdir(parents=True, exist_ok=True)
    case = Case(folder_name=folder, folder_path=str(fp),
                accionante=None if "PENDIENTE" in accfolder else accfolder,
                radicado_23_digitos=rad23n, processing_status="PENDIENTE",
                estado="ACTIVO", tipo_actuacion="TUTELA",
                observaciones=f"Creado de correo no ingestado; rad corto {rc} colisiona con caso de otro juzgado ({nota}).")
    db.add(case); db.flush()
    db.add(AuditLog(case_id=case.id, action="CREAR", source="gmail_create_raros2", new_value=f"Caso nuevo {rc} ({nota})"))
    db.commit()
    # Ingestar el email
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
        print(f"   email dup, skip"); continue
    em = Email(message_id=mid, subject=subj, sender=sndr, date_received=dr, body_preview=body or "",
               case_id=case.id, attachments=[], status="ASIGNADO", processed_at=_utcnow(),
               match_confidence="VERIFIED_NEW", match_signals_json=json.dumps({"route": "create_raros2"}, ensure_ascii=False))
    db.add(em); db.flush()
    guardados, ign = download_attachments(service, gid, case, db, email_id=em.id, email_message_id=mid)
    em.attachments = guardados
    if body:
        save_email_md(Path(case.folder_path), {"subject": subj, "sender": sndr, "date": dstr, "folder_name": folder},
                      body, guardados, db=db, case_id=case.id, email_id=em.id, email_message_id=mid)
    db.add(AuditLog(case_id=case.id, action="IMPORT_EMAIL_NEW", source="gmail_create_raros2", new_value=f"Email: {subj[:90]}"))
    db.commit()
    print(f"   CREADO c{case.id} + {len(guardados)} adjuntos ({len(ign)} dedup)")
db.close()
