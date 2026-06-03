"""Resuelve cada conflado leyendo TODOS sus PDFs (OCR): extrae el rad23 completo +
accionante, y decide:
  - ASIGNAR a cX  si el rad23 coincide con un candidato (mismo rad corto).
  - NUEVO          si hay rad23 limpio pero NO coincide con ningún candidato.
  - UNRESOLVED     si no se obtiene rad23 limpio (requiere lectura humana).
NO escribe — solo propone (data/conflados_plan.json)."""
import sys, csv, re, base64, tempfile, json
from pathlib import Path
from collections import Counter
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
ACC_RE = re.compile(r"(?:ACCIONANTE|Accionante)\s*[:\-.]*\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{6,45}?)(?:\s+(?:en representación|identificad|mayor|C\.?C|cédula|VINCULAD|ACCIONAD|Derechos|Radicación))")
# rad23 colombiano: 5 díg juzgado + 4 (40xx) + 3 + año + 5 consec + 2 recurso = 23
RAD23 = re.compile(r"\b(\d{5}\d{4}\d{3}20\d{2}\d{5}\d{2})\b")

plan = {}
for r in rows:
    rc = r["rad_corto"]; gid = r["gid"]
    if "10021" in rc or "incidente" in rc:
        continue
    msg = svc.users().messages().get(userId="me", id=gid, format="full").execute()
    parts = _find_attachment_parts(msg.get("payload", {}))
    rad_counter = Counter(); accs = []
    tmp = Path(tempfile.mkdtemp())
    for a in parts:
        att = svc.users().messages().attachments().get(userId="me", messageId=gid, id=a["attachmentId"]).execute()
        fp = tmp / a["filename"]
        fp.write_bytes(base64.urlsafe_b64decode(att["data"]))
        try:
            t = doc_io.read_one(fp).text or ""
        except Exception:
            t = ""
        clean = re.sub(r"[-.\s\xa0]", "", t)
        for m in RAD23.findall(clean):
            rad_counter[m[:23]] += 1
        for m in ACC_RE.findall(t):
            accs.append(re.sub(r"\s+", " ", m).strip())
    cands = candidates(rc)
    # mejor rad23 = el más frecuente cuyo rad corto coincide con rc
    rc_seq = re.match(r"(20\d{2})[-]?0*(\d+)", rc)
    seq = rc_seq.group(2).zfill(5) if rc_seq else ""
    yr = rc_seq.group(1) if rc_seq else ""
    best_rad = None
    for rad, _ in rad_counter.most_common():
        if yr in rad and seq in rad:
            best_rad = rad; break
    if not best_rad and rad_counter:
        best_rad = rad_counter.most_common(1)[0][0]
    decision = "UNRESOLVED"; target = None
    if best_rad:
        for c in cands:
            if norm(c.radicado_23_digitos)[:20] == norm(best_rad)[:20] and len(norm(best_rad)) >= 18:
                decision = "ASIGNAR"; target = c.id; break
        if decision == "UNRESOLVED":
            decision = "NUEVO"
    # accionante por nombre si no hubo rad
    if decision == "UNRESOLVED":
        for c in cands:
            cacc = (c.accionante or "").upper()
            for a in accs:
                if cacc and a.upper() in cacc and len(a) > 8:
                    decision = "ASIGNAR"; target = c.id; break
            if target: break
    acc_top = Counter(a.upper() for a in accs).most_common(1)
    plan[gid] = {"rad_corto": rc, "n_att": r["n_att"], "best_rad23": best_rad,
                 "accionante": acc_top[0][0] if acc_top else None,
                 "decision": decision, "target_case_id": target,
                 "candidatos": [(c.id, (c.accionante or "")[:24]) for c in cands]}
    print(f"{rc:14} att={r['n_att']:<2} rad23={best_rad or '-':24} acc={(acc_top[0][0][:24] if acc_top else '-'):24} → {decision}{' c'+str(target) if target else ''}")
json.dump(plan, open("data/conflados_plan.json", "w"), ensure_ascii=False, indent=1)
db.close()
print("\nPlan → data/conflados_plan.json")
