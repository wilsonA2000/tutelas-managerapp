"""Lee COMPLETAMENTE los docs de respuesta SED de los casos sin abogado_responsable
(pero CON respuesta), extrae el REDACTOR del footer ("Proyectó/Elaboró"), lo resuelve
contra el roster de 17 canónicos, y MUESTRA la línea exacta como evidencia. NO escribe.
"""
import sys, os, re, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["V9_OCR_SCANNED"] = "false"
from backend.database.database import SessionLocal
from backend.database.models import Case, Document
from backend.v9.regex_pass import _extract_abogado_footer
from backend.v9 import doc_io

# Roster canónico
roster = json.load(open("backend/data/abogados_canonicos.json"))
def resolve(name):
    if not name: return None
    up = name.upper().strip()
    for r in roster:
        if up == r["canonical"].upper() or up in [a.upper() for a in r["aliases"]] or r["canonical"].upper() in up:
            return r["canonical"]
        # match por apellido+nombre parcial
        cn = r["canonical"].upper().split()
        if len(cn) >= 2 and cn[0] in up and cn[-1] in up:
            return r["canonical"]
    return None

cats = json.load(open("data/abog_categorias.json"))
ids = cats["con_resp"]
db = SessionLocal()
RESP = {"RESPUESTA", "DOCX_RESPUESTA", "RESPUESTA_SED"}

def gather_texts(c):
    """Lee de DISCO todos los docs de respuesta: TODOS los .docx/.doc (las contestaciones
    SED suelen nombrarse solo por el número FOREST, p.ej. "3405561.docx", sin keyword)
    + .md/.pdf de respuesta. Disco-primero (la fuente de verdad)."""
    out = []
    p = Path(c.folder_path or "")
    if not p.is_dir():
        return out
    for f in sorted(p.rglob("*")):
        if not f.is_file():
            continue
        n = f.name.upper()
        is_docx = f.suffix.lower() in (".docx", ".doc")
        is_resp_md = f.suffix.lower() == ".md" and ("RESPUESTA" in n or "CONTESTACION" in n)
        is_resp_pdf = f.suffix.lower() == ".pdf" and ("RESPUESTA" in n or "CONTESTACION" in n or "RTA" in n)
        if not (is_docx or is_resp_md or is_resp_pdf):
            continue
        try:
            t = f.read_text(encoding="utf-8", errors="ignore") if f.suffix.lower() == ".md" else (doc_io.read_one(f).text or "")
        except Exception:
            t = ""
        if t.strip():
            out.append((f.name, t))
    return out

print(f"=== {len(ids)} casos CON respuesta SED ===\n")
plan = {}
for cid in ids:
    c = db.query(Case).filter(Case.id == cid).first()
    texts = gather_texts(c)
    redactor = None; ev = None; src = None
    for fn, t in texts:
        r = _extract_abogado_footer(t)
        if r:
            redactor = r; src = fn
            m = re.search(r"(?i)(proyect[oó]|elabor[oó]|redact[oó])[\s:.\-]*" + re.escape(r.split()[0][:6]), t)
            if not m:
                m = re.search(r"(?i)(proyect[oó]|elabor[oó])[^\n]{0,60}", t)
            ev = re.sub(r"\s+", " ", m.group(0))[:80] if m else "(footer)"
            break
    canon = resolve(redactor)
    plan[cid] = {"redactor": redactor, "canonical": canon, "src": src}
    if canon:
        verdict = f"→ {canon}"
    elif redactor:
        verdict = f"REDACTOR='{redactor}' NO está en roster (¿externo CPS? → vacío)"
    else:
        verdict = "sin 'Proyectó/Elaboró' legible en la respuesta"
    print(f"c{cid:<4} [{src or '-'}][:26]")
    print(f"      evidencia: {ev or '-'}")
    print(f"      {verdict}\n")
json.dump(plan, open("data/abog_plan.json", "w"), ensure_ascii=False, indent=1)
hall = [k for k, v in plan.items() if v["canonical"]]
print(f"=== {len(hall)}/{len(ids)} resueltos a un abogado del roster ===")
db.close()
