"""Cruza los 36 casos FOREST-vacío (solo-notificación) con Gmail: busca una RESPUESTA
SED (de apoyojuridico/tutelas@santander) que traiga un FOREST canónico, y la verifica
contra el rad23/accionante del caso (anti-conflación). Reporta:
  - FOREST hallado en Gmail (+ si el correo ya está en DB o no).
  - sin respuesta SED en Gmail (vacío legítimo confirmado).
NO escribe. Salida: data/forest_gmail_crossref.json
"""
import sys, json, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.database.database import SessionLocal
from backend.database.models import Email
from backend.email.gmail_monitor import _get_gmail_service, _extract_body_complete
from backend.v9.regex_pass import _extract_forest

cases = json.load(open("data/forest_36_ids.json"))
db = SessionLocal()
svc = _get_gmail_service()
db_msgids = {e.message_id for e in db.query(Email.message_id).all()}

def norm(x): return re.sub(r"[^0-9]", "", x or "")

SED_SENDERS = ("apoyojuridico", "tutelas@santander", "educacion@santander", "secretaria de educacion")

out = []
for c in cases:
    cid = c["cid"]; rc = c["rad_corto"]; rad23 = norm(c["rad23"]); acc = c["acc"]
    # construir consulta: número de rad corto (sin ceros) + variantes
    m = re.match(r"(20\d{2})-0*(\d+)", rc)
    seq = m.group(2) if m else ""
    yr = m.group(1) if m else ""
    queries = []
    if seq:
        queries.append(f'"{yr}-{seq.zfill(5)}"')
        queries.append(f'"{yr}-{seq.zfill(4)}"')
        queries.append(f'"{yr}-{seq}"')
    # también por accionante (apellidos) si es persona
    if acc and "PERSONER" not in acc:
        toks = [w for w in acc.split() if len(w) > 3][:2]
        if toks:
            queries.append(" ".join(f'"{t}"' for t in toks) + " RESPUESTA")
    found = None
    for q in queries:
        try:
            resp = svc.users().messages().list(userId="me", q=q, maxResults=15).execute()
        except Exception:
            continue
        for mref in resp.get("messages", []):
            msg = svc.users().messages().get(userId="me", id=mref["id"], format="full").execute()
            hdrs = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            sender = (hdrs.get("From", "") or "").lower()
            subject = hdrs.get("Subject", "") or ""
            mid = hdrs.get("Message-ID", hdrs.get("Message-Id", mref["id"]))
            # ¿es de SED y luce respuesta?
            is_sed = any(s in sender for s in SED_SENDERS)
            is_resp = re.search(r"(?i)respuesta|contestaci[oó]n", subject)
            if not (is_sed and is_resp):
                continue
            body = _extract_body_complete(msg.get("payload", {}))
            forest = _extract_forest(body)
            if not forest:
                continue
            # ANTI-CONFLACIÓN: el cuerpo debe citar el rad23 o el rad corto + apellido
            body_digits = norm(body)
            rad_ok = (rad23 and len(rad23) >= 18 and rad23[:18] in body_digits) or \
                     (seq and f"{yr}-{seq.zfill(5)}".replace("-", "") in body_digits) or \
                     (seq and (yr + seq) in body_digits)
            # ANTI-CONFLACIÓN ESTRICTA: el match por NOMBRE solo NO basta (un correo de
            # OTRO caso puede mencionar al accionante de pasada → falso positivo, p.ej.
            # c248/c311). Se exige que el cuerpo cite el RADICADO del caso.
            if rad_ok:
                found = {"forest": forest, "subject": subject[:60], "msgid": mid,
                         "in_db": mid in db_msgids, "via": "rad23",
                         "gid": mref["id"]}
                break
        if found:
            break
    out.append({"cid": cid, "rad_corto": rc, "acc": acc, **(found or {"forest": None})})
    tag = f"FOREST={found['forest']} ({found['via']}, {'ya en DB' if found['in_db'] else 'NO ingestado'})" if found else "sin respuesta SED en Gmail"
    print(f"  c{cid:<4} {rc:12} {acc[:24]:24} → {tag}", flush=True)

json.dump(out, open("data/forest_gmail_crossref.json", "w"), ensure_ascii=False, indent=1)
hall = [o for o in out if o.get("forest")]
print(f"\n=== {len(hall)}/{len(out)} con FOREST hallado en Gmail ({sum(1 for o in hall if not o['in_db'])} de correos NO ingestados) ===")
db.close()
