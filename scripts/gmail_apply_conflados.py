"""Aplica las resoluciones de conflados + Norte de Santander (decisión Wilson:
capturar todo para métricas, no borrar). Uso: [--apply].

A) Ingesta a caso existente (señal fuerte):
   00038→c514 (accionante Gladys), 00079→c396 (Personería Aratoca),
   00027 (att6/att2/att22)→c218 (rad23 OCR + misma notificación incidente).
B) Crea casos NUEVOS + ingesta:
   00053→Personería Chipatá (sede Hatillo, distinto de c37),
   10021→Ronald Díaz Roa (Norte de Santander, flag competencia, para métricas).
C) c528: agrega nota de competencia (NO se borra).
Quedan flaggeados sin tocar: 00062, 00052, 00030 (OCR no dio rad23).
"""
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
db = SessionLocal()
svc = _get_gmail_service()
existing = {e.message_id for e in db.query(Email.message_id).all()}

def ingest(gid, case, route):
    msg = svc.users().messages().get(userId="me", id=gid, format="full").execute()
    h = {x["name"]: x["value"] for x in msg.get("payload", {}).get("headers", [])}
    mid = h.get("Message-ID", h.get("Message-Id", gid))
    subj = _normalize_typos(h.get("Subject", "")); sndr = h.get("From", ""); dstr = h.get("Date", "")
    try:
        dr = parsedate_to_datetime(dstr).astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        dr = _utcnow()
    body = _extract_body_complete(msg.get("payload", {}))
    if mid in existing:
        print(f"      skip dup | {subj[:45]}"); return 0
    if not APPLY:
        print(f"      + {route} c{case.id} | {subj[:45]}"); return 0
    em = Email(message_id=mid, subject=subj, sender=sndr, date_received=dr, body_preview=body or "",
               case_id=case.id, attachments=[], status="ASIGNADO", processed_at=_utcnow(),
               match_confidence="VERIFIED_MANUAL",
               match_signals_json=json.dumps({"route": route}, ensure_ascii=False))
    db.add(em); db.flush()
    g, ign = download_attachments(svc, gid, case, db, email_id=em.id, email_message_id=mid)
    em.attachments = g
    if case.folder_path and body:
        save_email_md(Path(case.folder_path), {"subject": subj, "sender": sndr, "date": dstr, "folder_name": case.folder_name},
                      body, g, db=db, case_id=case.id, email_id=em.id, email_message_id=mid)
    db.add(AuditLog(case_id=case.id, action="IMPORT_EMAIL_CONFLADO", source="gmail_apply_conflados", new_value=f"{route}: {subj[:80]}"))
    existing.add(mid)
    print(f"      → c{case.id} +{len(g)} adj ({route}) | {subj[:42]}")
    return len(g)

def get(cid): return db.query(Case).filter(Case.id == cid).first()

def create_case(folder_name, accionante, rad23, rad_corto, obs):
    folder = re.sub(r'[<>:"/\\|?*]', "", folder_name).strip()[:80]
    fp = BASE_DIR / folder
    if APPLY:
        fp.mkdir(parents=True, exist_ok=True)
        c = Case(folder_name=folder, folder_path=str(fp), accionante=accionante,
                 radicado_23_digitos=rad23 or None, processing_status="PENDIENTE",
                 estado="ACTIVO", tipo_actuacion="TUTELA", observaciones=obs)
        db.add(c); db.flush()
        db.add(AuditLog(case_id=c.id, action="CREAR", source="gmail_apply_conflados", new_value=obs[:90]))
        db.commit()
        print(f"  CREADO c{c.id} {folder}")
        return c
    print(f"  (dry) CREAR {folder} acc={accionante}")
    return None

# ── A) Ingesta a existentes ──
print("=== A) Ingesta a caso existente ===")
A = [("19e88bcfe8be6c04", 514, "accionante_gladys"),
     ("19e88c80e2c6a860", 396, "accionante_personeria_aratoca"),
     ("19e83704578a5406", 218, "rad23_ocr_68209"),
     ("19e83a5338c3f861", 218, "mismo_incidente_00027"),
     ("19e858fd0b17e0e0", 218, "mismo_incidente_00027")]
for gid, cid, route in A:
    c = get(cid)
    if c: ingest(gid, c, route)

# ── B) Crear nuevos ──
print("\n=== B) Casos nuevos ===")
c53 = create_case("2026-00053 PERSONERIA MUNICIPAL DE CHIPATA",
                  "PERSONERÍA MUNICIPAL DE CHIPATÁ", None, "2026-00053",
                  "Tutela Personería Chipatá (docente sede Hatillo); rad corto 2026-00053 comparte consecutivo con casos de otros juzgados.")
if c53: ingest("19e8967a19db73cb", c53, "nuevo_chipata")
c102 = create_case("2026-10021 RONALD DIAZ ROA NORTE SANTANDER",
                   "RONALD DÍAZ ROA", "54001410500220261002100", "2026-10021",
                   "NORTE DE SANTANDER (Cúcuta) — incidente desacato; SED Santander NO es la obligada (es SED Norte de Santander). Conservado para métricas; verificar competencia.")
if c102:
    for g in ("19cc4bc54baea12d", "19cc3b482625b9a9", "19cb553fed6a3ae2"):
        ingest(g, c102, "nuevo_nds_metricas")

# ── C) c528 nota ──
print("\n=== C) c528 nota competencia ===")
c528 = get(528)
if c528 and APPLY:
    nota = "Accionado real = UNIVERSIDAD INDUSTRIAL DE SANTANDER (UIS), Juzgado Ocaña Norte de Santander; SED Santander no es parte. Conservado para métricas; verificar competencia."
    c528.observaciones = (c528.observaciones or "") + " | " + nota
    db.add(AuditLog(case_id=528, action="NOTA_COMPETENCIA", source="gmail_apply_conflados", new_value=nota[:90]))
    db.commit()
    print("  c528 nota agregada")
elif c528:
    print("  (dry) agregar nota a c528")

if APPLY:
    db.commit()
    print("\n=== HECHO. Flaggeados sin tocar: 00062, 00052, 00030 ===")
else:
    print("\n=== DRY ===")
db.close()
