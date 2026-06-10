"""Valida V9_LLM_SINGLE_CALL: corre cada caso en modo por-campo (OFF) y single-call (ON),
en dry_run (no persiste), y compara campos semánticos + nº llamadas LLM reales + tiempo.

Uso:  V9_DISABLE_LLM=false venv/bin/python3 scripts/validate_single_call.py
"""
import os, sys, time, glob, re

os.environ.setdefault("V9_DISABLE_LLM", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database.database import SessionLocal
from backend.v9.pipeline import extract_case
from backend.services import llm_mutex

CASES = [492, 487, 486, 482, 488, 483]  # sin casos OCR-pesados (485)
FIELDS = ["derecho_vulnerado", "asunto", "pretensiones"]


def _server_prompt_count() -> int:
    """nº de 'prompt processing done' en el log más reciente del llama-server."""
    logs = sorted(glob.glob("logs/llama_server_*.log"), key=os.path.getmtime)
    if not logs:
        return 0
    try:
        with open(logs[-1], errors="ignore") as f:
            return len(re.findall(r"prompt processing done", f.read()))
    except Exception:
        return 0


def run_mode(case_id: int, single: bool) -> dict:
    os.environ["V9_LLM_SINGLE_CALL"] = "true" if single else "false"
    llm_mutex.ensure_llm_up(wait_s=90)  # respawn si el server crasheó (DeviceLost)
    db = SessionLocal()
    try:
        before = _server_prompt_count()
        t = time.time()
        res = extract_case(db, case_id, dry_run=True, use_llm=True)
        elapsed = time.time() - t
        after = _server_prompt_count()
        vals = {f: (res.fields.values.get(f) or "")[:60] for f in FIELDS}
        return {"calls": after - before, "secs": round(elapsed, 1), "vals": vals}
    finally:
        db.close()


def _existing_cases(case_ids):
    """Filtra ids que ya no existen (borrados/fusionados en curación) — 2026-06-10:
    c487 desapareció y el run completo moría a mitad de camino."""
    from backend.database.models import Case
    db = SessionLocal()
    try:
        keep = [c for c in case_ids if db.get(Case, c) is not None]
    finally:
        db.close()
    gone = sorted(set(case_ids) - set(keep))
    if gone:
        print(f"(aviso: casos inexistentes omitidos: {gone})")
    return keep


def main():
    print("Encendiendo motor (GPU 1250)…")
    llm_mutex.ensure_llm_up(wait_s=90)
    cases = _existing_cases(CASES)
    print(f"{'='*78}\nVALIDACIÓN V9_LLM_SINGLE_CALL — {len(cases)} casos\n{'='*78}")
    tot_off_s = tot_on_s = tot_off_c = tot_on_c = 0
    mism = 0
    for cid in cases:
        off = run_mode(cid, single=False)
        on = run_mode(cid, single=True)
        tot_off_s += off["secs"]; tot_on_s += on["secs"]
        tot_off_c += off["calls"]; tot_on_c += on["calls"]
        print(f"\n── caso {cid} ──")
        print(f"  POR-CAMPO  : {off['calls']} llamadas · {off['secs']}s")
        print(f"  SINGLE-CALL: {on['calls']} llamadas · {on['secs']}s")
        for f in FIELDS:
            a, b = off["vals"][f], on["vals"][f]
            ok = "✓" if a == b else ("≈" if (a and b) else "✗")
            if a != b:
                mism += 1
            print(f"     {ok} {f:18} OFF={a!r:42} ON={b!r}")
    print(f"\n{'='*78}\nTOTALES")
    print(f"  Llamadas LLM: por-campo={tot_off_c}  single-call={tot_on_c}")
    print(f"  Tiempo total: por-campo={round(tot_off_s,1)}s  single-call={round(tot_on_s,1)}s")
    if tot_on_s:
        print(f"  Speedup: {round(tot_off_s/max(tot_on_s,0.1),2)}×")
    print(f"  Campos distintos (revisar manualmente): {mism}/{len(CASES)*len(FIELDS)}")


if __name__ == "__main__":
    main()
