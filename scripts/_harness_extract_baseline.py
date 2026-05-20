#!/usr/bin/env python3
"""Harness de extracción mejorado — baseline 4B.

Dos mejoras model-agnósticas:
  1. RETRIEVAL DECISIVO: rankea los docs por señal resolutiva (filename + contenido:
     SENTENCIA/FALLO/RESUELVE/DESISTIMIENTO/ACEPTA/INCIDENTE) y arma el texto con
     head+tail de los más decisivos + la demanda (para asunto/pretensiones). Así el
     doc que DECIDE entra en la ventana (no se trunca como en el head-only).
  2. CONSTRAINED DECODING: JSON-schema con enums para campos de vocab cerrado
     (derecho_vulnerado, sentido_fallo_1st) → el modelo NO puede inventar "ADMITIR".

Corre el 4B local con (grammar OFF) y (grammar ON) sobre el MISMO texto decisivo,
para aislar el efecto. No toca producción ni la DB. Uso: _harness_extract_baseline.py <case_id>
"""
from __future__ import annotations
import json, re, sqlite3, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "tutelas.db"
LLM = "http://127.0.0.1:8765/v1/chat/completions"

DERECHO_VOCAB = ["EDUCACION","SALUD","PETICION","DEBIDO_PROCESO","VIDA","SEGURIDAD_SOCIAL",
                 "MINIMO_VITAL","TRABAJO","IGUALDAD","INTIMIDAD","HABEAS_DATA","OTRO","SIN_DETERMINAR"]
SENTIDO_VOCAB = ["CONCEDE","NIEGA","IMPROCEDENTE","CARENCIA_OBJETO","DESISTIMIENTO",""]

DECISIVE_KW = ("SENTENCIA","FALLO","RESUELVE","FALLA","DESISTIMIENT","ACEPTA","INCIDENTE",
               "DESACATO","CONCEDE","NIEGA","IMPROCEDENTE","REVOCA","CONFIRMA")
TUTELA_KW = ("TUTELA","DEMANDA","PRETENSION","ESCRITO")

SYSTEM = """/no_think
Eres un abogado experto en acciones de tutela colombianas (Decreto 2591 de 1991),
analista del equipo jurídico de la SECRETARÍA DE EDUCACIÓN de la GOBERNACIÓN DE
SANTANDER. Extraes datos estructurados con precisión forense. Solo extraes.

PARTES: accionante = quien interpone (o agente oficioso/representante de un menor);
accionado = contra quien va; vinculado = tercero llamado al trámite. No los confundas.
CIUDAD = municipio donde se afecta el derecho, NUNCA la del juzgado.

SENTIDOS DE FALLO 1ra (cerrado): CONCEDE, NIEGA, IMPROCEDENTE, CARENCIA_OBJETO
(hecho superado/daño consumado), DESISTIMIENTO (el accionante desiste y el juez lo
ACEPTA → no hay fallo de fondo). Si concede u ordena algo en cualquier ordinal → CONCEDE.
Si no hay decisión de fondo en el texto, deja "".

ANTI-ALUCINACIÓN: extrae SOLO lo literal y claro. Prohibido inventar nombres, fechas,
radicados, FOREST o entidades. Si dudas, vacío. Mejor vacío que inventado.
FORMATO: responde SOLO el JSON pedido, sin explicaciones, sin <think>."""

USER_TMPL = """/no_think
Extrae estos campos del expediente y devuelve SOLO el JSON:
- accionados, vinculados (entidades, separadas por coma, o "")
- derecho_vulnerado (uno del vocab)
- asunto (1 línea, de qué trata, ≤120 chars)
- pretensiones (lo que pide el accionante, ≤200 chars)
- sentido_fallo_1st (del vocab cerrado; "" si no hay decisión de fondo)

Texto del expediente:
{text}"""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "accionados": {"type": "string"},
        "vinculados": {"type": "string"},
        "derecho_vulnerado": {"type": "string", "enum": DERECHO_VOCAB},
        "asunto": {"type": "string"},
        "pretensiones": {"type": "string"},
        "sentido_fallo_1st": {"type": "string", "enum": SENTIDO_VOCAB},
    },
    "required": ["accionados", "vinculados", "derecho_vulnerado", "asunto", "pretensiones", "sentido_fallo_1st"],
}


def head_tail(t: str, head=1800, tail=1500) -> str:
    t = t or ""
    if len(t) <= head + tail:
        return t
    return t[:head] + "\n[...]\n" + t[-tail:]


def decisive_text(case_id: int, budget=6500) -> tuple[str, list]:
    con = sqlite3.connect(str(DB)); con.row_factory = sqlite3.Row; c = con.cursor()
    docs = [d for d in c.execute(
        "SELECT id,filename,doc_type,extracted_text FROM documents WHERE case_id=? AND extracted_text IS NOT NULL", (case_id,))
        if (d["extracted_text"] or "").strip()]
    con.close()

    def score(d):
        fn = (d["filename"] or "").upper(); tx = (d["extracted_text"] or "").upper()
        s = sum(3 for kw in DECISIVE_KW if kw in fn) + sum(2 for kw in DECISIVE_KW if kw in tx[:1200] or kw in tx[-1500:])
        s += sum(1 for kw in TUTELA_KW if kw in fn)
        return s

    ranked = sorted(docs, key=score, reverse=True)
    # garantizar que la demanda/tutela esté (para asunto/pretensiones)
    tutela = next((d for d in docs if "TUTELA" in (d["filename"] or "").upper() or "DEMANDA" in (d["doc_type"] or "").upper()), None)
    chosen, used = [], 0
    order = ranked[:]
    if tutela and tutela not in ranked[:3]:
        order = ranked[:3] + [tutela] + [d for d in ranked[3:] if d is not tutela]
    for d in order:
        seg = head_tail(d["extracted_text"])
        if used + len(seg) > budget:
            seg = seg[: max(0, budget - used)]
        if not seg:
            break
        chosen.append((d["filename"], score(d), len(seg)))
        used += len(seg)
        if used >= budget:
            break
    text = "\n\n".join(f"=== {fn} ===\n{head_tail(next(d['extracted_text'] for d in docs if d['filename']==fn))}"
                       for fn, _, _ in chosen)[:budget]
    return text, chosen


def call(text: str, use_grammar: bool) -> tuple[dict, float]:
    body = {
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": USER_TMPL.format(text=text)}],
        "max_tokens": 400, "temperature": 0,
    }
    if use_grammar:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "extraccion", "schema": SCHEMA, "strict": True}}
    t0 = time.time()
    req = urllib.request.Request(LLM, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    raw = urllib.request.urlopen(req, timeout=180).read().decode()
    dt = time.time() - t0
    content = json.loads(raw)["choices"][0]["message"]["content"] or ""
    m = re.search(r"\{[\s\S]*\}", content)
    try:
        return (json.loads(m.group(0)) if m else {"_raw": content[:200]}), dt
    except Exception:
        return {"_raw": content[:200]}, dt


def main():
    cid = int(sys.argv[1]) if len(sys.argv) > 1 else 427
    text, chosen = decisive_text(cid)
    print(f"=== RETRIEVAL DECISIVO (case {cid}) — {len(text)} chars ===", file=sys.stderr)
    for fn, sc, ln in chosen:
        print(f"   [score {sc:>2}] {ln:>5}c  {fn[:50]}", file=sys.stderr)
    off, dt_off = call(text, use_grammar=False)
    on, dt_on = call(text, use_grammar=True)
    print(json.dumps({"case": cid, "retrieval_docs": [f for f, _, _ in chosen],
                      "grammar_off": {"latencia_s": round(dt_off, 1), **off},
                      "grammar_on": {"latencia_s": round(dt_on, 1), **on}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
