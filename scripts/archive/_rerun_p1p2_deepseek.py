#!/usr/bin/env python3
"""Gemelo de _rerun_p1p2_4b.py pero usando DeepSeek-V3 como LLM de fallback.

Mismo set (P1+P2), mismo regex (SR._extraer_ordenes_de_texto), mismo prompt
(SR._PROMPT_SYSTEM) → la única variable es el motor LLM. Para comparar 4B local
vs DeepSeek manzanas con manzanas. DRY-RUN: no escribe en la DB.

Salida: data/rerun_deepseek_p1p2.json
Requiere DEEPSEEK_API_KEY en el entorno.
"""
from __future__ import annotations
import json, os, re, sqlite3, sys, time
from pathlib import Path

from openai import OpenAI
from backend.services import seguimiento_resolutivo as SR
from backend.services import seguimiento_extractor as SE

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "tutelas.db"
RERUN = ROOT / "data" / "seguimiento_rerun_2026-05-19.json"
OUT = ROOT / "data" / "rerun_deepseek_p1p2.json"
MODEL = "deepseek-chat"


def ask_deepseek(client, tail: str) -> tuple[list[dict], float]:
    bloque = tail[:8000]
    user = f"PARTE RESOLUTIVA:\n{bloque}\n\nExtrae las órdenes de cumplimiento."
    t0 = time.time()
    r = client.chat.completions.create(
        model=MODEL, temperature=0, max_tokens=900,
        messages=[{"role": "system", "content": SR._PROMPT_SYSTEM},
                  {"role": "user", "content": user}],
    )
    dt = time.time() - t0
    raw = r.choices[0].message.content or ""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        data = json.loads(m.group(0) if m else raw)
        return (data.get("ordenes", []) or []), dt
    except Exception:
        return [], dt


def main():
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key:
        print("FALTA DEEPSEEK_API_KEY", file=sys.stderr); return 1
    client = OpenAI(api_key=key, base_url="https://api.deepseek.com")

    d = json.load(open(RERUN))
    con = sqlite3.connect(str(DB)); con.row_factory = sqlite3.Row
    c = con.cursor()

    def meta(cid):
        return c.execute("SELECT accionante,sentido_fallo_1st,sentido_fallo_2nd,fecha_fallo_1st,fecha_fallo_2nd FROM cases WHERE id=?", (cid,)).fetchone()

    def nord(cid):
        return c.execute("SELECT COUNT(*) FROM compliance_tracking WHERE case_id=? AND ordinal_nombre IS NOT NULL", (cid,)).fetchone()[0]

    targets = []
    for x in d["no_match"]:
        cid = x["case_id"]; r = meta(cid)
        if not r:
            continue
        s1 = (r["sentido_fallo_1st"] or "").upper(); s2 = (r["sentido_fallo_2nd"] or "").upper()
        if (("CONCEDE" in s1) or any(k in s2 for k in ("CONCEDE", "REVOCA", "CONFIRMA", "MODIFICA"))) and nord(cid) == 0 and x.get("pdf"):
            targets.append((cid, x["pdf"]))
    for x in d["no_pdf"]:
        cid = x["case_id"]
        doc = c.execute("""SELECT file_path FROM documents WHERE case_id=? AND doc_type LIKE 'SENTENCIA%'
                           ORDER BY (doc_type='SENTENCIA_2DA') DESC, id DESC LIMIT 1""", (cid,)).fetchone()
        if doc and doc["file_path"]:
            targets.append((cid, doc["file_path"]))

    print(f"Total: {len(targets)}", file=sys.stderr)
    out = []
    for i, (cid, pdf) in enumerate(targets, 1):
        r = meta(cid)
        rec = {"case_id": cid, "accionante": r["accionante"], "f1": r["sentido_fallo_1st"], "f2": r["sentido_fallo_2nd"], "pdf": Path(pdf).name}
        try:
            # filtro por sentido idéntico al de SR
            s1 = (r["sentido_fallo_1st"] or "").upper(); s2 = (r["sentido_fallo_2nd"] or "").upper()
            tail, npg, ocr = SR.read_resolutive_tail(pdf, 7)
            rec["ocr"] = ocr
            if not tail.strip():
                rec.update(metodo="vacio", n=0, ordenes=[]); out.append(rec)
                continue
            regex_ord = SE._extraer_ordenes_de_texto(tail, r["fecha_fallo_2nd"] or r["fecha_fallo_1st"], True, lenient_resuelve=True)
            if regex_ord:
                rec.update(metodo="regex_tail", n=len(regex_ord),
                           ordenes=[{"ordinal": o.ordinal_nombre, "accion": o.accion_resumida[:160], "source": "regex"} for o in regex_ord])
            else:
                ds, dt = ask_deepseek(client, tail)
                rec.update(metodo="deepseek", n=len(ds), latencia_s=round(dt, 1), ordenes=ds)
        except Exception as e:
            rec.update(metodo="ERROR", error=str(e)[:160])
        out.append(rec)
        print(f"\r[{i}/{len(targets)}] case {cid} {rec.get('metodo')} n={rec.get('n','-')}      ", end="", file=sys.stderr)
    print(file=sys.stderr)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"DONE -> {OUT.name}; {sum(1 for r in out if r.get('n',0)>0)} con órdenes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
