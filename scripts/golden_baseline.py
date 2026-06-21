"""Golden baseline = oráculo de regresión para la de-sobreingeniería (Fase 0).

Corre v9 `extract_case` en dry-run DETERMINISTA (sin LLM, sin RAMA) sobre un conjunto
de casos y snapshotea los 39 campos computados. Tras cada fase del refactor se re-corre
y se diffea: diff = 0 ⇒ sin regresión en el motor determinista.

Uso:
  python3 scripts/golden_baseline.py snapshot [--all | --sample N | --ids 1,2,3] -o FILE
  python3 scripts/golden_baseline.py diff BASELINE.json [--all | --sample N | --ids ...]

Determinismo: fija V9_DISABLE_LLM=true y RAMA_JUDICIAL_ENABLED=false ANTES de importar
backend (igual que v9_test_db). El LLM gap-fill es no-determinista y NO es lo que tocan
las fases estructurales; por eso se apaga para un oráculo estable.
"""
import os, sys, json, argparse, time

os.environ.setdefault("V9_DISABLE_LLM", "true")
os.environ.setdefault("RAMA_JUDICIAL_ENABLED", "false")
os.environ.setdefault("ACUMULACION_AUTO", "false")
os.environ.setdefault("CONFLATION_AUTO", "false")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database.database import SessionLocal
from backend.database.models import Case
from backend.v9.pipeline import extract_case


def _select_ids(db, args) -> list[int]:
    q = db.query(Case.id).order_by(Case.id)
    ids = [r[0] for r in q.all()]
    if args.ids:
        want = {int(x) for x in args.ids.split(",")}
        return [i for i in ids if i in want]
    if args.all:
        return ids
    # muestra estratificada determinista: cada k-ésimo caso para cubrir el rango
    n = args.sample or 80
    if len(ids) <= n:
        return ids
    step = len(ids) / n
    return [ids[int(i * step)] for i in range(n)]


def run_snapshot(db, ids: list[int]) -> dict:
    out = {}
    t0 = time.time()
    for k, cid in enumerate(ids, 1):
        try:
            res = extract_case(db, cid, dry_run=True, use_llm=False)
            out[str(cid)] = dict(res.fields.values)
        except Exception as e:
            out[str(cid)] = {"__error__": str(e)[:200]}
        if k % 20 == 0:
            print(f"  {k}/{len(ids)} ({time.time()-t0:.0f}s)", file=sys.stderr)
    print(f"  snapshot {len(ids)} casos en {time.time()-t0:.0f}s", file=sys.stderr)
    return out


def cmd_snapshot(args):
    db = SessionLocal()
    try:
        ids = _select_ids(db, args)
        snap = run_snapshot(db, ids)
    finally:
        db.close()
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"OK snapshot -> {args.output} ({len(snap)} casos)")


def cmd_diff(args):
    with open(args.baseline, encoding="utf-8") as f:
        base = json.load(f)
    db = SessionLocal()
    try:
        ids = [int(c) for c in base] if not (args.all or args.sample or args.ids) else _select_ids(db, args)
        cur = run_snapshot(db, ids)
    finally:
        db.close()
    # Solo comparamos los casos efectivamente re-corridos (cur). Un diff de subconjunto
    # NO debe marcar como regresión los casos del baseline que no se re-corrieron.
    diffs = []
    missing = [cid for cid in cur if cid not in base]
    for cid in sorted(cur, key=lambda x: int(x)):
        b, c = base.get(cid, {}), cur.get(cid, {})
        for field in sorted(set(b) | set(c)):
            if b.get(field) != c.get(field):
                diffs.append((cid, field, b.get(field), c.get(field)))
    if missing:
        print(f"⚠️  {len(missing)} casos re-corridos no estaban en el baseline: {missing[:10]}")
    if not diffs:
        print(f"✅ DIFF = 0 sobre {len(cur)} casos — sin regresión.")
        return 0
    print(f"❌ {len(diffs)} diferencias sobre {len(cur)} casos:")
    for cid, field, old, new in diffs[:80]:
        print(f"  c{cid}.{field}: {old!r} -> {new!r}")
    if len(diffs) > 80:
        print(f"  ... y {len(diffs)-80} más")
    return 1


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("snapshot", "diff"):
        p = sub.add_parser(name)
        if name == "diff":
            p.add_argument("baseline")
        p.add_argument("--all", action="store_true")
        p.add_argument("--sample", type=int, default=0)
        p.add_argument("--ids", type=str, default="")
        if name == "snapshot":
            p.add_argument("-o", "--output", default="data/golden_baseline.json")
    args = ap.parse_args()
    sys.exit(cmd_snapshot(args) if args.cmd == "snapshot" else cmd_diff(args))


if __name__ == "__main__":
    main()
