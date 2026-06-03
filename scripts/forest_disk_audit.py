"""Audita los casos con FOREST vacío LEYENDO LOS ARCHIVOS EN DISCO (no la DB):
recorre cada folder, lee los .md (cuerpo de correos) y .doc/.docx (respuestas SED),
y busca el FOREST canónico (GESTA nuevo o continuo year-prefixed). Determina si el
vacío es LEGÍTIMO (no hay correo/respuesta de SED) o RECUPERABLE (el FOREST está en
disco pero no se capturó). NO escribe.
"""
import sys, re, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.database.database import SessionLocal
from backend.database.models import Case
from backend.v9.regex_pass import _extract_forest

db = SessionLocal()
vac = [c for c in db.query(Case).all() if not (c.radicado_forest or "").strip()]

os.environ["V9_OCR_SCANNED"] = "false"  # FOREST está en texto, no en imagen → sin OCR
from backend.v9 import doc_io


def read_text(fp: Path) -> str:
    suf = fp.suffix.lower()
    try:
        if suf in (".md", ".txt"):
            return fp.read_text(encoding="utf-8", errors="ignore")
        if suf in (".docx", ".doc", ".pdf"):
            return doc_io.read_one(fp).text or ""
    except Exception:
        return ""
    return ""

recuperables = []
legitimos = []
for c in vac:
    folder = Path(c.folder_path or "")
    if not folder.is_dir():
        legitimos.append((c.id, "NO-DIR", None, [])); continue
    files = sorted(folder.rglob("*"))
    found = None; src = None
    md_count = doc_count = 0
    # Prioridad: .md (correos) → .docx/.doc (respuestas) → .pdf
    order = sorted(files, key=lambda f: {".md": 0, ".docx": 1, ".doc": 1, ".pdf": 2}.get(f.suffix.lower(), 3))
    has_email = any(f.suffix.lower() == ".md" for f in files)
    has_resp = any(f.suffix.lower() in (".docx", ".doc") for f in files)
    for f in order:
        if f.suffix.lower() not in (".md", ".docx", ".doc", ".pdf"):
            continue
        t = read_text(f)
        if not t:
            continue
        fo = _extract_forest(t)
        if fo:
            found = fo; src = f.name; break
    if found:
        recuperables.append((c.id, found, src))
    else:
        # diagnóstico de por qué está vacío
        why = "sin correo SED (.md)" if not has_email else ("sin respuesta DOCX" if not has_resp else "tiene correo/resp pero sin FOREST")
        legitimos.append((c.id, why, None, [f.name for f in files if f.suffix.lower() in ('.md','.docx','.doc')][:4]))

print(f"=== RECUPERABLES (FOREST en disco no capturado): {len(recuperables)} ===")
for cid, fo, src in recuperables:
    print(f"  c{cid}: {fo}  (de {src})")
print(f"\n=== LEGÍTIMOS VACÍOS: {len(legitimos)} ===")
from collections import Counter
porque = Counter(x[1] for x in legitimos)
for k, v in porque.most_common():
    print(f"  {k}: {v}")
print("\n  detalle:")
for cid, why, _, files in legitimos:
    print(f"    c{cid}: {why} | archivos: {files}")
import json
json.dump({"recuperables": recuperables, "legitimos": [(c, w) for c, w, _, _ in legitimos]},
          open("data/forest_disk_audit.json", "w"), ensure_ascii=False, indent=1)
db.close()
