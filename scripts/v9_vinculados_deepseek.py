#!/usr/bin/env python3
"""Puebla la columna `vinculados` (y limpia `accionados`) con DeepSeek-V3.

DeepSeek, en la revisión anterior, metió los vinculados de oficio DENTRO del campo
`accionados`. Este pase los separa: por cada caso le da el AUTO ADMISORIO (que lista las
partes) + lo que hay hoy en `accionados`/`vinculados`, y pide de vuelta:
  {accionados: "X - Y", vinculados: "Z - W"}  — accionados = contra quién va la tutela;
  vinculados = terceros que el JUEZ vinculó de oficio (vacío si no hay).
Aplica (--apply): `vinculados` siempre que DeepSeek devuelva algo; `accionados` solo si el
valor actual contiene "vinculad"/"tercero" (es la versión mezclada → la reemplaza por la limpia).

Requiere DEEPSEEK_API_KEY en el entorno. Coste ≈ $0.20-0.40 para los ~400 casos.
    DEEPSEEK_API_KEY='sk-...' ./venv/bin/python3 scripts/v9_vinculados_deepseek.py --limit 4
    DEEPSEEK_API_KEY='sk-...' ./venv/bin/python3 scripts/v9_vinculados_deepseek.py --apply --workers 8
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal  # noqa: E402
from backend.database.models import Case, Document  # noqa: E402
from backend.v9.field_extractor import _read_doc_text  # noqa: E402

SHELL_FOLDER = "__SIN_RADICADO__"
_DOC_PRIORITY = [("AUTO_ADMISORIO",), ("SENTENCIA_1RA",), ("DEMANDA_TUTELA", "ANEXO_DEMANDA"), ("INCIDENTE_DESACATO", "AUTO_INCIDENTE")]
_SYSTEM = ("Identificas las partes de una acción de tutela. Distingues ACCIONADOS (contra quién se "
           "dirige la tutela, los demandados) de VINCULADOS DE OFICIO (terceros que el JUEZ vincula "
           "para que se pronuncien). Respondes solo con un objeto JSON válido.")


def _doc_head(db, cid, n=4000):
    for dts in _DOC_PRIORITY:
        for dt in dts:
            best = None
            for d in db.query(Document).filter(Document.case_id == cid, Document.doc_type == dt).all():
                t = _read_doc_text(d)
                if t and len(t) >= 200 and (best is None or len(t) > len(best)):
                    best = t
            if best:
                return best[:n].strip()
    return ""


def _ask(client, model, head, cur_acc, cur_vinc, folder):
    prompt = (
        f"Expediente «{folder}». Lo que hay hoy en el cuadro:\n  accionados: {cur_acc or '(vacío)'}\n  vinculados: {cur_vinc or '(vacío)'}\n\n"
        f"AUTO/SENTENCIA (fragmento):\n{head}\n\n"
        "Devuelve SOLO este JSON:\n"
        '{"accionados": "lista de los ACCIONADOS (contra quién va la tutela) separados por \\" - \\"; usa el nombre completo de la entidad",\n'
        ' "vinculados": "lista de los VINCULADOS DE OFICIO / terceros interesados que el JUEZ vinculó, separados por \\" - \\"; cadena vacía si el juez no vinculó a nadie de oficio"}\n'
        "Si no hay suficiente información en los documentos, deja ambos como cadena vacía."
    )
    try:
        r = client.chat.completions.create(model=model, max_tokens=400, temperature=0,
            messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
            response_format={"type": "json_object"}, timeout=90)
        txt = (r.choices[0].message.content or "").strip()
    except Exception as e:  # noqa: BLE001
        return {"__err__": f"{type(e).__name__}: {str(e)[:140]}"}
    txt = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", txt.strip())
    m = re.search(r"\{.*\}", txt, re.DOTALL)
    try:
        return json.loads(m.group(0)) if m else {"__err__": "no-json"}
    except json.JSONDecodeError:
        return {"__err__": "json-malo"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--model", default="deepseek-v4-flash")
    args = ap.parse_args()
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        print("ERROR: define DEEPSEEK_API_KEY en el entorno.", file=sys.stderr); return 2
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    db = SessionLocal()
    try:
        cases = db.query(Case).filter(Case.folder_name.isnot(None), Case.folder_name != "", Case.folder_name != "None",
                                      Case.folder_name != SHELL_FOLDER, Case.processing_status != "DUPLICATE_MERGED").order_by(Case.id).all()
        if args.limit:
            cases = cases[: args.limit]
        jobs = []
        for c in cases:
            head = _doc_head(db, c.id)
            if not head and not (c.accionados or "").strip():
                continue
            jobs.append((c.id, c.folder_name, head, (c.accionados or "").strip(), (c.vinculados or "").strip()))
        print(f"Casos a procesar: {len(jobs)} · modelo {args.model} · workers {args.workers} · {'APPLY' if args.apply else 'DRY-RUN'}\n")

        lock = threading.Lock(); out = {}
        def _w(j):
            cid, folder, head, acc, vinc = j
            return cid, folder, acc, vinc, _ask(client, args.model, head, acc, vinc, folder)
        n_ok = n_err = 0
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for i, fut in enumerate(as_completed([ex.submit(_w, j) for j in jobs]), 1):
                cid, folder, acc, vinc, r = fut.result()
                if "__err__" in r:
                    n_err += 1; print(f"  [{i}/{len(jobs)}] #{cid} ⚠ {r['__err__']}"); continue
                n_ok += 1
                with lock: out[cid] = (acc, vinc, r)
                na = re.sub(r"\s+", " ", str(r.get("accionados") or "")).strip()
                nv = re.sub(r"\s+", " ", str(r.get("vinculados") or "")).strip()
                print(f"  [{i}/{len(jobs)}] #{cid} '{folder[:36]}'  vinc→ {nv[:90] or '(ninguno)'}")
        n_v = n_a = 0
        if args.apply:
            for cid, (acc, vinc, r) in out.items():
                c = db.get(Case, cid)
                if not c: continue
                nv = re.sub(r"\s+", " ", str(r.get("vinculados") or "")).strip().strip('"')
                na = re.sub(r"\s+", " ", str(r.get("accionados") or "")).strip().strip('"')
                if nv and nv.lower() not in ("none", "null", "n/a", "(vacío)", "no aplica") and len(nv) >= 4:
                    if nv != (c.vinculados or ""):
                        c.vinculados = nv[:1500]; n_v += 1
                # accionados: solo reemplazar si el actual está la versión mezclada y DeepSeek dio algo razonable
                if na and 6 <= len(na) <= 1500 and re.search(r"(?i)vinculad|tercero", c.accionados or "") and na.lower() not in ("none", "null"):
                    c.accionados = na[:1500]; n_a += 1
            db.commit()
        print(f"\nOK: {n_ok} · errores: {n_err}")
        print(f"{'APLICADO' if args.apply else 'DRY-RUN'} — vinculados {'escritos' if args.apply else 'a escribir'}: {n_v} · accionados limpiados: {n_a}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
