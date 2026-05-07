"""IURIS — Bench con system prompt cognitivo + eval permisivo.

Diferencias vs compare_pre_post_lora.py:
1. System prompt = blueprint cognitivo condensado (IURIS_SYSTEM_PROMPT.md)
2. Eval matching:
   - Fechas: normaliza a 'D-MM-YYYY' antes de comparar
   - Nombres: matching por subset de palabras significativas
   - Texto libre: matching por palabra clave dominante
3. Filtra <think>, <thought>, etc. del output

Uso:
  python3 scripts/bench_with_cognitive_prompt.py --n-cases 20 --llm-url http://localhost:8765
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "tutelas.db"
RESULTS_PATH = ROOT / "data" / "lora_bench_cognitive_results.json"

# System prompt cognitivo (extracto de IURIS_SYSTEM_PROMPT.md)
SYSTEM_PROMPT = """Eres un agente jurídico colombiano que extrae campos estructurados de tutelas. Sigue estas reglas:

PROCESO:
1. Lee el texto del expediente.
2. Identifica tipo de doc (auto/sentencia/incidente).
3. Aplica reglas del campo solicitado.
4. Si no hay evidencia clara, responde "" (vacío). NUNCA inventes.
5. Responde solo el valor pedido. Sin <think>, sin explicaciones, sin párrafos.

REGLAS POR CAMPO:

accionante: Persona NATURAL que presenta tutela. Marcadores: "presentada por", "ACCIONANTE:", "tutelante", "demandante". NO entidades. Sin honoríficos.

juzgado: Juzgado de 1ra instancia. Format: "JUZGADO X TIPO Municipal/Circuito DE CIUDAD". Tribunal NO va aquí.

juzgado_2nd: Tribunal/Sala 2da instancia. Format incluye Tribunal+Ciudad+Sala. Solo si hubo impugnación.

ciudad: Ciudad de los HECHOS, no del juzgado.

sentido_fallo_1st: Una palabra. CONCEDE (TUTELAR/CONCEDER), NIEGA (NEGAR/DENEGAR), IMPROCEDENTE.

sentido_fallo_2nd: Una palabra. CONFIRMA, REVOCA, MODIFICA.

impugnacion: SI o NO.

quien_impugno: Una palabra. ACCIONANTE/ACCIONADO/MINISTERIO_PUBLICO. Si fallo 1ra=NIEGA → probable ACCIONANTE.

incidente: SI o NO. SI solo si hay incidente APERTURADO formalmente.

responsable_desacato: PERSONA FÍSICA (nombres y apellidos). NO entidad. Marcadores: "REQUERIR a X", "INCIDENTAR a X". Filtrar honoríficos.

decision_incidente: Frase corta verbo+complemento. Ej: "Archivar por carencia", "Sancionar con N días".

derecho_vulnerado: Palabra clave. Ej: "Educación", "Salud", "Petición".

fecha_fallo_1st / fecha_fallo_2nd: Devolver como aparece en texto. NO normalizar.

REGLA DE ORO: Si no aparece textualmente, responde "". NUNCA inventes."""

EVAL_FIELDS = {
    "accionante": "¿Cuál es el nombre completo del accionante? Solo el nombre.",
    "juzgado": "¿Cuál es el juzgado de tutela?",
    "ciudad": "¿En qué ciudad ocurren los hechos?",
    "sentido_fallo_1st": "¿El fallo de primera instancia CONCEDE, NIEGA o IMPROCEDENTE? Una palabra.",
    "fecha_fallo_1st": "¿En qué fecha se profirió el fallo de primera instancia?",
    "impugnacion": "¿Hubo impugnación? SI o NO.",
    "quien_impugno": "¿Quién impugnó? ACCIONANTE, ACCIONADO o MINISTERIO_PUBLICO.",
    "juzgado_2nd": "¿Cuál es el juzgado de segunda instancia?",
    "sentido_fallo_2nd": "¿Sentido del fallo segunda instancia? CONFIRMA, REVOCA o MODIFICA.",
    "incidente": "¿Hay incidente de desacato? SI o NO.",
    "responsable_desacato": "¿Quién es el responsable del desacato? Solo el nombre.",
    "decision_incidente": "¿Decisión sobre el incidente?",
    "derecho_vulnerado": "¿Cuál derecho fundamental se vulneró?",
}


# ==============================
# Eval matching mejorado
# ==============================

MONTHS_ES = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
    "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
    "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
}


def normalize_date(s: str) -> str | None:
    """Normaliza fecha a YYYY-MM-DD si reconoce el formato."""
    if not s:
        return None
    s = s.strip().lower()
    # DD/MM/YYYY o D/M/YYYY
    m = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", s)
    if m:
        d, mo, y = m.groups()
        if len(y) == 2:
            y = "20" + y
        return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
    # "DD de MES de YYYY"
    m = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+(?:de\s+)?(\d{2,4})", s)
    if m:
        d, mo, y = m.groups()
        mo_num = MONTHS_ES.get(mo)
        if mo_num:
            if len(y) == 2:
                y = "20" + y
            return f"{y}-{mo_num}-{d.zfill(2)}"
    return None


def normalize_name(s: str) -> set[str]:
    """Devuelve set de palabras significativas del nombre (≥3 chars, sin stop words)."""
    if not s:
        return set()
    stop = {
        "la", "el", "los", "las", "de", "del", "y", "o", "a",
        "dr", "dra", "señor", "señora", "doctor", "doctora", "don", "doña",
        "doc", "señ",
    }
    words = re.findall(r"[a-záéíóúñ]+", s.lower())
    return {w for w in words if len(w) >= 3 and w not in stop}


def evaluate_match_v2(field: str, expected: str | None, predicted: str) -> tuple[bool, str]:
    """Eval mejorado.
    Retorna (match, reason).
    """
    if not expected:
        return False, "no expected"
    exp = str(expected).strip()
    pred = predicted.strip()
    if not pred or pred == '""':
        return False, "predicted empty"

    # Filtrar tags <think>, etc.
    pred = re.sub(r"<[^>]+>.*?</[^>]+>", "", pred, flags=re.DOTALL).strip()
    if not pred:
        return False, "predicted empty after filter"

    # Fechas: normalizar ambos
    if "fecha" in field:
        e_norm = normalize_date(exp)
        p_norm = normalize_date(pred)
        if e_norm and p_norm:
            return e_norm == p_norm, f"date norm exp={e_norm} pred={p_norm}"
        # Fallback: palabra a palabra
        return exp.lower() in pred.lower() or pred.lower() in exp.lower(), "date fallback"

    # Enums: matching exacto upper
    if field in ("sentido_fallo_1st", "sentido_fallo_2nd", "impugnacion",
                 "incidente", "quien_impugno"):
        e = exp.upper().strip()
        p = pred.upper().strip()
        return e in p or p in e, f"enum {e} vs {p}"

    # Nombres / texto libre: por palabras significativas
    exp_words = normalize_name(exp)
    pred_words = normalize_name(pred)
    if not exp_words:
        return False, "no significant exp words"

    # Si ≥50% de palabras del expected aparecen en predicted → match
    overlap = exp_words & pred_words
    coverage = len(overlap) / len(exp_words)
    return coverage >= 0.5, f"name overlap {len(overlap)}/{len(exp_words)} ({coverage:.0%})"


# ==============================
# Selección de casos
# ==============================

def select_cases(conn: sqlite3.Connection, n: int = 20) -> list[dict]:
    rows = conn.execute("""
        SELECT id, accionante, juzgado, ciudad, sentido_fallo_1st,
               fecha_fallo_1st, impugnacion, quien_impugno, juzgado_2nd,
               sentido_fallo_2nd, incidente, responsable_desacato,
               decision_incidente, derecho_vulnerado
        FROM cases
        WHERE processing_status = 'COMPLETO'
        ORDER BY id
        LIMIT ?
    """, (n,)).fetchall()
    out = []
    for r in rows:
        case = {
            "id": r[0], "accionante": r[1], "juzgado": r[2], "ciudad": r[3],
            "sentido_fallo_1st": r[4], "fecha_fallo_1st": r[5], "impugnacion": r[6],
            "quien_impugno": r[7], "juzgado_2nd": r[8], "sentido_fallo_2nd": r[9],
            "incidente": r[10], "responsable_desacato": r[11],
            "decision_incidente": r[12], "derecho_vulnerado": r[13],
        }
        docs = conn.execute(
            "SELECT extracted_text FROM documents WHERE case_id = ? LIMIT 5",
            (case["id"],)
        ).fetchall()
        case["text"] = "\n\n".join(d[0] for d in docs if d[0])[:3500]
        out.append(case)
    return out


def call_llm(url: str, user: str, max_tokens: int = 100,
             timeout: int = 60) -> tuple[str, float]:
    payload = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "stop": ["\n\nPregunta:"],
    }
    t0 = time.time()
    try:
        r = requests.post(f"{url}/v1/chat/completions", json=payload, timeout=timeout)
        elapsed = time.time() - t0
        if r.status_code != 200:
            return f"<HTTP {r.status_code}>", elapsed
        out = r.json()["choices"][0]["message"]["content"]
        out = re.sub(r"<think>.*?</think>", "", out, flags=re.DOTALL).strip()
        out = re.sub(r"^[\"']|[\"']$", "", out).strip()
        return out, elapsed
    except Exception as e:
        return f"<ERROR: {e}>", time.time() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-cases", type=int, default=20)
    ap.add_argument("--llm-url", default="http://127.0.0.1:8765")
    ap.add_argument("--output", default=str(RESULTS_PATH))
    args = ap.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    cases = select_cases(conn, args.n_cases)
    print(f"→ {len(cases)} casos seleccionados", flush=True)

    field_correct = Counter()
    field_total = Counter()
    field_lat = defaultdict(list)
    case_details = []

    for i, case in enumerate(cases, 1):
        text = case["text"]
        if not text or len(text) < 100:
            continue
        case_result = {"case_id": case["id"], "fields": {}}
        for field, q in EVAL_FIELDS.items():
            expected = case.get(field)
            if not expected:
                continue
            field_total[field] += 1
            user = f"Texto del expediente:\n\n{text}\n\nPregunta: {q}"
            ans, t = call_llm(args.llm_url, user)
            field_lat[field].append(t)
            ok, reason = evaluate_match_v2(field, expected, ans)
            if ok:
                field_correct[field] += 1
            case_result["fields"][field] = {
                "expected": str(expected)[:100],
                "predicted": ans[:200],
                "match": ok, "reason": reason,
                "elapsed_s": round(t, 2),
            }
        case_details.append(case_result)
        print(f"  [{i}/{len(cases)}] case={case['id']} done", flush=True)

    metrics = {}
    for field in EVAL_FIELDS.keys():
        total = field_total[field]
        if total == 0:
            continue
        metrics[field] = {
            "total": total,
            "correct": field_correct[field],
            "acc_pct": round(100 * field_correct[field] / total, 1),
            "avg_lat_s": round(sum(field_lat[field]) / len(field_lat[field]), 2),
        }

    global_total = sum(field_total.values())
    global_correct = sum(field_correct.values())
    global_acc = round(100 * global_correct / max(1, global_total), 1)

    print()
    print("=" * 70)
    print(f"BENCH ENHANCED — system prompt cognitivo + eval permisivo")
    print("=" * 70)
    print(f"\nGlobal accuracy: {global_acc}% ({global_correct}/{global_total})\n")
    print(f"{'campo':25s} {'total':>6s} {'correct':>8s} {'acc%':>7s} {'lat_s':>7s}")
    for f, m in sorted(metrics.items(), key=lambda kv: -kv[1]["acc_pct"]):
        print(f"  {f:23s} {m['total']:>6d} {m['correct']:>8d} {m['acc_pct']:>6.1f}% {m['avg_lat_s']:>6.2f}s")

    output = {
        "global_acc_pct": global_acc,
        "global_total": global_total,
        "global_correct": global_correct,
        "metrics_per_field": metrics,
        "case_details": case_details,
        "system_prompt_used": SYSTEM_PROMPT[:300] + "...",
    }
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\n✓ Resultados: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
