"""Benchmark del extractor ÚNICO DeepSeek contra el cuadro CURADO (verdad humana).

Corre backend/v9/llm_extract.extract_all sobre N casos curados por Wilson y mide el % de
ACUERDO por campo. Es el gate de calidad de la re-arquitectura (F2): dirige el tuning del
prompt y decide cuándo el extractor único puede reemplazar la competencia regex+gap_fill.

Uso:
    venv/bin/python3 scripts/benchmark_curado.py --sample 25
    venv/bin/python3 scripts/benchmark_curado.py --all
    venv/bin/python3 scripts/benchmark_curado.py --sample 25 --field derecho_vulnerado  # ver diffs
"""
import argparse
import os
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal
from backend.database.models import Case
from backend.v9.llm_extract import extract_all
from backend.v9.types import EXCEL_FIELDS

_MULTI = {"derecho_vulnerado"}  # campos multi-valor separados por ' - '


def _norm(s: str) -> str:
    s = (s or "").strip().upper()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s)


def _agree(field: str, ext: str, cur: str) -> str:
    e, c = _norm(ext), _norm(cur)
    if not e and not c:
        return "BOTH_EMPTY"
    if not e:
        return "EXT_EMPTY"   # curado tiene, extractor no
    if not c:
        return "CUR_EMPTY"   # extractor tiene, curado no (puede ser mejora)
    if field in _MULTI:
        es, cs = set(x.strip() for x in e.split("-")), set(x.strip() for x in c.split("-"))
        if es == cs:
            return "AGREE"
        return "AGREE_PARTIAL" if (es & cs) else "DIFF"
    return "AGREE" if e == c else ("AGREE_SUBSTR" if (e in c or c in e) else "DIFF")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--field", type=str, default=None, help="muestra diffs de este campo")
    args = ap.parse_args()

    db = SessionLocal()
    q = db.query(Case).filter(Case.processing_status == "COMPLETO").order_by(Case.id)
    cases = q.all()
    if args.sample and not args.all:
        step = max(1, len(cases) // args.sample)
        cases = cases[::step][: args.sample]
    print(f"Benchmark sobre {len(cases)} casos curados (COMPLETO).\n")

    tally = defaultdict(lambda: defaultdict(int))
    diffs = defaultdict(list)
    for i, case in enumerate(cases):
        try:
            out = extract_all(db, case)
        except Exception as e:
            print(f"  c{case.id} ERROR: {str(e)[:80]}")
            continue
        if not out:
            continue
        for f in EXCEL_FIELDS:
            verdict = _agree(f, out.get(f, ""), getattr(case, f, "") or "")
            tally[f][verdict] += 1
            if verdict == "DIFF":
                diffs[f].append((case.id, (out.get(f, "") or "")[:40], (getattr(case, f, "") or "")[:40]))
        if (i + 1) % 10 == 0:
            print(f"  ...{i+1}/{len(cases)}")

    print(f"\n{'CAMPO':28} | AGREE | ~SUB | ~PAR | DIFF | extΦ | curΦ | 2Φ")
    print("-" * 80)
    # ordenar por peor DIFF
    for f in sorted(EXCEL_FIELDS, key=lambda x: -tally[x]["DIFF"]):
        t = tally[f]
        print(f"{f:28} | {t['AGREE']:5} | {t['AGREE_SUBSTR']:4} | {t['AGREE_PARTIAL']:4} | "
              f"{t['DIFF']:4} | {t['EXT_EMPTY']:4} | {t['CUR_EMPTY']:4} | {t['BOTH_EMPTY']}")

    if args.field:
        print(f"\n=== DIFFs de {args.field} ===")
        for cid, e, c in diffs[args.field][:25]:
            print(f"  c{cid}: ext={e!r} | cur={c!r}")
    db.close()


if __name__ == "__main__":
    main()
