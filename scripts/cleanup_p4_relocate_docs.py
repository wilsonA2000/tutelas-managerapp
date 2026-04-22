"""P4 — Proponer reubicación de documentos SOSPECHOSO / NO_PERTENECE.

Estrategia:
- Para cada doc con verificacion SOSPECHOSO o NO_PERTENECE:
  - Extraer rad23 del texto del documento.
  - Extraer accionante del texto.
  - Extraer radicado FOREST si existe.
  - Buscar caso en DB cuyo rad23 o accionante coincida.
  - Si se encuentra 1 candidato con alta confianza → proponer mover.
  - Si hay múltiples → dejar para revisión humana.

NO mueve archivos físicos. Solo actualiza case_id en DB y registra audit.
El siguiente sync físico detectará la discrepancia.

Dry-run por defecto.
"""

import argparse
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from sqlalchemy import text
from backend.database.database import SessionLocal
from backend.database.models import Document, Case, AuditLog


RAD23_PATTERN = re.compile(r"\b(68[\d]{3,5}[-\s\.\u2013\u2014]?\d{2}[-\s\.\u2013\u2014]?\d{2}[-\s\.\u2013\u2014]?\d{3}[-\s\.\u2013\u2014]?\d{4}[-\s\.\u2013\u2014]?\d{5}[-\s\.\u2013\u2014]?\d{2})")
FOREST_PATTERN = re.compile(r"\b(2026\d{7})\b")


def find_target_case(db, doc: Document) -> tuple[int, str, float] | None:
    """Retorna (case_id, reason, confidence) del caso destino o None."""
    text_raw = doc.extracted_text or ""
    if not text_raw:
        return None

    # 1. Buscar por rad23 exacto
    m = RAD23_PATTERN.search(text_raw[:10000])
    if m:
        rad = m.group(1)
        # Normalizar quitando separadores
        rad_digits = re.sub(r"[^0-9]", "", rad)
        rows = db.execute(
            text("SELECT id, radicado_23_digitos FROM cases WHERE radicado_23_digitos IS NOT NULL")
        ).fetchall()
        for row in rows:
            db_rad = re.sub(r"[^0-9]", "", row[1] or "")
            if rad_digits == db_rad and row[0] != doc.case_id:
                return (row[0], f"rad23 match: {rad}", 0.95)

    # 2. Buscar por FOREST
    m = FOREST_PATTERN.search(text_raw[:5000])
    if m:
        forest = m.group(1)
        row = db.execute(
            text("SELECT id FROM cases WHERE radicado_forest=:f AND id!=:did LIMIT 1"),
            {"f": forest, "did": doc.case_id},
        ).fetchone()
        if row:
            return (row[0], f"forest match: {forest}", 0.9)

    # 3. Buscar por accionante (nombre propio detectado)
    # Esto requiere cognition; importar
    try:
        from backend.cognition import extract_actors, classify_zones
        actors = extract_actors(text_raw[:8000], classify_zones(text_raw[:8000]))
        if actors.accionantes:
            acc_name = actors.accionantes[0].name.strip().upper()
            row = db.execute(
                text("SELECT id FROM cases WHERE UPPER(accionante) LIKE :name AND id!=:did LIMIT 2"),
                {"name": f"%{acc_name[:30]}%", "did": doc.case_id},
            ).fetchall()
            if len(row) == 1:
                return (row[0][0], f"accionante match: {acc_name[:40]}", 0.75)
    except Exception:
        pass

    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="limit docs to process (0 = all)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        q = db.query(Document).filter(
            Document.verificacion.in_(["SOSPECHOSO", "NO_PERTENECE"])
        )
        if args.limit:
            q = q.limit(args.limit)
        docs = q.all()

        print(f"Procesando {len(docs)} docs SOSPECHOSO/NO_PERTENECE...")
        print()

        resolved = 0
        ambiguous = 0
        no_match = 0

        for d in docs:
            target = find_target_case(db, d)
            if not target:
                no_match += 1
                continue

            target_case_id, reason, conf = target
            print(f"  doc#{d.id} [{d.verificacion}] {d.filename[:40]}")
            print(f"    case actual: #{d.case_id} → target: #{target_case_id} ({reason}, conf={conf:.2f})")

            if args.apply and conf >= 0.85:
                old_case = d.case_id
                db.execute(
                    text("UPDATE documents SET case_id=:c, verificacion='REUBICADO_AUTO', "
                         "verificacion_detalle=:d WHERE id=:id"),
                    {"c": target_case_id,
                     "d": f"Reubicado P4: {reason}",
                     "id": d.id},
                )
                db.add(AuditLog(
                    case_id=target_case_id,
                    field_name=f"doc_{d.id}",
                    old_value=f"case_{old_case}",
                    new_value=f"case_{target_case_id} (conf={conf:.2f})",
                    action="P4_RELOCATE_DOC",
                    source=f"cleanup_p4; reason={reason}",
                ))
                resolved += 1
            elif conf < 0.85:
                ambiguous += 1

        if args.apply:
            db.commit()
            print(f"\n✅ Reubicados: {resolved} | Ambiguos (conf<0.85): {ambiguous} | Sin match: {no_match}")
        else:
            db.rollback()
            print(f"\n⚠️  DRY-RUN. {resolved+ambiguous} candidatos | Sin match: {no_match}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
