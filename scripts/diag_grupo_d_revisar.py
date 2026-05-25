"""Pasada profunda SOLO LECTURA para el bucket REVISAR del grupo D.
Para cada caso: lista docs de fallo, intenta dispositiva con last_pages=12,
recap del 1ra en doc completo, y marca si hay archivos de fallo en el folder
del caso que NO estén registrados como documents (fallo en disco sin ingestar).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database.database import SessionLocal
from backend.database.models import Case, Document
from backend.v9 import field_extractor as fe
from backend.extraction.pdf_extractor import extract_pdf

REVISAR = [13, 70, 82, 96, 107, 147, 152, 160, 182, 186, 203, 229, 230, 239, 245, 250, 417, 421]
FALLO_FN = re.compile(r"(?i)fallo|sentencia|resuelve|cumplimiento|tutela.*\d")
SENT_TYPES = ("SENTENCIA_1RA", "SENTENCIA_2DA", "PDF_SENTENCIA", "NOTIFICACION_FALLO",
              "OFICIO_CUMPLIMIENTO", "DESCONOCIDO", "AUTO_CONCEDE_IMPUGNACION", "IMPUGNACION")


def deep_dispositiva(fp):
    if not fp or not os.path.exists(fp) or not fp.lower().endswith(".pdf"):
        return None, None, "n/a"
    r = extract_pdf(fp, first_pages=0, last_pages=12)
    t = r.text or ""
    if len(t.strip()) < 50:
        return None, None, "SCANNED"
    z = fe._last_resuelve_zone(t)
    if not z:
        m = list(fe._RE_PRIMERO_DECISION.finditer(t))
        if m:
            z = t[m[-1].start():m[-1].start() + 2500]
    return (z[:260] if z else None), (fe._classify_sentido_fallo(z) if z else None), "ok"


def main():
    db = SessionLocal()
    for cid in REVISAR:
        c = db.get(Case, cid)
        print(f"\n{'='*70}\nc{cid} DB_1st={c.sentido_fallo_1st} DB_2nd={c.sentido_fallo_2nd} acc={c.accionante}")
        docs = db.query(Document).filter(Document.case_id == cid).all()
        sent = [d for d in docs if (d.doc_type or "") in SENT_TYPES]
        for d in sent:
            z, tag, st = deep_dispositiva(d.file_path)
            full = ""
            if d.file_path and os.path.exists(d.file_path) and d.file_path.lower().endswith(".pdf"):
                full = extract_pdf(d.file_path, first_pages=10, last_pages=10).text or ""
            recap = fe._classify_recap_1ra(full) if full else None
            print(f"  #{d.id} [{d.doc_type}] {d.filename[:46]} | disp12={tag}({st}) recap={recap}")
            if z:
                print(f"      zona: {z.strip()[:150]}")
        # archivos de fallo en disco NO registrados
        if c.folder_path and os.path.isdir(c.folder_path):
            registrados = {os.path.basename(d.file_path or "") for d in docs}
            for root, _, files in os.walk(c.folder_path):
                for fn in files:
                    if fn not in registrados and FALLO_FN.search(fn) and fn.lower().endswith((".pdf", ".docx", ".doc")):
                        print(f"  [!] EN DISCO SIN INGESTAR: {os.path.join(root, fn).replace(c.folder_path,'')}")
    db.close()


if __name__ == "__main__":
    main()
