"""Scan global read-only: Message-ID de Gmail INBOX vs BD. Halla correos no ingestados."""
import sys, re, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sqlite3
from backend.email.gmail_monitor import _get_gmail_service

svc = _get_gmail_service()
con = sqlite3.connect("data/tutelas.db"); con.row_factory = sqlite3.Row; cur = con.cursor()
dbids = set(r[0] for r in cur.execute("SELECT message_id FROM emails WHERE message_id IS NOT NULL"))
dbids |= set(r[0] for r in cur.execute("SELECT email_message_id FROM documents WHERE email_message_id IS NOT NULL"))

# paginar INBOX
ids = []
tok = None
while True:
    kw = {"userId": "me", "labelIds": ["INBOX"], "maxResults": 200}
    if tok: kw["pageToken"] = tok
    r = svc.users().messages().list(**kw).execute()
    ids += [m["id"] for m in r.get("messages", [])]
    tok = r.get("nextPageToken")
    if not tok: break
print(f"Gmail INBOX msgs: {len(ids)} | DB message_ids: {len(dbids)}", flush=True)

no_ing = []
for i, mid in enumerate(ids):
    if i % 200 == 0: print(f"  {i}/{len(ids)}", flush=True)
    mm = svc.users().messages().get(userId="me", id=mid, format="metadata",
                                    metadataHeaders=["Message-ID", "Subject", "From"]).execute()
    h = {x["name"]: x["value"] for x in mm["payload"]["headers"]}
    rfcid = h.get("Message-ID", h.get("Message-Id", mid))
    labels = mm.get("labelIds", [])
    if rfcid not in dbids:
        no_ing.append({"rfcid": rfcid, "subject": h.get("Subject", "")[:80],
                       "from": h.get("From", "")[:40], "unread": "UNREAD" in labels})
json.dump(no_ing, open("data/gmail_no_ingestados.json", "w"), ensure_ascii=False)
# clasificar
def cls(s):
    s = s.lower()
    if "respuesta" in s or "contestaci" in s or "forest" in s or " rta" in s: return "RESPUESTA?"
    if "notifica" in s or "fallo" in s or "sentencia" in s or "auto" in s: return "NOTIFICACION"
    if "impugna" in s: return "IMPUGNACION"
    if "incidente" in s or "desacato" in s or "requerimiento" in s: return "INCIDENTE/REQ"
    return "OTRO"
from collections import Counter
c = Counter(cls(x["subject"]) for x in no_ing)
unread = sum(1 for x in no_ing if x["unread"])
print(f"\nNO INGESTADOS: {len(no_ing)} (unread={unread}, procesados-leidos={len(no_ing)-unread})")
print("por tipo:", dict(c))
print("--- muestra RESPUESTA? no ingestadas ---")
for x in no_ing:
    if cls(x["subject"]) == "RESPUESTA?": print(f"   [{'UNREAD' if x['unread'] else 'leido'}] {x['from']:32} | {x['subject']}")
con.close()
