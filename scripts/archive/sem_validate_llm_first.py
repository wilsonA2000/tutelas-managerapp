#!/usr/bin/env python3
"""Validación: ¿el clasificador LLM REAL del pipeline arregla asunto/derecho?

Llama a los clasificadores ya existentes (_llm_classify_asunto / _llm_classify_derecho)
con la MISMA selección de texto que usaría el pipeline, y compara contra el valor
actual en DB (que es source=regex). NO escribe nada.

Uso: ./venv/bin/python3 scripts/sem_validate_llm_first.py 18 60 23 24 ...
"""
from __future__ import annotations
import sys, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import re
from backend.database.database import SessionLocal
from backend.database.models import Case, Document
from backend.v9.field_extractor import (
    _llm_classify_asunto, _llm_classify_derecho, _asunto_case_text,
    _asunto_vocab, _DERECHO_DOC_PRIORITY, _read_doc_text,
)

# --- Selección de fuente MEJORADA (prototipo del fix) ---------------------
_DEM_MARK = [r"BAJO LA GRAVEDAD DEL JURAMENTO", r"NO HE PRESENTADO OTRA",
             r"PRETENSIONES", r"\bHECHOS\b", r"JURAMENTO", r"ACCION DE TUTELA",
             r"instaur", r"interpong", r"agente oficios", r"en mi calidad de"]
# El head delata un doc que NO es la demanda original (es etapa procesal posterior).
_NOT_DEMANDA = re.compile(
    r"INCIDENTE DE DESACATO|AUTO\b|INFORME DE CUMPLIMIENTO|VISITA OCULAR|"
    r"REQUERIMIENTO PREVIO|DECIDE SANCI|APERTURA.{0,8}PRUEBAS|NO SANCIONA", re.I)
# Doctypes que reformulan el RECLAMO ORIGINAL limpio (no la etapa de desacato).
_CLAIM_PREF = ["DEMANDA_TUTELA", "ANEXO_DEMANDA", "AUTO_ADMISORIO",
               "SENTENCIA_1RA", "SENTENCIA_2DA"]


def _best_claim_text(db, case):
    """Devuelve (etiqueta, texto, es_demanda_real) del doc que mejor refleja el
    RECLAMO ORIGINAL — no la etapa procesal. Penaliza autos/desacato/informes."""
    rows = [(d.doc_type or "OTRO", d.filename or "",
             d.extracted_text if d.extracted_text else (_read_doc_text(d) or ""))
            for d in db.query(Document).filter(Document.case_id == case.id).all()]
    scored = []
    for dt, fn, t in rows:
        if len(t) < 250:
            continue
        head = t[:6000]
        sc = sum(2 for m in _DEM_MARK if re.search(m, head, re.I))
        if dt in ("DEMANDA_TUTELA", "ANEXO_DEMANDA"):
            sc += 2
        if dt == "AUTO_ADMISORIO":
            sc += 3  # restatement limpio del reclamo original
        if _NOT_DEMANDA.search(t[:1400]):
            sc -= 6   # head de etapa procesal posterior → no es la demanda
        scored.append((sc, dt, fn, t))
    if not scored:
        return None, "", False
    scored.sort(key=lambda x: (-x[0], -len(x[3])))
    sc, dt, fn, t = scored[0]
    return f"{dt}:{fn[:28]}", t[:9000], sc >= 4


def _derecho_llm_text(db, case):
    """Replica la selección de texto que extract_derecho_vulnerado_for_case
    pasa al LLM: concat de los docs de doctype prioritario (auto/demanda/sent),
    primeros 9000 chars c/u, hasta 3."""
    docs_by_type = {}
    for d in db.query(Document).filter(Document.case_id == case.id).all():
        docs_by_type.setdefault(d.doc_type or "OTRO", []).append(d)
    chunks = []
    for dt in _DERECHO_DOC_PRIORITY:
        for d in docs_by_type.get(dt, []):
            t = d.extracted_text if d.extracted_text else _read_doc_text(d)
            if t and len(t) >= 200:
                chunks.append(t[:9000])
    if not chunks:
        longest = sorted(
            (d for d in db.query(Document).filter(Document.case_id == case.id).all()
             if d.extracted_text),
            key=lambda d: len(d.extracted_text or ""), reverse=True)
        if longest:
            chunks = [(longest[0].extracted_text or "")[:9000]]
    return "\n\n".join(chunks[:3])


def main():
    ids = [int(x) for x in sys.argv[1:]]
    db = SessionLocal()
    vocab = _asunto_vocab()
    try:
        for cid in ids:
            case = db.query(Case).filter(Case.id == cid).first()
            if not case:
                print(json.dumps({"case": cid, "err": "no existe"})); continue
            src, claim_text, is_real = _best_claim_text(db, case)
            a_llm = _llm_classify_asunto(claim_text, vocab) if claim_text else None
            d_llm = _llm_classify_derecho(claim_text) if claim_text else None
            print(json.dumps({
                "case": cid, "src": src, "demanda_real": is_real,
                "asunto_db": case.asunto, "asunto_llm": a_llm,
                "derecho_db": case.derecho_vulnerado, "derecho_llm": d_llm,
            }, ensure_ascii=False), flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
