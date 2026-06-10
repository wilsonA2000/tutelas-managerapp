#!/usr/bin/env python3
"""Compara dos salidas de bakeoff_harness.py (4B vs 30B) lado a lado.

Enfoca el diff en los campos cuya autoridad fue el LLM (donde los modelos
difieren; el determinista da idéntico) + un set de campos semánticos clave.
Marca divergencias y candidatos a revisión humana (un modelo llenó, el otro no).

Uso: python3 scripts/bakeoff_compare.py data/bakeoff_4B.json data/bakeoff_30B.json
"""
from __future__ import annotations
import json, sys
from pathlib import Path

# Campos semánticos que siempre mostramos si difieren (aunque no sean source=llm).
KEY_FIELDS = ["sentido_fallo_1st", "derecho_vulnerado", "asunto", "pretensiones",
              "quien_impugno", "responsable_desacato", "decision_incidente"]


def short(v, n=66):
    s = "" if v is None else str(v)
    s = s.replace("\n", " ").strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def load(p):
    return json.loads(Path(p).read_text())


def main() -> int:
    if len(sys.argv) != 3:
        print("uso: bakeoff_compare.py <a.json> <b.json>"); return 2
    A, B = load(sys.argv[1]), load(sys.argv[2])
    ta, tb = A.get("tag", "A"), B.get("tag", "B")
    print(f"\n{'='*78}\nBAKE-OFF  {ta} ({A.get('model','?')})  vs  {tb} ({B.get('model','?')})\n{'='*78}")

    ca, cb = A["cases"], B["cases"]
    common = sorted(set(ca) & set(cb), key=int)

    n_diff = 0
    review = []  # (cid, field, a_val, b_val) — uno lleno y el otro vacío
    for cid in common:
        a, b = ca[cid], cb[cid]
        if "error" in a or "error" in b:
            print(f"\n● Caso {cid}: ERROR  {ta}={a.get('error','-')}  {tb}={b.get('error','-')}")
            continue
        fa, fb = a.get("fields", {}), b.get("fields", {})
        sa, sb = a.get("sources", {}), b.get("sources", {})
        # Campos a comparar: los que vinieron de LLM en cualquiera + clave que difieran.
        llm_fields = set(a.get("llm_fields", [])) | set(b.get("llm_fields", []))
        cand = sorted(llm_fields | set(KEY_FIELDS))
        diffs = [(f, fa.get(f), fb.get(f), sa.get(f, "-"), sb.get(f, "-"))
                 for f in cand if (fa.get(f) or "") != (fb.get(f) or "")]
        hdr = (f"\n● Caso {cid}  ·  lat {ta}={a['lat_s']}s {tb}={b['lat_s']}s  ·  "
               f"llm_calls {ta}={a.get('llm_calls')} {tb}={b.get('llm_calls')}  ·  "
               f"campos_llm {ta}={a.get('llm_fields')} {tb}={b.get('llm_fields')}")
        if not diffs:
            print(hdr + "  →  (sin divergencias)")
            continue
        print(hdr)
        print(f"   {'campo':<22} {ta:<34} {tb:<34}")
        for f, av, bv, asrc, bsrc in diffs:
            n_diff += 1
            print(f"   {f:<22} {short(av,32)+f' [{asrc}]':<34} {short(bv,32)+f' [{bsrc}]':<34}")
            if bool(av) != bool(bv):
                review.append((cid, f, av, bv))

    # ---- Resumen ----
    def avg_lat(C):
        ls = [c["lat_s"] for c in C.values() if "lat_s" in c]
        return round(sum(ls)/len(ls), 1) if ls else None
    def tot_llm(C):
        return sum((c.get("llm_calls") or 0) for c in C.values() if "llm_calls" in c)
    print(f"\n{'='*78}\nRESUMEN")
    print(f"  Casos comparados:        {len(common)}")
    print(f"  Latencia prom/caso:      {ta}={avg_lat(ca)}s   {tb}={avg_lat(cb)}s")
    print(f"  Latencia total:          {ta}={A.get('lat_total_s')}s   {tb}={B.get('lat_total_s')}s")
    print(f"  Llamadas LLM totales:    {ta}={tot_llm(ca)}   {tb}={tot_llm(cb)}")
    print(f"  Campos divergentes:      {n_diff}")
    if review:
        print(f"\n  ⚠ REVISAR ({len(review)}) — un modelo llenó y el otro dejó vacío")
        print(f"     (posible alucinación del que llenó, o mejor extracción — tú juzgas):")
        for cid, f, av, bv in review:
            lleno = f"{ta}='{short(av,40)}'" if av else f"{tb}='{short(bv,40)}'"
            print(f"       caso {cid} · {f}: {lleno}")
    print(f"{'='*78}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
