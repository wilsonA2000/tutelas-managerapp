"""Desambigua los correos conflados: extrae rad23 completo + accionante de cada uno y
lo cruza contra el rad23 de los casos candidatos (mismo rad corto). Propone resolución
SOLO cuando hay match fuerte (rad23 idéntico o accionante idéntico). NO escribe."""
import sys, csv, re, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.database.database import SessionLocal
from backend.database.models import Case
from backend.email.gmail_monitor import (
    _get_gmail_service, _extract_body_complete, _find_attachment_parts, _normalize_rad_num,
)

db = SessionLocal()
svc = _get_gmail_service()
rows = list(csv.DictReader(open("data/gmail_flag_conflados.csv")))

def norm(x): return re.sub(r"[^0-9]", "", x or "")

def candidates(rc):
    m = re.match(r"(20\d{2})[-]?0*(\d+)", rc or "")
    if not m: return []
    tg = f"{m.group(1)}:{m.group(2)}"
    return [c for c in db.query(Case).filter(Case.folder_name.ilike(f"{m.group(1)}%")).all()
            if _normalize_rad_num(c.folder_name) == tg]

ACC_RE = re.compile(r"(?:ACCIONANTE|Señor[ae]?\s+accionante|Accionante)\s*[:\-.]*\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{6,45})")

for r in rows:
    rc = r["rad_corto"]; gid = r["gid"]
    if "10021" in rc or "incidente" in rc:
        continue  # Norte de Santander aparte
    msg = svc.users().messages().get(userId="me", id=gid, format="full").execute()
    body = _extract_body_complete(msg.get("payload", {}))
    atts = " ".join(a["filename"] for a in _find_attachment_parts(msg.get("payload", {})))
    blob = re.sub(r"[-\s]", "", body + " " + atts)
    rads23 = set(re.findall(r"\b\d{20,23}\b", blob))
    rads23 = {x[:23] for x in rads23 if len(x) >= 20}
    accs = [re.sub(r"\s+", " ", a).strip() for a in ACC_RE.findall(body)]
    cands = candidates(rc)
    print(f"\n=== {rc} (att={r['n_att']}) ===")
    print(f"   rad23 en correo: {sorted(rads23) or '(ninguno)'}")
    print(f"   accionante(s) en correo: {accs[:3] or '(ninguno)'}")
    match = None; how = None
    for c in cands:
        cr = norm(c.radicado_23_digitos)
        for er in rads23:
            ern = norm(er)
            if len(cr) >= 18 and len(ern) >= 18 and cr[:20] == ern[:20]:
                match = c; how = f"rad23 idéntico ({ern[:20]})"; break
        if match: break
    if not match:
        for c in cands:
            cacc = (c.accionante or "").upper()
            for a in accs:
                if cacc and (a.upper() in cacc or cacc in a.upper()) and len(a) > 6:
                    match = c; how = f"accionante '{a}'≈c{c.id}"; break
            if match: break
    for c in cands:
        flag = "  <<< MATCH" if match and c.id == match.id else ""
        print(f"      c{c.id}: {(c.accionante or '')[:28]:28} rad23={(c.radicado_23_digitos or '')[:23]}{flag}")
    print(f"   → RESOLUCIÓN: {'c'+str(match.id)+' ('+how+')' if match else 'SIN MATCH FUERTE — requiere lectura humana'}")
db.close()
