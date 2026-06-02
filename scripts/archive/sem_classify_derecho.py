#!/usr/bin/env python3
"""Clasificador semántico LOCAL (Qwen 4B) de derecho_vulnerado + asunto.

Lee la demanda (o el mejor doc sustituto) de un caso y propone los derechos
fundamentales REALMENTE invocados + el asunto, contra vocabulario controlado.
NO escribe a la DB — solo propone. Wilson/Claude validan 1-a-1.

Uso:
    ./venv/bin/python3 scripts/sem_classify_derecho.py 9 18 92 ...
    ./venv/bin/python3 scripts/sem_classify_derecho.py --file data/cand.txt
"""
import sqlite3, json, sys, urllib.request, re

DB = "data/tutelas.db"
LLM_URL = "http://127.0.0.1:8765/v1/chat/completions"

DERECHOS_VOCAB = [
    "EDUCACION", "SALUD", "VIDA", "TRABAJO", "PETICION", "DEBIDO_PROCESO",
    "IGUALDAD", "SEGURIDAD_SOCIAL", "MINIMO_VITAL", "INTIMIDAD", "HABEAS_DATA",
]
ASUNTO_VOCAB = [
    "TRASLADO", "NOMBRAMIENTO", "MATRICULA", "SALUD_DOCENTE", "PENSION",
    "SALARIO", "CESANTIAS", "REINTEGRO", "TESORERIA", "CNSC_CONCURSO",
    "INCLUSION_DISCAPACIDAD", "PROTECCION_MENOR", "TUTOR_SOMBRA",
    "TRANSPORTE_ESCOLAR", "ALIMENTACION_PAE", "CALIDAD_EDUCATIVA",
    "DERECHO_PETICION", "DEBIDO_PROCESO", "INSPECCION",
]
# Preferencia de doc fuente: la demanda primero; luego lo que reformula derechos.
SRC_PREF = ["DEMANDA_TUTELA", "ANEXO_DEMANDA", "AUTO_ADMISORIO",
            "PDF_AUTO_ADMISORIO", "SENTENCIA_1RA", "PDF_SENTENCIA",
            "IMPUGNACION", "RESPUESTA"]

PROMPT = """/no_think
Eres un clasificador jurídico de tutelas colombianas. Lee el texto y responde SOLO con JSON.

Identifica:
1. "derechos": lista de los DERECHOS FUNDAMENTALES que el ACCIONANTE invoca como VULNERADOS.
   Vocabulario permitido (usa SOLO estos): {derechos}
   REGLA CLAVE: "EDUCACION" va SOLO si lo vulnerado es el derecho a la educación de un
   ESTUDIANTE/MENOR. Que el accionado sea la "Secretaría de Educación" NO implica EDUCACION;
   un docente que reclama traslado/nombramiento/salud/pensión invoca TRABAJO/SALUD/
   SEGURIDAD_SOCIAL/DEBIDO_PROCESO, NO educación.
2. "asunto": UNA etiqueta del vocabulario: {asuntos}
3. "razon": máximo 15 palabras, en qué frase del texto te basas.

Responde EXACTAMENTE:
{{"derechos": ["..."], "asunto": "...", "razon": "..."}}

TEXTO:
---
{texto}
---
JSON:"""


_DEM_MARK = [r"BAJO LA GRAVEDAD DEL JURAMENTO", r"NO HE PRESENTADO OTRA",
             r"PRETENSIONES", r"\bHECHOS\b", r"JURAMENTO", r"ACCION DE TUTELA",
             r"instaur", r"interpong", r"agente oficios", r"en mi calidad de"]
_BAD_HEAD = re.compile(r"AUTO\b|INFORME DE CUMPLIMIENTO|RESUELVE|SENTENCIA|"
                       r"VISITA OCULAR|NOTIFICA|REQUERIMIENTO PREVIO", re.I)


def get_source_text(cur, cid):
    """Elige el doc que MÁS parece la demanda original del accionante, sin
    confiar en el rótulo doc_type (a veces autos quedan como DEMANDA_TUTELA).
    Devuelve (etiqueta_fuente, texto, es_demanda_real)."""
    rows = cur.execute(
        "SELECT doc_type, filename, COALESCE(extracted_text,'') t FROM documents WHERE case_id=?",
        (cid,)).fetchall()
    scored = []
    for dt, fn, t in rows:
        if len(t) < 300:
            continue
        head = t[:6000]
        sc = sum(2 for m in _DEM_MARK if re.search(m, head, re.I))
        if dt in ("DEMANDA_TUTELA", "ANEXO_DEMANDA"):
            sc += 2
        if dt in ("INCIDENTE_DESACATO",):
            sc += 1
        if _BAD_HEAD.search(t[:1200]):
            sc -= 4
        scored.append((sc, dt, fn, t))
    if not scored:
        return None, "", False
    scored.sort(key=lambda x: (-x[0], -len(x[3])))
    sc, dt, fn, t = scored[0]
    is_real = sc >= 4  # umbral: parece demanda real (no un auto suelto)
    return f"{dt}:{fn[:30]}", t, is_real


def head_window(text, n=8500):
    """Head del doc + ventana alrededor de 'DERECHOS ... VULNERAD' si aparece tarde."""
    head = text[:n]
    m = re.search(r"DERECHOS?\s+(FUNDAMENTALES?\s+)?(QUE\s+SE\s+)?(CONSIDERAN?\s+)?VULNERAD",
                  text[n:], re.I)
    if m:
        s = n + m.start()
        head += "\n...\n" + text[s:s + 1500]
    return head


def classify(texto):
    body = {
        "model": "Qwen3-4B-Q4_K_M.gguf",
        "messages": [{"role": "user", "content": PROMPT.format(
            derechos=", ".join(DERECHOS_VOCAB),
            asuntos=", ".join(ASUNTO_VOCAB),
            texto=texto)}],
        "temperature": 0.0,
        "max_tokens": 250,
        "stream": False,
    }
    req = urllib.request.Request(
        LLM_URL, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        out = json.load(resp)
    content = out["choices"][0]["message"]["content"].strip()
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        return {"_raw": content, "_error": "no_json"}
    try:
        return json.loads(m.group(0))
    except Exception as e:
        return {"_raw": content, "_error": str(e)}


def main():
    args = sys.argv[1:]
    ids = []
    if args and args[0] == "--file":
        ids = [int(x) for x in open(args[1]).read().split()]
    else:
        ids = [int(x) for x in args]
    con = sqlite3.connect(DB); cur = con.cursor()
    for cid in ids:
        row = cur.execute(
            "SELECT asunto, derecho_vulnerado FROM cases WHERE id=?", (cid,)).fetchone()
        cur_a, cur_d = (row or ("", ""))
        src, txt, is_real = get_source_text(cur, cid)
        if not txt:
            print(json.dumps({"case": cid, "_error": "sin texto"}, ensure_ascii=False), flush=True)
            continue
        prop = classify(head_window(txt))
        prop_d = " - ".join(prop.get("derechos", [])) if isinstance(prop.get("derechos"), list) else prop.get("derechos")
        print(json.dumps({
            "case": cid, "src": src, "demanda_real": is_real,
            "asunto_db": cur_a, "asunto_llm": prop.get("asunto"),
            "derecho_db": cur_d, "derecho_llm": prop_d,
            "razon": prop.get("razon"), "err": prop.get("_error"),
        }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
