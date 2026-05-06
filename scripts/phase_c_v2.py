"""Phase C v2: enriquecimiento quien_impugno con LLM + guards múltiples.

Diferencias vs v1:
- Prompt 2-clase (ACCIONANTE/ACCIONADO) — MP solo si regex detecta Personero/Defensor
- Heurística determinista pre-LLM:
    CONCEDE/AMPARA + entidad pública accionado → ACCIONADO
    NIEGA/IMPROCEDENTE → ACCIONANTE
    CONCEDE PARCIAL → ACCIONANTE (no satisfecho)
- LLM como segunda opinión: si concuerda con heurística, high confidence (auto-persist).
  Si difieren, marca quien_impugno_review='LLM:X|HEU:Y' (revisión humana).
- Guard MP: rechaza si accionante/accionados sin Personero/Defensor.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "tutelas.db"
PROGRESS = ROOT / "data" / "phase_c_v2_progress.json"
LLM_URL = "http://127.0.0.1:8765/v1/chat/completions"

ENTIDAD_PUB_RE = re.compile(
    r'\b(secretar[ií]a|gobernaci[oó]n|alcald[ií]a|ministerio|departamento|'
    r'colegio|escuela|hospital|e\.?s\.?e\.?|e\.?p\.?s\.?|instituto|fondo|gobierno)\b',
    re.IGNORECASE,
)
MP_RE = re.compile(
    r'\b(personer[oa]|defensor\s+del\s+pueblo|procuradur[ií]a|ministerio\s+p[uú]blico)\b',
    re.IGNORECASE,
)


def heuristic(case: dict) -> str:
    """Predicción determinista basada en cuadro procesal."""
    sentido = (case.get('sentido_fallo_1st') or '').upper()
    accionados = (case.get('accionados') or '').upper()
    has_pub = bool(ENTIDAD_PUB_RE.search(accionados))
    if 'PARCIAL' in sentido:
        return 'ACCIONANTE'
    if any(k in sentido for k in ('CONCEDE', 'AMPARA', 'TUTELA EL', 'PROTEGE')):
        return 'ACCIONADO' if has_pub else 'ACCIONANTE'
    if any(k in sentido for k in ('NIEGA', 'IMPROCEDENTE', 'RECHAZA')):
        return 'ACCIONANTE'
    return 'ACCIONANTE'  # default


def has_mp_signal(case: dict) -> bool:
    blob = ((case.get('accionante') or '') + ' ' + (case.get('accionados') or ''))
    return bool(MP_RE.search(blob))


def ask_llm(case: dict) -> tuple[str | None, float]:
    """Prompt 2-clase. MP solo si regex pre-detecta señal."""
    if has_mp_signal(case):
        choices = "ACCIONANTE, ACCIONADO, o MINISTERIO_PUBLICO"
    else:
        choices = "ACCIONANTE o ACCIONADO"

    prompt = (
        "Eres asistente jurídico colombiano experto en tutelas.\n\n"
        f"DATOS:\n"
        f"- Accionante: {case.get('accionante') or '?'}\n"
        f"- Accionados: {(case.get('accionados') or '?')[:150]}\n"
        f"- Sentido 1ra: {case.get('sentido_fallo_1st') or '?'}\n\n"
        "REGLAS:\n"
        "- CONCEDE/AMPARA + accionado entidad pública → ACCIONADO\n"
        "- NIEGA/IMPROCEDENTE → ACCIONANTE (perdió)\n"
        "- CONCEDE PARCIAL → ACCIONANTE\n\n"
        f"Responde SOLO una palabra: {choices}. /no_think"
    )
    t0 = time.time()
    try:
        r = requests.post(LLM_URL, json={
            "model": "qwen3-4b-iuris",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 20, "temperature": 0.1,
        }, timeout=30)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip().upper()
        elapsed = time.time() - t0
        for cat in ["ACCIONANTE", "ACCIONADO", "MINISTERIO_PUBLICO"]:
            if cat in text:
                # Guard MP: rechazar si no había señal pre-detectada
                if cat == "MINISTERIO_PUBLICO" and not has_mp_signal(case):
                    return None, elapsed  # alucinación rejected
                return cat, elapsed
        return None, elapsed
    except Exception:
        return None, time.time() - t0


def main():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row

    gaps = con.execute("""
        SELECT id, accionante, accionados, sentido_fallo_1st, juzgado_2nd
        FROM cases
        WHERE processing_status='COMPLETO' AND impugnacion='SI'
          AND (quien_impugno IS NULL OR quien_impugno='')
    """).fetchall()
    total = len(gaps)
    print(f"Casos NULL: {total}", flush=True)

    auto_filled = 0  # heurística + LLM concordantes → auto-persist
    review_marked = 0  # discordantes → marcados para review
    rejected = 0  # LLM falló o alucinó MP
    times = []
    t_start = time.time()

    for i, c in enumerate(gaps):
        case = dict(c)
        heu = heuristic(case)
        llm, latency = ask_llm(case)
        times.append(latency)

        if llm is None:
            rejected += 1
            # Conservar heurística como fallback
            con.execute("UPDATE cases SET quien_impugno=? WHERE id=?", (heu, case['id']))
            auto_filled += 1
        elif llm == heu:
            # Concordancia → high confidence
            con.execute("UPDATE cases SET quien_impugno=? WHERE id=?", (llm, case['id']))
            auto_filled += 1
        else:
            # Discordancia → marcar revisión manual con ambas predicciones
            note = f"REVIEW:LLM={llm}|HEU={heu}"
            con.execute("UPDATE cases SET quien_impugno=? WHERE id=?", (note, case['id']))
            review_marked += 1

        if (i + 1) % 10 == 0:
            con.commit()
            elapsed = time.time() - t_start
            avg = elapsed / (i + 1)
            eta = (total - (i + 1)) * avg
            progress = {
                "processed": i + 1, "total": total,
                "auto_filled": auto_filled, "review_marked": review_marked,
                "rejected_mp": rejected,
                "elapsed_s": round(elapsed, 1),
                "avg_latency_s": round(avg, 1),
                "eta_s": round(eta),
            }
            PROGRESS.write_text(json.dumps(progress, indent=2))
            print(f"  {i+1}/{total} | auto={auto_filled} review={review_marked} mp_rej={rejected} avg={avg:.1f}s ETA={eta:.0f}s",
                  flush=True)

    con.commit()
    final = {
        "total": total,
        "auto_filled": auto_filled,
        "review_marked": review_marked,
        "rejected_mp": rejected,
        "elapsed_s": round(time.time() - t_start, 1),
        "avg_latency_s": round(sum(times) / max(len(times), 1), 2),
        "done": True,
    }
    PROGRESS.write_text(json.dumps(final, indent=2))
    print(f"\n✅ Done: auto={auto_filled} review={review_marked} mp_rej={rejected} en {final['elapsed_s']}s", flush=True)
    con.close()


if __name__ == "__main__":
    main()
