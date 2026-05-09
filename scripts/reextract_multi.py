"""Re-extraccion dirigida con multi-prompt (1 call/case) + concurrencia ThreadPool.

Optimizaciones vs reextract_focused.py:
  - 1 llamada LLM por case (5 campos en un solo JSON) en lugar de 5 secuenciales.
  - 2 workers concurrentes consumen los 2 slots de llama-server (--parallel 2).
  - Commit por batch de 5 cases para no perder progreso.
  - Pre-skip de cases sin texto suficiente.

Uso:
    python3 scripts/reextract_multi.py --execute --max 5    # smoke test
    python3 scripts/reextract_multi.py --execute            # todos
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.cognition.cognitive_complementary_ai import _build_authority_weighted_text
from backend.cognition.focused_field_extractors import (
    FIELD_PROMPTS, extract_multi_focused,
)
from backend.database.database import SessionLocal
from backend.database.models import AuditLog, Case

EXPORTS = Path(__file__).resolve().parents[1] / "data" / "exports"
TARGET_FIELDS = list(FIELD_PROMPTS.keys())
PRINT_LOCK = Lock()


def load_target_case_ids() -> list[int]:
    rep = json.loads((EXPORTS / "audit_report.json").read_text(encoding="utf-8"))
    target_rules = {"R4", "R8"}
    return [
        e["case_id"] for e in rep["cases"]
        if {f["rule"] for f in e["findings"]} & target_rules
    ]


def applicable_fields(case) -> list[str]:
    out = []
    for f in TARGET_FIELDS:
        if getattr(case, f, None):
            continue
        if f in ("quien_impugno", "juzgado_2nd", "sentido_fallo_2nd"):
            if (case.impugnacion or "").upper() not in ("SI", "S"):
                continue
        if f in ("fecha_apertura_incidente", "responsable_desacato"):
            if (case.incidente or "").upper() not in ("SI", "S"):
                continue
        out.append(f)
    return out


def process_one(case_id: int) -> dict:
    """Procesa 1 case en su propia DB session (thread-safe)."""
    db = SessionLocal()
    try:
        c = db.query(Case).filter(Case.id == case_id).first()
        if not c:
            return {"case_id": case_id, "skipped": "not_found"}
        fields = applicable_fields(c)
        if not fields:
            return {"case_id": case_id, "skipped": "no_applicable_fields"}
        full_text = _build_authority_weighted_text(db, c, max_chars=3500)
        if not full_text or len(full_text) < 200:
            return {"case_id": case_id, "skipped": "no_text"}

        t0 = time.time()
        results = extract_multi_focused(c, full_text, fields, max_tokens=400)
        dt = time.time() - t0

        applied = []
        for fname, res in results.items():
            if not res.value or res.confidence < 0.5:
                continue
            if getattr(c, fname, None):
                continue
            setattr(c, fname, str(res.value)[:500])
            db.add(AuditLog(
                case_id=c.id, field_name=fname,
                old_value="", new_value=str(res.value)[:500],
                action="REEXTRACT_MULTI",
                source=f"v8.3_multi conf={res.confidence}",
            ))
            applied.append(fname)
        if applied:
            db.commit()
        return {"case_id": case_id, "fields_attempted": fields,
                "fields_applied": applied, "dt": round(dt, 1)}
    except Exception as e:
        return {"case_id": case_id, "error": str(e)[:120]}
    finally:
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--execute", action="store_true")
    ap.add_argument("--max", type=int, default=None)
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()

    case_ids = load_target_case_ids()
    if args.max:
        case_ids = case_ids[: args.max]
    print(f"Target: {len(case_ids)} cases · workers={args.workers}")

    if args.dry_run:
        print("[DRY-RUN] no se ejecutara — usa --execute")
        return 0

    t0 = time.time()
    completed = 0
    total_applied = 0
    field_counter: dict[str, int] = {}
    skipped = {}
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process_one, cid): cid for cid in case_ids}
        for fut in as_completed(futures):
            r = fut.result()
            completed += 1
            cid = r.get("case_id")
            if "error" in r:
                errors.append(f"#{cid}: {r['error']}")
            elif "skipped" in r:
                skipped[r["skipped"]] = skipped.get(r["skipped"], 0) + 1
            else:
                applied = r.get("fields_applied", [])
                total_applied += len(applied)
                for f in applied:
                    field_counter[f] = field_counter.get(f, 0) + 1
                with PRINT_LOCK:
                    elapsed = time.time() - t0
                    eta = elapsed / completed * (len(case_ids) - completed)
                    print(f"[{completed:3d}/{len(case_ids)}] case={cid:4d} "
                          f"fields={r['fields_attempted']} applied={applied} "
                          f"dt={r['dt']}s · elapsed={int(elapsed)}s eta={int(eta)}s")

    elapsed = time.time() - t0
    print(f"\n=== DONE en {elapsed/60:.1f} min ===")
    print(f"Cases procesados: {completed}/{len(case_ids)}")
    print(f"Total fields aplicados: {total_applied}")
    print(f"Por field: {field_counter}")
    print(f"Skipped: {skipped}")
    if errors:
        print(f"Errores ({len(errors)}):")
        for e in errors[:10]:
            print(f"  {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
