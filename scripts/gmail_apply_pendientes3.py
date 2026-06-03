"""Resuelve los 3 conflados pendientes tras lectura del PDF:
  00062 → c333 (Mogotes 68464, juzgado+rad)
  00030 → c399 (San Joaquín 68682, rad23 exacto)
  00052 → NUEVO Dayana Palencia (Otanche BOYACÁ; SED Santander co-accionada → métricas)
Uso: [--apply]."""
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
db = SessionLocal(); svc = _get_gmail_service()
existing = {e.message_id for e in db.query(Email.message_id).all()}

def ingest(gid, case, route):
    msg = svc.users().messages().get(userId="me", id=gid, format="full").execute()
    h = {x["name"]: x["value"] for x in msg.get("payload", {}).get("headers", [])}
    mid = h.get("Message-ID", h.get("Message-Id", gid))
    subj = _normalize_typos(h.get("Subject", "")); sndr = h.get("From", ""); dstr = h.get("Date", "")
    try: dr = parsedate_to_datetime(dstr).astimezone(timezone.utc).replace(tzinfo=None)
    except Exception: dr = _utcnow()
    body = _extract_body_complete(msg.get("payload", {}))
    if mid in existing: print(f"   skip dup | {subj[:45]}"); return
    if not APPLY: print(f"   + c{case.id} ({route}) | {subj[:45]}"); return
    em = Email(message_id=mid, subject=subj, sender=sndr, date_received=dr, body_preview=body or "",
               case_id=case.id, attachments=[], status="ASIGNADO", processed_at=_utcnow(),
               match_confidence="VERIFIED_MANUAL", match_signals_json=json.dumps({"route": route}, ensure_ascii=False))
    db.add(em); db.flush()
    g, ign = download_attachments(svc, gid, case, db, email_id=em.id, email_message_id=mid)
    em.attachments = g
    if case.folder_path and body:
        save_email_md(Path(case.folder_path), {"subject": subj, "sender": sndr, "date": dstr, "folder_name": case.folder_name},
                      body, g, db=db, case_id=case.id, email_id=em.id, email_message_id=mid)
    db.add(AuditLog(case_id=case.id, action="IMPORT_EMAIL_CONFLADO", source="apply_pendientes3", new_value=f"{route}: {subj[:80]}"))
    existing.add(mid); db.commit()
    print(f"   → c{case.id} +{len(g)} adj ({route})")

def get(cid): return db.query(Case).filter(Case.id == cid).first()

print("=== 00062 → c333 ===");  ingest("19e8962304edbe64", get(333), "juzgado_mogotes_68464")
print("=== 00030 → c399 ===");  ingest("19e88ba378877c8d", get(399), "rad23_exacto_68682")
print("=== 00052 → NUEVO Dayana (Boyacá) ===")
if APPLY:
    folder = "2026-00052 DAYANA CATERINA PALENCIA SALINAS"
    fp = BASE_DIR / folder; fp.mkdir(parents=True, exist_ok=True)
    c = Case(folder_name=folder, folder_path=str(fp), accionante="DAYANA CATERINA PALENCIA SALINAS",
             radicado_23_digitos=None, processing_status="PENDIENTE", estado="ACTIVO", tipo_actuacion="TUTELA",
             observaciones="Juzgado Promiscuo de Otanche, BOYACÁ; accionados Gobernación de Boyacá Y Santander (SED Santander co-accionada). Conservado para métricas; verificar competencia.")
    db.add(c); db.flush()
    db.add(AuditLog(case_id=c.id, action="CREAR", source="apply_pendientes3", new_value="Dayana Palencia Otanche Boyacá (SED Santander co-accionada)"))
    db.commit(); print(f"   CREADO c{c.id} {folder}")
    ingest("19e89550231cb003", c, "nuevo_boyaca_metricas")
else:
    print("   (dry) CREAR 2026-00052 DAYANA CATERINA PALENCIA SALINAS")
db.close()
