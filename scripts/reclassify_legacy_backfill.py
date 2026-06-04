"""Fase 1 — Backfill de reclasificación: sube a la taxonomía RICA (DocType) los docs
que aún tienen etiqueta legacy por-filename (PDF_*/DOCX_*/OTRO/DESCONOCIDO) y tienen
texto, reusando el clasificador por CONTENIDO del doc_librarian.

Por qué: los extractores de field_extractor.py filtran doc_type por igualdad EXACTA
(SENTENCIA_1RA/DEMANDA_TUTELA/RESPUESTA/…). Un doc en PDF_SENTENCIA es invisible para
ellos → campos vacíos. Este backfill los hace visibles de una sola pasada.

Seguro por diseño:
  - DRY-RUN por defecto (imprime histograma de transiciones, no escribe).
  - --apply EXIGE crear un backup nombrado antes (sqlite3 backup API, WAL-safe).
  - Solo toca etiquetas legacy (reclassify_legacy_docs respeta first-classifier-wins:
    los tipos ricos / curados a mano NO se tocan).
  - Idempotente: un segundo --apply reporta 0 cambios.
  - AuditLog por cada cambio.

Uso:
  ./venv/bin/python3 scripts/reclassify_legacy_backfill.py                 # DRY-RUN
  ./venv/bin/python3 scripts/reclassify_legacy_backfill.py --apply         # aplica (crea backup)
  ./venv/bin/python3 scripts/reclassify_legacy_backfill.py --min-conf 0.5  # baja el umbral
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.database.database import SessionLocal
from backend.database.models import AuditLog, Case
from backend.v9.doc_librarian import reclassify_legacy_docs
from backend.services.backup_service import create_backup


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill de reclasificación de docs legacy por contenido.")
    ap.add_argument("--apply", action="store_true", default=False,
                    help="Aplicar los cambios (por defecto es DRY-RUN). Crea un backup antes.")
    ap.add_argument("--min-conf", type=float, default=0.6,
                    help="Confianza mínima del clasificador para comprometer un tipo (default 0.6).")
    ap.add_argument("--limit-cases", type=int, default=0,
                    help="Máximo de casos a procesar (0 = todos).")
    args = ap.parse_args()

    transitions: Counter = Counter()   # (old -> new) -> count
    changes_all: list[dict] = []
    cases_touched: set[int] = set()

    backup_info = None
    if args.apply:
        backup_info = create_backup(reason="pre_reclassify_legacy_backfill")
        if "error" in backup_info:
            print(f"!! No se pudo crear el backup: {backup_info['error']}. ABORTO (no aplico sin backup).")
            return 1
        print(f"✓ Backup creado: {backup_info['filename']} ({backup_info['size_mb']} MB)\n")

    with SessionLocal() as db:
        q = db.query(Case)
        if args.limit_cases:
            q = q.limit(args.limit_cases)
        cases = q.all()
        print(f"Casos a evaluar: {len(cases)}  ·  min_conf={args.min_conf}  ·  modo={'APPLY' if args.apply else 'DRY-RUN'}\n")

        for case in cases:
            changes = reclassify_legacy_docs(db, case, min_conf=args.min_conf)
            for ch in changes:
                transitions[(ch["old"], ch["new"])] += 1
                changes_all.append(ch)
                cases_touched.add(case.id)
                if args.apply:
                    db.add(AuditLog(
                        case_id=case.id,
                        field_name="doc_type",
                        old_value=ch["old"],
                        new_value=ch["new"],
                        action="RECLASSIFY_LEGACY_BACKFILL",
                        source="script:reclassify_legacy_backfill",
                    ))

        if args.apply:
            db.commit()
        else:
            db.rollback()  # descarta las mutaciones de doc_type que hizo reclassify_legacy_docs

    # ---- Reporte ----
    mode = "[DRY-RUN] " if not args.apply else "[APLICADO] "
    print("=== Histograma de transiciones (old -> new) ===")
    for (old, new), n in transitions.most_common():
        print(f"  {n:>5}  {old or '∅':28s} -> {new}")
    print(f"\n{mode}Total cambios: {len(changes_all)}  ·  Docs únicos: {len({c['doc_id'] for c in changes_all})}"
          f"  ·  Casos tocados: {len(cases_touched)}")
    if changes_all:
        print("\nMuestra (primeros 8):")
        for ch in changes_all[:8]:
            fn = (ch.get("filename") or "")[:38]
            print(f"  [{ch['doc_id']}] {fn!r:40s} {ch['old']} -> {ch['new']} (conf {ch['conf']})")
    if not args.apply and changes_all:
        print("\n→ Revisa el histograma. Para aplicar: --apply (creará backup automáticamente).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
