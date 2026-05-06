"""Phase C: enriquece quien_impugno con LLM cuantizado.

Procesa casos donde:
  - processing_status='COMPLETO'
  - impugnacion='SI'
  - quien_impugno vacío o no-categórico

Llama directo al llama-server :8765 con prompt minimalista.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "tutelas.db"
PROGRESS = ROOT / "data" / "phase_c_progress.json"

LLM_URL = "http://127.0.0.1:8765/v1/chat/completions"


def ask_llm(case: dict) -> tuple[str | None, float]:
    """Retorna (categoria, latencia_s)."""
    prompt = (
        "Eres un asistente jurídico colombiano experto en tutelas. Identifica QUIÉN impugnó "
        "el fallo de primera instancia.\n\n"
        f"Datos:\n"
        f"- Accionante: {case['accionante'] or '?'}\n"
        f"- Accionados: {(case['accionados'] or '?')[:200]}\n"
        f"- Sentido fallo 1ra: {case['sentido_fallo_1st'] or '?'}\n"
        f"- Juzgado 2da: {case['juzgado_2nd'] or '?'}\n\n"
        "REGLAS:\n"
        "- CONCEDE/AMPARA + entidad pública accionada → ACCIONADO\n"
        "- NIEGA/IMPROCEDENTE → ACCIONANTE (perdió)\n"
        "- CONCEDE PARCIAL → ACCIONANTE (no conforme)\n"
        "- Personero/Defensor → MINISTERIO_PUBLICO\n\n"
        "Responde SOLO con UNA palabra: ACCIONANTE, ACCIONADO, o MINISTERIO_PUBLICO."
    )
    t0 = time.time()
    try:
        r = requests.post(LLM_URL, json={
            "model": "qwen3-4b-iuris",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 30, "temperature": 0.1,
        }, timeout=30)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
        elapsed = time.time() - t0
        for cat in ["ACCIONANTE", "ACCIONADO", "MINISTERIO_PUBLICO"]:
            if cat in text.upper():
                return cat, elapsed
        return None, elapsed
    except Exception as e:
        return None, time.time() - t0


def main():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    gaps = con.execute("""
        SELECT id, folder_name, accionante, accionados, sentido_fallo_1st, juzgado_2nd
        FROM cases
        WHERE processing_status='COMPLETO' AND impugnacion='SI'
          AND (quien_impugno IS NULL OR quien_impugno=''
               OR quien_impugno NOT IN ('ACCIONANTE','ACCIONADO','MINISTERIO_PUBLICO'))
    """).fetchall()
    total = len(gaps)
    print(f"Casos gap: {total}", flush=True)

    filled = 0
    errors = 0
    times = []
    t_start = time.time()

    for i, c in enumerate(gaps):
        cat, latency = ask_llm(dict(c))
        times.append(latency)
        if cat:
            con.execute("UPDATE cases SET quien_impugno=? WHERE id=?", (cat, c["id"]))
            filled += 1
        else:
            errors += 1

        # Commit + progress cada 10
        if (i + 1) % 10 == 0:
            con.commit()
            elapsed = time.time() - t_start
            avg = elapsed / (i + 1)
            eta = (total - (i + 1)) * avg
            progress = {
                "processed": i + 1, "total": total,
                "filled": filled, "errors": errors,
                "elapsed_s": round(elapsed, 1),
                "avg_latency_s": round(avg, 1),
                "eta_s": round(eta),
            }
            PROGRESS.write_text(json.dumps(progress, indent=2))
            print(f"  {i+1}/{total} | filled={filled} errors={errors} avg={avg:.1f}s ETA={eta:.0f}s",
                  flush=True)

    con.commit()
    con.close()

    final = {
        "total": total, "filled": filled, "errors": errors,
        "elapsed_s": round(time.time() - t_start, 1),
        "avg_latency_s": round(sum(times) / max(len(times), 1), 2),
        "done": True,
    }
    PROGRESS.write_text(json.dumps(final, indent=2))
    print(f"\n✅ Done: {filled}/{total} en {final['elapsed_s']}s", flush=True)


if __name__ == "__main__":
    main()
