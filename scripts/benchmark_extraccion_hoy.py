#!/usr/bin/env python3
"""Benchmark de extracción v9 sobre los casos tocados hoy (Local Qwen vs estado actual).

Mide, por caso: campos llenos ANTES y DESPUÉS, campos nuevos, llamadas LLM, tiempo.
NO pisa nada (persist solo rellena vacíos). Total al final.

Uso:
    ./venv/bin/python3 scripts/benchmark_extraccion_hoy.py            # use_llm=True (Qwen local)
    ./venv/bin/python3 scripts/benchmark_extraccion_hoy.py --no-llm   # determinista
"""
from __future__ import annotations
import argparse, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal
from backend.database.models import Case, Email
from backend.v9.pipeline import extract_case

# Campos del cuadro que cuentan para "llenos"
FIELDS = ["radicado_23_digitos","radicado_forest","accionante","accionados","vinculados",
          "derecho_vulnerado","juzgado","ciudad","fecha_ingreso","asunto","pretensiones",
          "oficina_responsable","abogado_responsable","estado","fecha_respuesta",
          "sentido_fallo_1st","fecha_fallo_1st","impugnacion","quien_impugno",
          "juzgado_2nd","sentido_fallo_2nd","fecha_fallo_2nd","incidente",
          "fecha_apertura_incidente","decision_incidente","responsable_desacato","observaciones"]

def filled(case):
    return sum(1 for f in FIELDS if getattr(case, f, None))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true")
    args = ap.parse_args()
    use_llm = not args.no_llm

    db = SessionLocal()
    # casos con email procesado hoy
    ids = sorted({r[0] for r in db.query(Email.case_id).filter(
        Email.processed_at >= __import__("datetime").datetime.now() - __import__("datetime").timedelta(days=1),
        Email.case_id.isnot(None)).all()})
    print(f"Casos tocados hoy: {len(ids)} | motor: {'Qwen local (use_llm=True)' if use_llm else 'determinista'}\n")
    print(f"{'#':>5} {'antes':>5} {'desp':>5} {'+nuevos':>7} {'llm':>4} {'seg':>6}  caso")
    tot_before=tot_after=tot_new=tot_llm=0; t0=time.perf_counter()
    rows=[]
    for cid in ids:
        c = db.query(Case).filter(Case.id==cid).first()
        if not c: continue
        before = filled(c)
        t=time.perf_counter()
        res = extract_case(db, cid, dry_run=False, use_llm=use_llm)
        dt=time.perf_counter()-t
        db.refresh(c)
        after = filled(c)
        new = after - before
        tot_before+=before; tot_after+=after; tot_new+=max(0,new); tot_llm+=res.llm_calls
        rows.append((cid, before, after, new, res.llm_calls, dt, (c.folder_name or "")[:38]))
        print(f"{cid:>5} {before:>5} {after:>5} {new:>+7} {res.llm_calls:>4} {dt:>6.1f}  {(c.folder_name or '')[:38]}")
    total_t=time.perf_counter()-t0
    print("\n" + "="*60)
    print(f"  TOTAL: {len(rows)} casos")
    print(f"  Campos llenos: {tot_before} → {tot_after}  (+{tot_after-tot_before} netos, +{tot_new} acumulados)")
    print(f"  Llamadas LLM totales: {tot_llm}")
    print(f"  Tiempo total: {total_t:.1f}s  ({total_t/max(1,len(rows)):.1f}s/caso)")
    print(f"  Casos que ganaron ≥1 campo: {sum(1 for r in rows if r[3]>0)}")
    db.close()

if __name__ == "__main__":
    raise SystemExit(main())
