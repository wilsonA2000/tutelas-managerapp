#!/usr/bin/env python3
"""Computa benchmark de una DB de experimento Gmail ingest.

Uso:
    python3 scripts/benchmark_gmail_ingest.py [db_path] [label]

Si db_path no se da, usa la DB activa de settings.
Emite JSON a stdout (y a logs/benchmark_{label}.json si label).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


def compute(db_path: str, label: str = "") -> dict:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Counts
    c.execute("SELECT COUNT(*) FROM cases"); cases = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM documents"); docs = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM emails"); emails = c.fetchone()[0]

    # Email status
    c.execute("SELECT status, COUNT(*) FROM emails GROUP BY status")
    status = dict(c.fetchall())

    # Match confidence distribution
    c.execute("SELECT match_confidence, COUNT(*) FROM emails GROUP BY match_confidence")
    confidence = dict(c.fetchall())

    # Orphans (case_id IS NULL)
    c.execute("SELECT COUNT(*) FROM emails WHERE case_id IS NULL")
    orphans = c.fetchone()[0]

    # Cases without rad23
    c.execute("SELECT COUNT(*) FROM cases WHERE radicado_23_digitos IS NULL OR radicado_23_digitos=''")
    cases_no_rad23 = c.fetchone()[0]

    # Cases without forest
    c.execute("SELECT COUNT(*) FROM cases WHERE radicado_forest IS NULL OR radicado_forest=''")
    cases_no_forest = c.fetchone()[0]

    # Casos con accionante PENDIENTE REVISION (no extraído)
    c.execute("SELECT COUNT(*) FROM cases WHERE accionante IS NULL OR accionante LIKE '%PENDIENTE%'")
    cases_no_accionante = c.fetchone()[0]

    # Score distribution (stats)
    c.execute("SELECT AVG(match_score), MIN(match_score), MAX(match_score) FROM emails WHERE match_score IS NOT NULL")
    s = c.fetchone()
    score_stats = {"avg": round(s[0], 1) if s[0] else None, "min": s[1], "max": s[2]}

    # Time range
    c.execute("SELECT MIN(date_received), MAX(date_received) FROM emails")
    date_range = c.fetchone()

    # Coverage
    assigned = status.get("ASIGNADO", 0)
    coverage_pct = round(100 * assigned / emails, 2) if emails else 0

    report = {
        "label": label,
        "timestamp": datetime.utcnow().isoformat(),
        "db_path": db_path,
        "counts": {
            "cases": cases,
            "documents": docs,
            "emails": emails,
        },
        "email_status": status,
        "match_confidence": {k or "NULL": v for k, v in confidence.items()},
        "score_stats": score_stats,
        "orphan_emails": orphans,
        "coverage_pct": coverage_pct,
        "cases_quality": {
            "without_rad23": cases_no_rad23,
            "without_forest": cases_no_forest,
            "without_accionante": cases_no_accionante,
        },
        "date_range": {
            "first": date_range[0],
            "last": date_range[1],
        },
    }
    conn.close()
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db_path", nargs="?", default=None)
    ap.add_argument("label", nargs="?", default="")
    args = ap.parse_args()

    if args.db_path:
        db_path = args.db_path
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from backend.core.settings import settings
        db_path = str(settings.db_path)

    report = compute(db_path, args.label)
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))

    if args.label:
        out = Path(__file__).resolve().parents[1] / "logs" / f"benchmark_{args.label}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        print(f"\n[saved] {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
