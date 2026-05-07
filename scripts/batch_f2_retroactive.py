"""F2 batch retroactivo — calcula confidences sobre todos los casos COMPLETO sin re-extraer.

Uso:
    USE_FIELD_CONFIDENCE=true python3 scripts/batch_f2_retroactive.py [--dry-run] [--limit N]

Reporta distribución bandas global + por campo + casos top-10 con más campos en BAJO.
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

# Forzar flag para esta corrida
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["USE_FIELD_CONFIDENCE"] = "true"

from backend.cognition.confidence import score_case, SCORED_FIELDS

DB_PATH = Path(__file__).parent.parent / "data" / "tutelas.db"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="No persistir; solo reportar")
    ap.add_argument("--limit", type=int, default=0, help="Limitar casos procesados (0=todos)")
    args = ap.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("PRAGMA table_info(cases)")
        existing_cols = [r[1] for r in cur.fetchall()]
        select_cols = ",".join(f for f in existing_cols)
        sql = f"SELECT {select_cols} FROM cases WHERE processing_status = 'COMPLETO'"
        if args.limit:
            sql += f" LIMIT {args.limit}"
        rows = conn.execute(sql).fetchall()
        print(f"→ Procesando {len(rows)} casos COMPLETO (dry_run={args.dry_run})")

        global_bands = Counter()
        per_field_bands: dict[str, Counter] = defaultdict(Counter)
        case_review_counts = []

        for row in rows:
            # Construir objeto-like con atributos de cada columna
            c = SimpleNamespace(**{k: row[k] for k in row.keys()})
            confidences = score_case(c)
            n_bad = 0
            for field, meta in confidences.items():
                global_bands[meta["band"]] += 1
                per_field_bands[field][meta["band"]] += 1
                if meta["band"] in ("REVISAR", "BAJO"):
                    n_bad += 1
            case_review_counts.append((c.id, n_bad, (c.accionante or "")[:40]))

            if not args.dry_run:
                conn.execute(
                    "UPDATE cases SET field_confidences_json=? WHERE id=?",
                    (json.dumps(confidences, ensure_ascii=False), c.id),
                )

        if not args.dry_run:
            conn.commit()
            print(f"✓ Persistidos confidences en {len(rows)} casos")
        else:
            print("✓ Dry run — no se persistió")

        total = sum(global_bands.values())
        print("\n=== Distribución global ===")
        for band in ("OK", "REVISAR", "BAJO"):
            n = global_bands[band]
            pct = 100 * n / total if total else 0
            print(f"  {band:8s}  {n:6d}  ({pct:5.1f}%)")

        # Campos con más BAJO (excluyendo vacíos esperables como tercer incidente)
        print("\n=== Top 15 campos con más BAJO ===")
        bad_per_field = sorted(
            ((f, per_field_bands[f]["BAJO"], per_field_bands[f]["REVISAR"])
             for f in SCORED_FIELDS),
            key=lambda x: -x[1]
        )[:15]
        print(f"  {'campo':35s} {'BAJO':>6s} {'REVISAR':>8s}")
        for f, bajo, rev in bad_per_field:
            print(f"  {f:35s} {bajo:6d} {rev:8d}")

        # Top 10 casos con más campos problemáticos
        print("\n=== Top 10 casos con más campos REVISAR/BAJO ===")
        case_review_counts.sort(key=lambda x: -x[1])
        for cid, nbad, acc in case_review_counts[:10]:
            print(f"  case={cid:4d}  bad={nbad:3d}  accionante={acc}")

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
