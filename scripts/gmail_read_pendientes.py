"""Lee (OCR) los adjuntos de los 3 conflados pendientes y vuelca el contenido clave
para decidir con Wilson: accionante, juzgado, municipio, radicado, qué dice el doc."""
import sys, base64, tempfile, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.email.gmail_monitor import _get_gmail_service, _extract_body_complete, _find_attachment_parts
from backend.v9 import doc_io

PEND = [
    ("2026-00062", "19e8962304edbe64", "c273 Leison Chia (68001 Bquilla) | c333 Personería Mogotes (68464)"),
    ("2026-00052", "19e89550231cb003", "c290 Jenny Tarazona (68001-13 Bquilla) | c448 Personería Vélez (68861)"),
    ("2026-00030", "19e88ba378877c8d", "7 cands: c155 Laura/c199 Oscar/c225 Pers.Betulia/c229 Blanca/c239 María/c399 Pers.Estanzuelas/c408 Wigberto"),
]
svc = _get_gmail_service()
for rc, gid, cands in PEND:
    msg = svc.users().messages().get(userId="me", id=gid, format="full").execute()
    h = {x["name"]: x["value"] for x in msg.get("payload", {}).get("headers", [])}
    body = _extract_body_complete(msg.get("payload", {}))
    parts = _find_attachment_parts(msg.get("payload", {}))
    print("=" * 75)
    print(f"### {rc}  | SUBJECT: {h.get('Subject','')[:65]}")
    print(f"    candidatos: {cands}")
    print(f"    BODY: {re.sub(chr(92)+'s+',' ',body)[:280]}")
    tmp = Path(tempfile.mkdtemp())
    for a in parts:
        att = svc.users().messages().attachments().get(userId="me", messageId=gid, id=a["attachmentId"]).execute()
        fp = tmp / a["filename"]; fp.write_bytes(base64.urlsafe_b64decode(att["data"]))
        try:
            t = doc_io.read_one(fp).text or ""
        except Exception as e:
            t = f"(error {e})"
        tc = re.sub(r"\s+", " ", t)
        print(f"\n  --- {a['filename']} (len {len(t)}) ---")
        # señales clave
        for label, rx in [("ACCIONANTE", r"ACCIONANTE\s*[:\-.]*\s*([A-ZÁÉÍÓÚÑ][\w\s]{5,45})"),
                          ("ACCIONADO", r"ACCIONAD[OA]S?\s*[:\-.]*\s*([A-ZÁÉÍÓÚÑ][\w\s]{5,45})"),
                          ("JUZGADO", r"(JUZGADO[\w\s]{5,55})"),
                          ("MUNICIPIO/lugar", r"(?:municipio|vereda|sede|Personería\s+(?:Municipal\s+)?de)\s+([A-ZÁÉÍÓÚÑ][\wáéíóúñ\s]{3,30})"),
                          ("RADICADO", r"[Rr]adica\w*\s*(?:No\.?|N°|:)?\s*([\d\-.\s]{12,30})")]:
            m = re.search(rx, tc)
            if m: print(f"     {label}: {m.group(1).strip()[:55]}")
        print(f"     HEAD: {tc[:350]}")
