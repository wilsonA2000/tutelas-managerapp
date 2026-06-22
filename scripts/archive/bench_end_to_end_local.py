"""IURIS — Bench end-to-end del LLM Compilador local.

Simula el flujo real de producción:
1. Selecciona N casos COMPLETO con los campos ya extraídos por las capas 0-5
2. Por cada caso, esconde 2-3 campos al azar (simulando huecos)
3. Construye JSON de insumos consolidados (formato real del system prompt)
4. POST a llama-server con system prompt PRODUCCIÓN
5. Compara los huecos llenos por LLM vs ground truth de la DB
6. Reporta: cobertura por campo, latencia, alucinaciones (% campos inventados)

Uso:
  python3 scripts/bench_end_to_end_local.py --n-cases 30
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "tutelas.db"
PROMPT_PATH = ROOT / "docs" / "iuris" / "SYSTEM_PROMPT_COMPILER.md"
RESULTS_PATH = ROOT / "data" / "bench_e2e_local_results.json"

LLM_URL = "http://127.0.0.1:8765"

# Campos que el LLM puede ser pedido para llenar (semánticos + clasificatorios)
HUECOS_CANDIDATOS = [
    "categoria_tematica", "observaciones", "derecho_vulnerado",
    "quien_impugno", "decision_incidente",
]

# Campos siempre incluidos como contexto extraído (lo que ya hizo el pipeline)
CONTEXTO_CAMPOS = [
    "accionante", "juzgado", "ciudad", "fecha_ingreso",
    "sentido_fallo_1st", "fecha_fallo_1st", "impugnacion",
    "asunto", "pretensiones", "incidente",
    "responsable_desacato", "fecha_apertura_incidente",
]


def load_system_prompt() -> str:
    """Carga la Versión PRODUCCIÓN del system prompt."""
    md = PROMPT_PATH.read_text(encoding="utf-8")
    m = re.search(r"## Versión PRODUCCIÓN.*?```\n(.*?)```", md, re.DOTALL)
    return m.group(1).strip() if m else ""


def select_cases(conn: sqlite3.Connection, n: int) -> list[dict]:
    """Selecciona N casos COMPLETO con suficientes campos llenos para simular huecos."""
    rows = conn.execute("""
        SELECT id, accionante, juzgado, ciudad, fecha_ingreso,
               sentido_fallo_1st, fecha_fallo_1st, impugnacion,
               quien_impugno, asunto, pretensiones, incidente,
               responsable_desacato, fecha_apertura_incidente,
               categoria_tematica, observaciones, derecho_vulnerado,
               decision_incidente
        FROM cases
        WHERE processing_status = 'COMPLETO'
          AND categoria_tematica IS NOT NULL AND categoria_tematica != ''
          AND derecho_vulnerado IS NOT NULL AND derecho_vulnerado != ''
          AND observaciones IS NOT NULL AND observaciones != ''
        ORDER BY id
        LIMIT ?
    """, (n,)).fetchall()
    out = []
    for r in rows:
        case = dict(zip([
            "id", "accionante", "juzgado", "ciudad", "fecha_ingreso",
            "sentido_fallo_1st", "fecha_fallo_1st", "impugnacion",
            "quien_impugno", "asunto", "pretensiones", "incidente",
            "responsable_desacato", "fecha_apertura_incidente",
            "categoria_tematica", "observaciones", "derecho_vulnerado",
            "decision_incidente",
        ], r))
        out.append(case)
    return out


def build_insumos(case: dict, huecos: list[str]) -> dict:
    """Construye JSON de insumos consolidados (lo que el pipeline real le pasaría)."""
    extraidos = {}
    for f in CONTEXTO_CAMPOS:
        v = case.get(f)
        if v:
            extraidos[f] = {"value": str(v)[:200], "source": "pipeline_v6", "confidence": 0.9}

    # Texto evidencia: concatenar asunto + pretensiones + observaciones (sin spoilers)
    evidencia_parts = []
    for f in ("asunto", "pretensiones"):
        v = case.get(f)
        if v:
            evidencia_parts.append(f"{f.upper()}: {str(v)[:300]}")
    evidencia = " | ".join(evidencia_parts)

    return {
        "campos_extraidos": extraidos,
        "campos_huecos": huecos,
        "evidencia_textual": evidencia[:1500],
        "metadata": {
            "tipo_doc": "consolidado",
            "tiene_incidente": (case.get("incidente") or "").upper() in ("SI", "SÍ"),
            "tiene_impugnacion": (case.get("impugnacion") or "").upper() in ("SI", "SÍ"),
        },
    }


def call_compiler(sys_prompt: str, insumos: dict, timeout: int = 180) -> tuple[dict | None, float, str]:
    """POST al llama-server. Retorna (json_parsed, latencia_s, raw_text)."""
    payload = {
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": json.dumps(insumos, ensure_ascii=False)},
        ],
        "temperature": 0.1,
        "max_tokens": 400,
    }
    t0 = time.time()
    try:
        r = requests.post(f"{LLM_URL}/v1/chat/completions", json=payload, timeout=timeout)
        elapsed = time.time() - t0
        if r.status_code != 200:
            return None, elapsed, f"<HTTP {r.status_code}>"
        text = r.json()["choices"][0]["message"]["content"]
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        text_clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
        try:
            parsed = json.loads(text_clean)
            return parsed, elapsed, text
        except json.JSONDecodeError:
            return None, elapsed, text
    except Exception as e:
        return None, time.time() - t0, f"<ERROR: {e}>"


def evaluate_match(field: str, expected: str | None, predicted: str) -> bool:
    """Eval permisivo: matching por palabras significativas."""
    if not expected:
        return predicted.strip() == "" or predicted is None
    if not predicted:
        return False
    exp = str(expected).strip().upper()
    pred = str(predicted).strip().upper()
    # Enums
    if field in ("quien_impugno", "impugnacion", "incidente",
                  "sentido_fallo_1st", "sentido_fallo_2nd"):
        return exp in pred or pred in exp
    # Texto: matching por palabras significativas (≥50% solapamiento)
    stop = {"DE", "LA", "EL", "LOS", "LAS", "Y", "O", "A", "EN"}
    exp_words = {w for w in re.findall(r"\w+", exp) if len(w) >= 3 and w not in stop}
    pred_words = {w for w in re.findall(r"\w+", pred) if len(w) >= 3 and w not in stop}
    if not exp_words:
        return False
    overlap = exp_words & pred_words
    return len(overlap) / len(exp_words) >= 0.4


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-cases", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    random.seed(args.seed)

    print("→ Cargando system prompt...", flush=True)
    sys_prompt = load_system_prompt()
    print(f"  {len(sys_prompt)} chars", flush=True)

    conn = sqlite3.connect(str(DB_PATH))
    cases = select_cases(conn, args.n_cases)
    print(f"→ {len(cases)} casos seleccionados", flush=True)

    field_correct = Counter()
    field_total = Counter()
    field_lat = defaultdict(list)
    field_alucinaciones = Counter()  # campos NO pedidos pero devueltos
    case_details = []

    for i, case in enumerate(cases, 1):
        # Seleccionar 2 huecos al azar (campos que SÍ tienen valor en DB)
        candidatos = [f for f in HUECOS_CANDIDATOS if case.get(f)]
        if len(candidatos) < 2:
            continue
        huecos = random.sample(candidatos, k=min(2, len(candidatos)))

        insumos = build_insumos(case, huecos)
        parsed, elapsed, raw = call_compiler(sys_prompt, insumos)

        case_result = {"case_id": case["id"], "huecos_pedidos": huecos,
                       "elapsed_s": round(elapsed, 2)}

        if parsed is None:
            case_result["status"] = "json_invalid"
            case_result["raw"] = raw[:200]
            case_details.append(case_result)
            print(f"  [{i}/{len(cases)}] case={case['id']} ✗ JSON inválido", flush=True)
            continue

        # Evaluar cada hueco
        case_result["status"] = "ok"
        case_result["fields"] = {}
        for hueco in huecos:
            field_total[hueco] += 1
            field_lat[hueco].append(elapsed / len(huecos))
            expected = case.get(hueco)
            predicted = parsed.get(hueco, "")
            match = evaluate_match(hueco, expected, str(predicted))
            if match:
                field_correct[hueco] += 1
            case_result["fields"][hueco] = {
                "expected": str(expected)[:100],
                "predicted": str(predicted)[:120],
                "match": match,
            }

        # Detectar alucinaciones: campos en el output que NO estaban pedidos
        for k in parsed.keys():
            if k not in huecos and not k.startswith("_"):
                field_alucinaciones[k] += 1

        case_details.append(case_result)
        print(f"  [{i}/{len(cases)}] case={case['id']} {elapsed:.1f}s "
              f"hits={sum(case_result['fields'][h]['match'] for h in huecos)}/{len(huecos)}",
              flush=True)

    # Reporte
    print("\n" + "=" * 70)
    print("BENCH END-TO-END LOCAL — Resultados")
    print("=" * 70)
    total_q = sum(field_total.values())
    total_ok = sum(field_correct.values())
    print(f"\nGlobal accuracy: {round(100 * total_ok / max(1, total_q), 1)}% "
          f"({total_ok}/{total_q})\n")
    print(f"{'campo':25s} {'total':>6s} {'OK':>4s} {'acc%':>6s} {'lat':>6s}")
    for f in HUECOS_CANDIDATOS:
        if field_total[f] == 0:
            continue
        acc = round(100 * field_correct[f] / field_total[f], 1)
        lat = round(sum(field_lat[f]) / len(field_lat[f]), 2) if field_lat[f] else 0
        print(f"  {f:23s} {field_total[f]:>6d} {field_correct[f]:>4d} "
              f"{acc:>5.1f}% {lat:>5.1f}s")

    if field_alucinaciones:
        print(f"\n⚠️  Alucinaciones (campos extra devueltos):")
        for k, c in field_alucinaciones.most_common(10):
            print(f"  {k}: {c} casos")

    out = {
        "n_cases": len(cases),
        "global_acc_pct": round(100 * total_ok / max(1, total_q), 1),
        "global_total": total_q,
        "global_correct": total_ok,
        "field_metrics": {
            f: {"total": field_total[f], "correct": field_correct[f],
                "acc_pct": round(100 * field_correct[f] / max(1, field_total[f]), 1),
                "avg_lat_s": round(sum(field_lat[f]) / max(1, len(field_lat[f])), 2)}
            for f in HUECOS_CANDIDATOS if field_total[f] > 0
        },
        "alucinaciones": dict(field_alucinaciones),
        "case_details": case_details[:50],
    }
    RESULTS_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n✓ Resultados: {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
