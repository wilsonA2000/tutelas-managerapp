"""One-shot: reclasifica docs DEMANDA_TUTELA que en realidad son auto/informe/oficio.

~32 docs quedaron mal rotulados DEMANDA_TUTELA (autos/informes que CITAN la tutela).
Tras el fix del clasificador (commit dcfb01e), este script los re-evalúa con el
clasificador de PRODUCCIÓN ya endurecido (doc_librarian.classify) y corrige el doc_type.

SEGURIDAD: solo procesa docs cuyo texto dispara `_RE_NOT_DEMANDA` (marcador dispositivo/
informe) → una demanda REAL nunca se toca. Idempotente: una 2ª corrida = 0 cambios.

Uso:
  ./venv/bin/python3 scripts/reclassify_demanda_falsa.py --dry-run   # ver el plan
  ./venv/bin/python3 scripts/reclassify_demanda_falsa.py --backup    # backup + aplicar
"""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.database.database import SessionLocal
from backend.database.models import Document, AuditLog
from backend.core.time import utcnow
from backend.extraction.doc_ops import _RE_NOT_DEMANDA
from backend.v9.doc_io import DocText
from backend.v9 import doc_librarian

DB_PATH = Path(__file__).parent.parent / "data" / "tutelas.db"


def _production_type(doc: Document) -> str:
    """Tipo según el clasificador de producción endurecido (doc_librarian.classify).
    Se CONFÍA en su veredicto: si dice DEMANDA_TUTELA, el doc ES una demanda real
    (el guard `_RE_DEMANDA_1P` la protege aunque los anexos traigan un 'RESUELVE') →
    el caller la salta. NO se fuerza otro tipo."""
    dt = DocText(
        path=doc.file_path or "", filename=doc.filename or "",
        text=doc.extracted_text or "", method="cache",
    )
    res = doc_librarian.classify(dt)
    return res.doc_type.value if hasattr(res.doc_type, "value") else str(res.doc_type)


def main() -> int:
    ap = argparse.ArgumentParser(description="Reclasifica DEMANDA_TUTELA falsas (autos/informes).")
    ap.add_argument("--dry-run", action="store_true", default=False)
    ap.add_argument("--backup", action="store_true", default=False,
                    help="Copia data/tutelas.db a un .bak antes de escribir")
    args = ap.parse_args()
    apply = not args.dry_run

    if apply and args.backup:
        ts = utcnow().strftime("%Y%m%d_%H%M%S")
        bak = DB_PATH.with_name(f"tutelas.db.bak_pre_demanda_falsa_{ts}")
        shutil.copy2(DB_PATH, bak)
        print(f"backup: {bak.name}")

    changed = 0
    with SessionLocal() as db:
        docs = db.query(Document).filter(
            Document.doc_type == "DEMANDA_TUTELA",
            Document.extracted_text.isnot(None),
            Document.extracted_text != "",
        ).all()
        print(f"DEMANDA_TUTELA con texto: {len(docs)}")
        for doc in docs:
            text = doc.extracted_text or ""
            # SEGURIDAD: solo los que disparan el marcador anti-demanda (NO demandas reales).
            if not _RE_NOT_DEMANDA.search(text[:3000]):
                continue
            new_type = _production_type(doc)
            if new_type == "DEMANDA_TUTELA":
                continue  # no se pudo determinar otro tipo → dejar como está
            print(f"  [{doc.id}] c{doc.case_id} {(doc.filename or '')[:44]!r:46s} DEMANDA_TUTELA -> {new_type}")
            changed += 1
            if apply:
                db.add(AuditLog(
                    case_id=doc.case_id, field_name="doc_type",
                    old_value="DEMANDA_TUTELA", new_value=new_type,
                    action="RECLASSIFY_DEMANDA_FALSA",
                    source="script:reclassify_demanda_falsa",
                ))
                doc.doc_type = new_type
                doc.updated_at = utcnow()
        if apply and changed:
            db.commit()
        print(f"\n{'APLICADO' if apply else 'DRY-RUN'}: {changed} reclasificados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
