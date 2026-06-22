#!/usr/bin/env python3
"""Re-extrae órdenes de los casos 2da=CONFIRMA leyendo la 1ra instancia (DeepSeek).

Valida el fix del flujo CONFIRMA: usa SR.doc_sentencia_para_ordenes() para elegir
el fallo de 1ra (donde vive la orden), lee su cola resolutiva, regex primero y
DeepSeek como fallback. DRY-RUN → data/confirma_1ra_ds.json.
"""
from __future__ import annotations
import json, os, re, sqlite3, sys, time
from pathlib import Path
from openai import OpenAI
from backend.services import seguimiento_resolutivo as SR
from backend.services import seguimiento_extractor as SE

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "tutelas.db"
OUT = ROOT / "data" / "confirma_1ra_ds.json"


def ask_ds(client, tail):
    r = client.chat.completions.create(
        model="deepseek-chat", temperature=0, max_tokens=900,
        messages=[{"role": "system", "content": SR._PROMPT_SYSTEM},
                  {"role": "user", "content": f"PARTE RESOLUTIVA:\n{tail[:8000]}\n\nExtrae las órdenes de cumplimiento."}])
    raw = r.choices[0].message.content or ""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        return json.loads(m.group(0) if m else raw).get("ordenes", []) or []
    except Exception:
        return []


def main():
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
    con = sqlite3.connect(str(DB)); con.row_factory = sqlite3.Row; c = con.cursor()
    cases = list(c.execute("""SELECT id,accionante,sentido_fallo_1st,sentido_fallo_2nd,fecha_fallo_1st
        FROM cases WHERE UPPER(COALESCE(sentido_fallo_2nd,'')) LIKE '%CONFIRMA%'
          AND processing_status!='DUPLICATE_MERGED' ORDER BY id"""))
    out = []
    for i, cas in enumerate(cases, 1):
        docs = list(c.execute("SELECT doc_type,file_path FROM documents WHERE case_id=? ORDER BY id", (cas["id"],)))
        fp, inst = SR.doc_sentencia_para_ordenes(docs, cas["sentido_fallo_2nd"])
        rec = {"case_id": cas["id"], "accionante": cas["accionante"],
               "f1": cas["sentido_fallo_1st"], "f2": cas["sentido_fallo_2nd"],
               "doc_inst": inst, "doc": Path(fp).name if fp else None}
        if not fp or not os.path.exists(fp):
            rec.update(metodo="no_doc", n=0, ordenes=[]); out.append(rec); continue
        try:
            tail, _, ocr = SR.read_resolutive_tail(fp, 7)
            rec["ocr"] = ocr
            regex_ord = SE._extraer_ordenes_de_texto(tail, cas["fecha_fallo_1st"], True, lenient_resuelve=True)
            if regex_ord:
                rec.update(metodo="regex_1ra", n=len(regex_ord),
                           ordenes=[{"ordinal": o.ordinal_nombre, "dest": o.destinatario_tipo, "accion": o.accion_resumida[:160]} for o in regex_ord])
            else:
                ds = ask_ds(client, tail)
                rec.update(metodo="deepseek_1ra", n=len(ds), ordenes=ds)
        except Exception as e:
            rec.update(metodo="ERROR", error=str(e)[:140])
        out.append(rec)
        print(f"\r[{i}/{len(cases)}] case {cas['id']} {rec.get('metodo')} n={rec.get('n','-')}     ", end="", file=sys.stderr)
    print(file=sys.stderr)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"DONE -> {OUT.name}; {sum(1 for r in out if r.get('n',0)>0)}/{len(out)} con órdenes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
