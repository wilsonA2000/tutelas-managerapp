"""Para cada caso del grupo D, reúne la EVIDENCIA DE DISCO del fallo (solo lectura)
y propone una acción de reconciliación contra el valor de la DB.

Por caso evalúa, leyendo el archivo en disco (no la DB):
  - disk_1ra: dispositiva de un doc que parece 1ra (filename NO dice 2da) → tag.
  - disk_2da: dispositiva de un doc que parece 2da → tag (su sentido es el 2nd).
  - recap_1ra: recap del fallo de 1ra dentro de un doc de 2da.
  - scanned: algún doc sentencia con archivo presente pero sin capa de texto (→ OCR).

Acción propuesta (heurística, para revisar con Wilson; NO aplica nada):
  CONFIRMA        db == disk_1ra (groundear).
  CORRIGE         db != disk_1ra y hay disk_1ra claro.
  RECLASIFICAR    el/los doc son 2da mal etiquetados; 1ra viene de recap.
  OCR             archivo presente sin texto → necesita OCR para decidir.
  REVISAR         sin evidencia clara de disco.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database.database import SessionLocal
from backend.database.models import Case, Document
from backend.v9 import field_extractor as fe
from backend.extraction.pdf_extractor import extract_pdf

# Señales de 2da en filename (superset de _RE_2DA_FILENAME — para diagnóstico).
_FN_2DA = re.compile(r"(?i)2da|2a\b|2[ªa]\s*inst|segunda\s*inst|fallo\s*2|tutela\s*2a|"
                     r"confirma|revoca|modifica|segundainstancia|tribunal")
_FN_1RA = re.compile(r"(?i)primera\s*inst|1era?\s*inst|1ra\s*inst|primerainstancia")


def disk_zone_tag(d, ocr=False):
    fp = getattr(d, "file_path", None)
    if not fp or not os.path.exists(fp):
        return None, None, "FILE_MISSING"
    if not str(fp).lower().endswith(".pdf"):
        z = fe._last_resuelve_zone(d.extracted_text or "")
        return (z, fe._classify_sentido_fallo(z) if z else None, "nonpdf")
    try:
        r = extract_pdf(fp, first_pages=0, last_pages=5, ocr_scanned=ocr)
        tail = r.text or ""
        if len(tail.strip()) < 50:
            return None, None, "SCANNED"  # sin capa de texto en la cola
        z = fe._last_resuelve_zone(tail)
        if not z:
            m = list(fe._RE_PRIMERO_DECISION.finditer(tail))
            if m:
                z = tail[m[-1].start():m[-1].start() + 2500]
        return (z, fe._classify_sentido_fallo(z) if z else None, "ok")
    except Exception as e:
        return None, None, f"ERR:{e}"


def main():
    db = SessionLocal()
    data = json.load(open("data/diag_grupo_d.json"))
    rows = []
    for r in data:
        c = db.get(Case, r["case_id"])
        docs = db.query(Document).filter(Document.case_id == c.id).all()
        disk_1ra = disk_2da = recap = None
        scanned = False
        d1ra_fn = d2da_fn = None
        for d in docs:
            dt = d.doc_type or ""
            fn = d.filename or ""
            if dt not in ("SENTENCIA_1RA", "SENTENCIA_2DA", "PDF_SENTENCIA",
                          "DESCONOCIDO", "NOTIFICACION_FALLO", "AUTO_2DA",
                          "AUTO_CONCEDE_IMPUGNACION", "IMPUGNACION"):
                continue
            is2da_fn = bool(_FN_2DA.search(fn)) or dt in ("SENTENCIA_2DA", "AUTO_2DA")
            is1ra_fn = bool(_FN_1RA.search(fn))
            z, tag, st = disk_zone_tag(d)
            if st == "SCANNED":
                scanned = True
            if (is2da_fn and not is1ra_fn):
                if tag and not disk_2da:
                    disk_2da, d2da_fn = tag, fn
                # recap del 1ra dentro del 2da
                if z:
                    rc = fe._classify_recap_1ra(extract_pdf(d.file_path, first_pages=5, last_pages=5).text or "") if os.path.exists(d.file_path or "") else None
                    if rc and not recap:
                        recap = rc
            else:
                if tag and not disk_1ra:
                    disk_1ra, d1ra_fn = tag, fn

        dbv = r["db_sentido"]
        if disk_1ra:
            action = "CONFIRMA" if disk_1ra == dbv else "CORRIGE"
        elif disk_2da and not disk_1ra:
            action = "RECLASIFICAR"
        elif scanned:
            action = "OCR"
        else:
            action = "REVISAR"
        rows.append({
            "case_id": c.id, "db": dbv, "disk_1ra": disk_1ra, "d1ra_fn": d1ra_fn,
            "disk_2da": disk_2da, "d2da_fn": d2da_fn, "recap_1ra": recap,
            "scanned": scanned, "action": action,
            "subcausa": r["subcausa"],
        })

    from collections import Counter
    print("=== ACCIONES PROPUESTAS ===")
    for k, v in Counter(x["action"] for x in rows).most_common():
        print(f"  {k}: {v}")
    print()
    for a in ("CONFIRMA", "CORRIGE", "RECLASIFICAR", "OCR", "REVISAR"):
        sub = [x for x in rows if x["action"] == a]
        if not sub:
            continue
        print(f"\n----- {a} ({len(sub)}) -----")
        for x in sub:
            extra = ""
            if x["disk_2da"]:
                extra += f" 2da={x['disk_2da']}({(x['d2da_fn'] or '')[:30]})"
            if x["recap_1ra"]:
                extra += f" recap1ra={x['recap_1ra']}"
            if x["scanned"]:
                extra += " [SCANNED]"
            d1 = f"{x['disk_1ra']}({(x['d1ra_fn'] or '')[:34]})" if x["disk_1ra"] else "-"
            print(f"  c{x['case_id']:<4} DB={x['db']:<15} disk_1ra={d1}{extra}")

    json.dump(rows, open("data/diag_grupo_d_grounding.json", "w"), ensure_ascii=False, indent=2)
    print(f"\n-> data/diag_grupo_d_grounding.json")
    db.close()


if __name__ == "__main__":
    main()
