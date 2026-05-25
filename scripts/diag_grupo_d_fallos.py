"""Diagnóstico SOLO LECTURA del grupo D (gap de fallos reales).

Grupo D = casos con `sentido_fallo_1st` en DB + hay doc de sentencia/fallo +
el extractor `extract_sentido_fallo_1ra_for_case` devuelve None.

Para cada gap clasifica la SUBCAUSA contra el DISCO (no la DB):
  - GATE_EMPTY_TEXT: el doc SENTENCIA_1RA tiene extracted_text vacío/<=500 →
    el gate (field_extractor.py:2329) lo descarta antes de leer disco.
  - DISK_HAS_DISPOSITIVA: re-leyendo últimas 5 pág del PDF SÍ hay zona dispositiva
    clasificable → el fix es backfill de texto + re-extraer.
  - DISK_NO_DISPOSITIVA: el disco tampoco da dispositiva (escaneado imagen-pura,
    doc mal clasificado, o fallo no está en este case) → necesita OCR o revisión.
  - NO_SENTENCIA_DOC: no hay archivo de sentencia ingestado en el case.

NO escribe nada.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database.database import SessionLocal
from backend.database.models import Case, Document
from backend.v9 import field_extractor as fe

SENTENCIA_TYPES = {"SENTENCIA_1RA", "SENTENCIA_2DA", "PDF_SENTENCIA",
                   "NOTIFICACION_FALLO", "OFICIO_CUMPLIMIENTO"}


def disk_dispositiva(d):
    """Re-lee el final del PDF en disco y devuelve (zona?, tag?)."""
    fp = getattr(d, "file_path", None)
    if not fp or not str(fp).lower().endswith(".pdf"):
        return None, None
    if not os.path.exists(fp):
        return None, "FILE_MISSING"
    try:
        from backend.extraction.pdf_extractor import extract_pdf
        tail = extract_pdf(fp, first_pages=0, last_pages=5).text or ""
        z = fe._last_resuelve_zone(tail)
        if not z:
            import re
            m = list(fe._RE_PRIMERO_DECISION.finditer(tail))
            if m:
                z = tail[m[-1].start():m[-1].start() + 2500]
        tag = fe._classify_sentido_fallo(z) if z else None
        return (z[:200] if z else None), tag
    except Exception as e:
        return None, f"ERR:{e}"


def main():
    db = SessionLocal()
    out = []
    cases = db.query(Case).filter(
        Case.sentido_fallo_1st.isnot(None), Case.sentido_fallo_1st != ""
    ).all()
    print(f"Casos con sentido_fallo_1st en DB: {len(cases)}")
    gaps = []
    for c in cases:
        val, src = fe.extract_sentido_fallo_1ra_for_case(db, c)
        if val is not None:
            continue  # extractor coincide o da algo -> no es gap
        gaps.append(c)
    print(f"GAP (extractor=None pese a tener valor DB): {len(gaps)}\n")

    for c in gaps:
        docs = db.query(Document).filter(Document.case_id == c.id).all()
        sent_docs = [d for d in docs if (d.doc_type or "") in SENTENCIA_TYPES]
        rec = {
            "case_id": c.id,
            "rad": c.radicado_23_digitos or c.radicado_forest,
            "db_sentido": c.sentido_fallo_1st,
            "n_docs": len(docs),
            "subcausa": None,
            "sent_docs": [],
        }
        if not sent_docs:
            rec["subcausa"] = "NO_SENTENCIA_DOC"
            out.append(rec)
            continue
        # ¿Llegaría algún tag de disco a través de la ruta del extractor (paso 1 = solo
        # SENTENCIA_1RA, no descartado como 2da)?  Eso separa: filtro 2da, doc no-1RA, miss real.
        usable_1ra_disk_tag = False
        any_disk_tag_any_doc = False
        any_gate_empty = False
        for d in sent_docs:
            tlen = len((d.extracted_text or ""))
            disk_z, disk_tag = disk_dispositiva(d)
            is2da = fe._is_segunda_instancia(d)
            real_tag = disk_tag and not str(disk_tag).startswith(("ERR", "FILE"))
            rec["sent_docs"].append({
                "doc_id": d.id, "doc_type": d.doc_type,
                "filename": d.filename, "text_len": tlen,
                "gate_ok": tlen > 500, "is_2da_filter": is2da,
                "disk_tag": disk_tag,
            })
            if tlen <= 500:
                any_gate_empty = True
            if real_tag:
                any_disk_tag_any_doc = True
                if d.doc_type == "SENTENCIA_1RA" and tlen > 500 and not is2da:
                    usable_1ra_disk_tag = True
        if usable_1ra_disk_tag:
            # El extractor DEBERÍA haberlo cogido; revisar por qué no (raro).
            rec["subcausa"] = "EXTRACTOR_SHOULD_HIT"
        elif any_disk_tag_any_doc:
            # El disco da tag pero por un doc 2da/oficio o un 1RA filtrado como 2da.
            rec["subcausa"] = "DISK_TAG_BUT_FILTERED"
        elif any_gate_empty:
            rec["subcausa"] = "GATE_EMPTY_TEXT"
        else:
            rec["subcausa"] = "DISK_NO_DISPOSITIVA"
        out.append(rec)

    # Resumen por subcausa
    from collections import Counter
    cnt = Counter(r["subcausa"] for r in out)
    print("=== SUBCAUSAS ===")
    for k, v in cnt.most_common():
        print(f"  {k}: {v}")
    print()
    for r in sorted(out, key=lambda x: x["subcausa"]):
        ds = ", ".join(f"#{s['doc_id']}({s['doc_type']},len={s['text_len']},2da={s['is_2da_filter']},disk={s['disk_tag']})"
                       for s in r["sent_docs"]) or "(sin doc sentencia)"
        print(f"c{r['case_id']} [{r['rad']}] DB={r['db_sentido']:<16} {r['subcausa']:<22} {ds}")

    with open("data/diag_grupo_d.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n-> data/diag_grupo_d.json ({len(out)} casos)")
    db.close()


if __name__ == "__main__":
    main()
