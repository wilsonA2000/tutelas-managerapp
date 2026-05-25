#!/usr/bin/env python3
"""CLI para correr el pipeline v9 sobre 1 o N casos. Default: dry_run.

Uso:
    python3 scripts/v9_extract.py --case 142
    python3 scripts/v9_extract.py --case 142 --apply       # escribe a DB
    python3 scripts/v9_extract.py --all --limit 10         # primeros 10 casos
    python3 scripts/v9_extract.py --all --apply            # extracción masiva

Salida: tabla con completitud y timing. Si --json, dump completo.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Añadir raíz del proyecto al path para que `from backend...` funcione
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal  # noqa: E402
from backend.database.models import Case  # noqa: E402
from backend.v9.pipeline import extract_case  # noqa: E402


def _print_result(result, verbose: bool = False) -> None:
    f = result.fields
    timing = result.timing_ms
    print(f"\n=== Case {result.case_id} ({result.folder_name}) ===")
    print(f"  Completitud: {f.completitud()}%")
    print(f"  Docs:        {result.docs_processed} ok / {result.docs_failed} failed")
    print(f"  LLM calls:   {result.llm_calls}")
    print(f"  Timing (ms): doc_io={timing.get('doc_io',0)} | regex={timing.get('regex_pass',0)} | "
          f"catalog={timing.get('catalog_resolve',0)} | excel={timing.get('excel_reconcile',0)} | "
          f"llm={timing.get('llm_gap_fill',0)} | persist={timing.get('persist',0)} | "
          f"TOTAL={timing.get('__total',0)}ms")
    if f.abogado_canonical:
        print(f"  Abogado canónico:    {f.abogado_canonical} ({f.abogado_canonical_confidence:.2f})")
    if f.dependencia_canonical:
        print(f"  Dependencia canónica: {f.dependencia_canonical} ({f.dependencia_canonical_confidence:.2f})")
    if verbose:
        print("\n  Campos extraídos:")
        for k, v in f.values.items():
            if v:
                src = f.sources[k].value
                shown = v[:60] + "…" if len(v) > 60 else v
                print(f"    [{src:7}] {k:30} = {shown}")
        empty = f.missing_fields()
        if empty:
            print(f"\n  Campos vacíos ({len(empty)}): {', '.join(empty)}")


def main():
    ap = argparse.ArgumentParser(description="Pipeline v9 — extracción simplificada")
    ap.add_argument("--case", type=int, help="ID de un caso específico")
    ap.add_argument("--all", action="store_true", help="Procesar todos los casos")
    ap.add_argument("--limit", type=int, default=10, help="Límite con --all (default 10)")
    ap.add_argument("--apply", action="store_true", help="Escribir cambios a DB (default: dry_run)")
    ap.add_argument("--verbose", "-v", action="store_true", help="Mostrar todos los campos extraídos")
    ap.add_argument("--json", action="store_true", help="Output JSON en lugar de tabla")
    ap.add_argument("--llm", action="store_true", help="Habilita fallbacks LLM (derecho/asunto/pretensiones/gap-fill/observaciones)")
    args = ap.parse_args()

    if not args.case and not args.all:
        ap.error("Especifica --case <id> o --all")

    db = SessionLocal()
    try:
        if args.case:
            case_ids = [args.case]
        else:
            q = db.query(Case.id).order_by(Case.id).limit(args.limit)
            case_ids = [row[0] for row in q.all()]

        results = []
        for cid in case_ids:
            try:
                r = extract_case(db, cid, dry_run=not args.apply, use_llm=args.llm)
                results.append(r)
                if not args.json:
                    _print_result(r, verbose=args.verbose)
            except Exception as e:
                print(f"[ERROR] case {cid}: {e}", file=sys.stderr)

        if args.json:
            payload = [
                {
                    "case_id": r.case_id,
                    "folder_name": r.folder_name,
                    "completitud": r.fields.completitud(),
                    "docs": {"ok": r.docs_processed, "failed": r.docs_failed},
                    "llm_calls": r.llm_calls,
                    "timing_ms": r.timing_ms,
                    "values": r.fields.values,
                    "sources": r.fields.sources_json(),
                    "abogado_canonical": r.fields.abogado_canonical,
                    "abogado_canonical_confidence": r.fields.abogado_canonical_confidence,
                    "dependencia_canonical": r.fields.dependencia_canonical,
                    "dependencia_canonical_confidence": r.fields.dependencia_canonical_confidence,
                }
                for r in results
            ]
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            # Resumen agregado
            if len(results) > 1:
                avg_compl = sum(r.fields.completitud() for r in results) / len(results)
                total_ms = sum(r.total_ms() for r in results)
                total_llm = sum(r.llm_calls for r in results)
                print(f"\n=== Resumen ({len(results)} casos) ===")
                print(f"  Completitud promedio: {avg_compl:.1f}%")
                print(f"  Tiempo total: {total_ms} ms ({total_ms/len(results):.0f} ms/caso)")
                print(f"  Total LLM calls: {total_llm} ({total_llm/len(results):.2f}/caso)")
                print(f"  Modo: {'APPLY' if args.apply else 'DRY-RUN'}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
