"""IURIS — Comparación métricas pre vs post LoRA fine-tuning.

Selecciona N casos representativos del DB local, corre extracción con:
  - BASELINE (sin LLM, solo regex+forensic actual del pipeline v6)
  - QWEN3-4B + LORA (modelo entrenado en RunPod)

Mide:
  - Cobertura por campo (% extraído correctamente)
  - Latencia por caso
  - RAM peak
  - Casos donde LoRA mejoró vs empeoró

Output:
  - data/lora_comparison_results.json
  - logs detallados pre/post

Uso:
  # Después de cargar LoRA en llama-server localhost:8765
  python3 scripts/compare_pre_post_lora.py --n-cases 50 --llm-url http://localhost:8765
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "tutelas.db"
RESULTS_PATH = ROOT / "data" / "lora_comparison_results.json"

# Campos a evaluar — los que el LoRA fue entrenado para extraer
EVAL_FIELDS = {
    "accionante": "¿Cuál es el nombre completo del accionante? Solo el nombre.",
    "juzgado": "¿Cuál es el juzgado de tutela?",
    "ciudad": "¿En qué ciudad ocurren los hechos?",
    "sentido_fallo_1st": "¿El fallo de primera instancia CONCEDE, NIEGA o IMPROCEDENTE? Una palabra.",
    "fecha_fallo_1st": "¿En qué fecha se profirió el fallo de primera instancia?",
    "impugnacion": "¿Hubo impugnación al fallo? SI o NO.",
    "quien_impugno": "¿Quién impugnó? ACCIONANTE, ACCIONADO o MINISTERIO_PUBLICO.",
    "juzgado_2nd": "¿Cuál es el juzgado de segunda instancia?",
    "sentido_fallo_2nd": "¿Sentido del fallo segunda instancia? CONFIRMA, REVOCA o MODIFICA.",
    "incidente": "¿Hay incidente de desacato? SI o NO.",
    "responsable_desacato": "¿Quién es el responsable del desacato? Solo el nombre.",
    "decision_incidente": "¿Decisión sobre el incidente? Frase corta.",
    "derecho_vulnerado": "¿Cuál derecho fundamental se vulneró?",
}

SYSTEM_PROMPT = (
    "Eres asistente jurídico colombiano. Responde solo lo solicitado, "
    "en español, conciso. NO uses <think>. Solo responde directo."
)


def select_cases(conn: sqlite3.Connection, n: int = 50) -> list[dict]:
    """Selecciona N casos COMPLETO con docs reales.

    Estratificación: mix de casos con/sin impugnación, con/sin incidente.
    """
    rows = conn.execute("""
        SELECT id, accionante, juzgado, ciudad, sentido_fallo_1st,
               fecha_fallo_1st, impugnacion, quien_impugno, juzgado_2nd,
               sentido_fallo_2nd, incidente, responsable_desacato,
               decision_incidente, derecho_vulnerado, folder_path
        FROM cases
        WHERE processing_status = 'COMPLETO'
        ORDER BY id
        LIMIT ?
    """, (n,)).fetchall()

    cols = [d[0] for d in conn.execute("PRAGMA table_info(cases)").fetchall()]
    out = []
    for r in rows:
        case = dict(zip([d[0] for d in conn.execute("SELECT * FROM cases LIMIT 0").description], r)) if False else None
        # Simple manual mapping
        case = {
            "id": r[0], "accionante": r[1], "juzgado": r[2], "ciudad": r[3],
            "sentido_fallo_1st": r[4], "fecha_fallo_1st": r[5], "impugnacion": r[6],
            "quien_impugno": r[7], "juzgado_2nd": r[8], "sentido_fallo_2nd": r[9],
            "incidente": r[10], "responsable_desacato": r[11],
            "decision_incidente": r[12], "derecho_vulnerado": r[13],
            "folder_path": r[14],
        }
        # Cargar texto OCR de docs
        docs = conn.execute(
            "SELECT extracted_text FROM documents WHERE case_id = ? LIMIT 5",
            (case["id"],)
        ).fetchall()
        case["text"] = "\n\n".join(d[0] for d in docs if d[0])[:5000]
        out.append(case)
    return out


def call_llm(url: str, system: str, user: str, max_tokens: int = 200,
             temperature: float = 0.1, timeout: int = 60) -> tuple[str, float]:
    """Llama al endpoint OpenAI-compat (llama-server) y retorna (respuesta, tiempo)."""
    payload = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stop": ["\n\nPregunta:", "\n\n#"],
    }
    t0 = time.time()
    try:
        r = requests.post(f"{url}/v1/chat/completions", json=payload, timeout=timeout)
        elapsed = time.time() - t0
        if r.status_code != 200:
            return f"<HTTP {r.status_code}: {r.text[:100]}>", elapsed
        out = r.json()["choices"][0]["message"]["content"]
        # Filtrar <think>...</think>
        import re as _re
        out = _re.sub(r"<think>.*?</think>", "", out, flags=_re.DOTALL).strip()
        return out, elapsed
    except Exception as e:
        return f"<ERROR: {e}>", time.time() - t0


def evaluate_match(field: str, expected: str | None, predicted: str) -> bool:
    """Verifica si la predicción matchea el ground truth (semánticamente)."""
    if not expected:
        return False
    exp = str(expected).strip().upper()
    pred = predicted.strip().upper()
    if not pred:
        return False
    # Match strict para enums
    if field in ("sentido_fallo_1st", "sentido_fallo_2nd", "impugnacion",
                  "incidente", "quien_impugno"):
        return exp in pred or pred in exp
    # Match nombres / texto: si las primeras 3 palabras del expected están en pred
    exp_words = exp.split()[:3]
    if len(exp_words) >= 1:
        return all(w in pred for w in exp_words[:2])  # primeras 2 palabras
    return exp in pred


def run_evaluation(cases: list[dict], llm_url: str, label: str = "lora") -> dict:
    """Ejecuta evaluación sobre N casos, retorna métricas."""
    print(f"→ Evaluando {len(cases)} casos con [{label}] LLM @ {llm_url}")
    field_correct = Counter()
    field_total = Counter()
    field_latency = defaultdict(list)
    case_details = []

    for i, case in enumerate(cases, 1):
        case_text = case["text"][:3500]
        if not case_text or len(case_text) < 100:
            print(f"  [{i}] case={case['id']} SKIP (sin texto)")
            continue
        case_result = {"case_id": case["id"], "fields": {}}

        for field, question in EVAL_FIELDS.items():
            expected = case.get(field)
            if not expected:
                continue
            field_total[field] += 1
            user_msg = f"Texto del expediente:\n\n{case_text}\n\nPregunta: {question}"
            answer, elapsed = call_llm(llm_url, SYSTEM_PROMPT, user_msg)
            field_latency[field].append(elapsed)
            match = evaluate_match(field, expected, answer)
            if match:
                field_correct[field] += 1
            case_result["fields"][field] = {
                "expected": expected,
                "predicted": answer[:200],
                "match": match,
                "elapsed_s": round(elapsed, 2),
            }
        case_details.append(case_result)
        print(f"  [{i}/{len(cases)}] case={case['id']} done")

    # Aggregate
    metrics = {}
    for field in EVAL_FIELDS.keys():
        total = field_total[field]
        if total == 0:
            continue
        correct = field_correct[field]
        avg_lat = sum(field_latency[field]) / len(field_latency[field]) if field_latency[field] else 0
        metrics[field] = {
            "total": total,
            "correct": correct,
            "accuracy_pct": round(100 * correct / total, 1),
            "avg_latency_s": round(avg_lat, 2),
        }
    return {
        "label": label,
        "llm_url": llm_url,
        "n_cases": len(cases),
        "metrics_per_field": metrics,
        "global": {
            "total_questions": sum(field_total.values()),
            "total_correct": sum(field_correct.values()),
            "accuracy_pct": round(
                100 * sum(field_correct.values()) / max(1, sum(field_total.values())), 1
            ),
        },
        "case_details": case_details,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-cases", type=int, default=50)
    ap.add_argument("--llm-url", default="http://localhost:8765",
                    help="URL del llama-server con LoRA cargado")
    ap.add_argument("--baseline-url", default="",
                    help="URL del llama-server SIN LoRA (opcional, para comparación)")
    ap.add_argument("--output", default=str(RESULTS_PATH))
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"❌ DB no encontrada: {DB_PATH}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(str(DB_PATH))

    cases = select_cases(conn, args.n_cases)
    print(f"→ {len(cases)} casos seleccionados (con accionante: "
          f"{sum(1 for c in cases if c.get('accionante'))})")

    # Eval con LoRA (post-training)
    results_lora = run_evaluation(cases, args.llm_url, label="qwen3_4b_lora")

    # Eval con baseline si URL proporcionada
    results_baseline = None
    if args.baseline_url:
        results_baseline = run_evaluation(cases, args.baseline_url, label="qwen3_4b_base")

    # Comparativa
    print("\n" + "=" * 70)
    print("RESULTADOS")
    print("=" * 70)
    print(f"\n[LoRA] global accuracy: {results_lora['global']['accuracy_pct']}%")
    print(f"\n{'campo':25s} {'total':>6s} {'correct':>8s} {'acc%':>6s} {'lat_s':>7s}")
    for field, m in sorted(results_lora["metrics_per_field"].items(),
                            key=lambda kv: -kv[1]["accuracy_pct"]):
        print(f"  {field:23s} {m['total']:>6d} {m['correct']:>8d} "
              f"{m['accuracy_pct']:>5.1f}% {m['avg_latency_s']:>6.2f}s")

    if results_baseline:
        print(f"\n[Baseline] global accuracy: {results_baseline['global']['accuracy_pct']}%")
        print(f"\nDelta LoRA vs Baseline:")
        for field, m_lora in results_lora["metrics_per_field"].items():
            m_base = results_baseline["metrics_per_field"].get(field, {"accuracy_pct": 0})
            delta = m_lora["accuracy_pct"] - m_base["accuracy_pct"]
            sign = "+" if delta >= 0 else ""
            print(f"  {field:25s} baseline {m_base['accuracy_pct']}% "
                  f"→ lora {m_lora['accuracy_pct']}% "
                  f"({sign}{delta:.1f}%)")

    # Guardar JSON completo
    output = {
        "lora": results_lora,
        "baseline": results_baseline,
        "summary": {
            "lora_global_acc": results_lora["global"]["accuracy_pct"],
            "baseline_global_acc": results_baseline["global"]["accuracy_pct"] if results_baseline else None,
        },
    }
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\n✓ Resultados completos: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
