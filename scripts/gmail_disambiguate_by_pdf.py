"""Desambigua conflados LEYENDO el PDF adjunto: descarga a /tmp, extrae texto,
mina el rad23 completo (23 díg) y lo cruza con el rad23 de los casos candidatos.
Propone resolución. NO escribe en la DB ni en carpetas de casos."""
import sys, csv, re, base64, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.database.database import SessionLocal
from backend.database.models import Case
from backend.email.gmail_monitor import _get_gmail_service, _find_attachment_parts, _normalize_rad_num
from backend.v9 import doc_io

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

tmp = Path(tempfile.mkdtemp(prefix="disambig_"))
resolutions = {}
for r in rows:
    rc = r["rad_corto"]; gid = r["gid"]
    if "10021" in rc or "incidente" in rc:
        continue
    msg = svc.users().messages().get(userId="me", id=gid, format="full").execute()
    parts = _find_attachment_parts(msg.get("payload", {}))
    rads23 = set()
    for a in parts[:3]:  # primeros 3 adjuntos
        att_id = a.get("attachmentId")
        if not att_id:
            continue
        att = svc.users().messages().attachments().get(userId="me", messageId=gid, id=att_id).execute()
        data = base64.urlsafe_b64decode(att["data"])
        fp = tmp / a["filename"]
        fp.write_bytes(data)
        try:
            dt = doc_io.read_one(fp)
            blob = re.sub(r"[-\s]", "", (dt.text or "")[:6000])
            for x in re.findall(r"\b\d{20,23}\b", blob):
                rads23.add(x[:23])
        except Exception as e:
            print(f"   (no se pudo leer {a['filename']}: {e})")
    cands = candidates(rc)
    match = None
    for c in cands:
        cr = norm(c.radicado_23_digitos)
        for er in rads23:
            ern = norm(er)
            if len(cr) >= 18 and len(ern) >= 18 and cr[:20] == ern[:20]:
                match = c; break
        if match: break
    print(f"\n=== {rc} (att={r['n_att']}) gid={gid} ===")
    print(f"   rad23 en PDFs: {sorted(rads23) or '(ninguno)'}")
    for c in cands:
        fl = "  <<< MATCH" if match and c.id == match.id else ""
        print(f"      c{c.id}: {(c.accionante or '')[:26]:26} rad23={(c.radicado_23_digitos or '')[:23]}{fl}")
    print(f"   → {'c'+str(match.id) if match else 'SIN MATCH (rad del PDF no coincide con ningún candidato → posible caso NUEVO)'}")
    resolutions[gid] = {"rad_corto": rc, "match_case_id": match.id if match else None,
                        "rads23_pdf": sorted(rads23), "n_att": r["n_att"]}
import json
json.dump(resolutions, open("data/conflados_resolutions.json", "w"), ensure_ascii=False, indent=1)
db.close()
print(f"\nResoluciones → data/conflados_resolutions.json")
