"""P2 — Marcar documentos con mismo hash en múltiples casos.

Estrategia:
- Para cada hash con múltiples apariciones:
  - Mantener "canónico": doc del caso con mayor prioridad
    (caso original de tutela > caso de impugnación > otros)
  - Marcar los demás con verificacion='DUPLICADO' + detalle
- NO eliminar archivos físicos ni registros.
- Esto permite que la UI los distinga sin perder trazabilidad.

Dry-run por defecto. --apply para ejecutar.
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from sqlalchemy import text
from backend.database.database import SessionLocal
from backend.database.models import Document, Case


def choose_canonical(docs: list[Document]) -> Document:
    """Canónico: doc con case que tiene más campos llenos + case_id menor (más antiguo)."""
    def score(d: Document) -> tuple[int, int]:
        case = d.case
        if not case:
            return (-1, -d.id)
        filled = sum(1 for f in (
            case.radicado_23_digitos, case.accionante, case.asunto,
            case.fecha_ingreso, case.radicado_forest,
        ) if f and str(f).strip())
        return (filled, -case.id)
    return max(docs, key=score)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        # Solo docs con file_hash y con case asignado
        docs = db.query(Document).filter(
            Document.file_hash.isnot(None),
            Document.file_hash != "",
            Document.case_id.isnot(None),
        ).all()
        by_hash = defaultdict(list)
        for d in docs:
            by_hash[d.file_hash].append(d)

        marked = 0
        groups = 0
        for h, group in by_hash.items():
            # Agrupados por case para detectar cross-case dupes
            cases = {d.case_id for d in group}
            if len(cases) < 2:
                continue  # no es dupe cross-case
            groups += 1
            canonical = choose_canonical(group)
            print(f"\nHash {h[:12]}: {group[0].filename[:40]}")
            print(f"  Canónico: doc#{canonical.id} (case #{canonical.case_id})")
            for d in group:
                if d.id == canonical.id:
                    continue
                # Si ya está marcado como DUPLICADO, skip
                if (d.verificacion or "") == "DUPLICADO":
                    continue
                print(f"  → Marcar doc#{d.id} (case #{d.case_id}) as DUPLICADO")
                if args.apply:
                    db.execute(
                        text("UPDATE documents SET verificacion='DUPLICADO', "
                             "verificacion_detalle=:d WHERE id=:id"),
                        {"id": d.id,
                         "d": f"Copia de doc#{canonical.id} (case #{canonical.case_id}) hash {h[:12]}"}
                    )
                marked += 1

        if args.apply:
            db.commit()
            print(f"\n✅ {marked} documentos marcados como DUPLICADO en {groups} grupos de hash")
        else:
            db.rollback()
            print(f"\n⚠️  DRY-RUN: {marked} documentos serían marcados en {groups} grupos")
    finally:
        db.close()


if __name__ == "__main__":
    main()
