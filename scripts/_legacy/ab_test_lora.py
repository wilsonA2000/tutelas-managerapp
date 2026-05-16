"""A/B test: extract_multi_focused sobre 5 cases, NO escribe DB.

Mismo modelo (Qwen3-4B Q4_K_M). Diferencia: con/sin LoRA.
Output: JSON con resultados que se compara despues.

Uso:
    python3 scripts/ab_test_lora.py --label base
    python3 scripts/ab_test_lora.py --label lora
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.cognition.cognitive_complementary_ai import _build_authority_weighted_text
from backend.cognition.focused_field_extractors import (
    FIELD_PROMPTS, extract_multi_focused,
)
from backend.database.database import SessionLocal
from backend.database.models import Case

CASE_IDS = [4, 17, 47, 92, 187]
EXPORTS = Path(__file__).resolve().parents[1] / "data" / "exports"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True, help="base | lora")
    args = ap.parse_args()

    db = SessionLocal()
    out = {"label": args.label, "ts": time.time(), "cases": []}
    try:
        for cid in CASE_IDS:
            c = db.query(Case).filter(Case.id == cid).first()
            full_text = _build_authority_weighted_text(db, c, max_chars=3500)

            fields_appl = []
            for f in FIELD_PROMPTS:
                if getattr(c, f, None):
                    continue
                if f in ("quien_impugno", "juzgado_2nd", "sentido_fallo_2nd"):
                    if (c.impugnacion or "").upper() not in ("SI", "S"):
                        continue
                if f in ("fecha_apertura_incidente", "responsable_desacato"):
                    if (c.incidente or "").upper() not in ("SI", "S"):
                        continue
                fields_appl.append(f)

            t0 = time.time()
            try:
                results = extract_multi_focused(c, full_text, fields_appl, max_tokens=400)
            except Exception as e:
                results = {}
                err = str(e)[:120]
            else:
                err = None
            dt = time.time() - t0

            entry = {
                "case_id": cid,
                "fields_applicable": fields_appl,
                "fields_returned": list(results.keys()),
                "fields_passed_validators": list(results.keys()),
                "fields_count": len(results),
                "dt": round(dt, 1),
                "error": err,
                "values": {
                    k: {"v": str(r.value)[:100], "conf": r.confidence}
                    for k, r in results.items()
                },
            }
            out["cases"].append(entry)
            print(f"case={cid:4d} appl={len(fields_appl)} returned={len(results)} dt={dt:.1f}s "
                  f"-> {[(k, str(r.value)[:30]) for k,r in results.items()]}")
    finally:
        db.close()

    out_path = EXPORTS / f"ab_test_{args.label}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    total_returned = sum(c["fields_count"] for c in out["cases"])
    total_appl = sum(len(c["fields_applicable"]) for c in out["cases"])
    avg_dt = sum(c["dt"] for c in out["cases"]) / max(1, len(out["cases"]))
    print(f"\n=== {args.label.upper()} ===")
    print(f"Cases: {len(out['cases'])}  Fields aplicables: {total_appl}  "
          f"Llenos: {total_returned}  Tasa: {100*total_returned/max(1,total_appl):.0f}%")
    print(f"Avg dt: {avg_dt:.1f}s/case")
    print(f"Reporte: {out_path}")


if __name__ == "__main__":
    main()
