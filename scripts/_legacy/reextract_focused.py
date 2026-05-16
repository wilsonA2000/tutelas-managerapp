"""Re-extraccion dirigida con focused_field_extractors.

Solo toca cases que tienen findings R4 o R8 del audit_report.json
(campos pobres aplicables: quien_impugno, fecha_apertura_incidente,
responsable_desacato, juzgado_2nd, sentido_fallo_2nd vacios).

NO corre todo el pipeline. Solo invoca Capa 6.5 focused.

Uso:
    python3 scripts/reextract_focused.py --dry-run
    python3 scripts/reextract_focused.py --execute [--max N] [--case ID]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.cognition.cognitive_complementary_ai import (
    _build_authority_weighted_text,
)
from backend.cognition.focused_field_extractors import (
    FIELD_PROMPTS,
    extract_focused_for_case,
)
from backend.database.database import SessionLocal
from backend.database.models import AuditLog, Case

EXPORTS = Path(__file__).resolve().parents[1] / "data" / "exports"
TARGET_FIELDS = list(FIELD_PROMPTS.keys())


def load_target_case_ids(report_path: Path, target_rules=("R4", "R8")) -> list[int]:
    if not report_path.exists():
        return []
    rep = json.loads(report_path.read_text(encoding="utf-8"))
    out = []
    for entry in rep["cases"]:
        rules = {f["rule"] for f in entry["findings"]}
        if rules & set(target_rules):
            out.append(entry["case_id"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--execute", action="store_true")
    ap.add_argument("--max", type=int, default=None, help="limite de cases")
    ap.add_argument("--case", type=int, default=None, help="solo un case_id")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        if args.case:
            target_ids = [args.case]
        else:
            target_ids = load_target_case_ids(EXPORTS / "audit_report.json")
            if args.max:
                target_ids = target_ids[: args.max]
        print(f"Target cases: {len(target_ids)}")

        before_counter = Counter()
        after_counter = Counter()
        filled_per_field: Counter[str] = Counter()
        rejected_per_field: Counter[str] = Counter()
        no_text_count = 0

        for cid in target_ids:
            case = db.query(Case).filter(Case.id == cid).first()
            if not case:
                continue
            for f in TARGET_FIELDS:
                if getattr(case, f, None):
                    before_counter[f] += 1

            full_text = _build_authority_weighted_text(db, case, max_chars=8000)
            if not full_text or len(full_text) < 200:
                no_text_count += 1
                continue

            try:
                results = extract_focused_for_case(case, full_text)
            except Exception as e:
                print(f"  case_id={cid} ERROR: {str(e)[:100]}")
                continue

            for fname, res in results.items():
                if res.value is None:
                    rejected_per_field[fname] += 1
                    continue
                if res.confidence < 0.5:
                    rejected_per_field[fname] += 1
                    continue
                if getattr(case, fname, None):
                    continue  # double-check no pisar
                if args.execute:
                    setattr(case, fname, str(res.value)[:500])
                    db.add(AuditLog(
                        case_id=case.id, field_name=fname,
                        old_value="", new_value=str(res.value)[:500],
                        action="REEXTRACT_FOCUSED",
                        source=f"v8.3_focused conf={res.confidence}",
                    ))
                filled_per_field[fname] += 1

            for f in TARGET_FIELDS:
                if getattr(case, f, None):
                    after_counter[f] += 1

        if args.execute:
            db.commit()
            print("\n[OK] Cambios persistidos")
        else:
            db.rollback()
            print("\n[DRY-RUN] cambios NO persistidos")

        print(f"\nCases sin texto suficiente (skipped): {no_text_count}")
        print("\nLLM intentos por campo:")
        for f in TARGET_FIELDS:
            print(f"  {f}: filled={filled_per_field[f]} rejected={rejected_per_field[f]}")

        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
