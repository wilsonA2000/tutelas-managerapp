"""P3 — Regenerar folder_name para casos con NULL o formato no canónico.

Estrategia:
- Si el caso tiene rad23 + accionante en DB → generar "YYYY-NNNNN ACCIONANTE".
- Solo actualiza el campo en DB (folder_name). NO renombra carpetas físicas.
- El sync posterior detectará la discrepancia y reportará al operador.
- Respeta regla del proyecto: "Sync NUNCA crea carpetas ni mueve archivos".

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
from backend.database.models import Case, AuditLog


CANONICAL_RE = re.compile(r"^(20\d{2})-\d{4,6}\s+[A-ZÁÉÍÓÚÑ]")


def extract_year_cons(rad23: str) -> tuple[str, str] | None:
    """Extrae (YYYY, NNNNN) desde un rad23 formato Colombia."""
    if not rad23:
        return None
    # Formato: XX-XXX-XX-XX-XXX-YYYY-NNNNN-NN
    # El año tiene 4 dígitos, el consecutivo 4-5 dígitos después.
    m = re.search(r"(20\d{2})[^0-9]?(\d{4,5})", rad23)
    if m:
        return m.group(1), m.group(2).zfill(5)
    return None


def propose_name(case: Case) -> str | None:
    """Genera nombre canónico desde rad23 + accionante. Retorna None si no hay datos."""
    if not case.accionante or not case.accionante.strip():
        return None
    if not case.radicado_23_digitos:
        return None
    yc = extract_year_cons(case.radicado_23_digitos)
    if not yc:
        return None
    year, cons = yc
    # Limpiar accionante: mayúsculas + sin comas/paréntesis/extras
    acc = case.accionante.strip().upper()
    acc = re.sub(r"[,;.\(\)]", " ", acc)
    acc = re.sub(r"\s+", " ", acc).strip()
    # Limitar a 80 chars por seguridad en FS
    return f"{year}-{cons} {acc}"[:100]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        cases = db.query(Case).all()

        null_fixed = 0
        noncanon_fixed = 0
        skipped_no_data = []
        updates = []

        for c in cases:
            current = c.folder_name
            if current and CANONICAL_RE.match(current):
                continue  # ya canónico
            proposed = propose_name(c)
            if not proposed:
                skipped_no_data.append(c.id)
                continue
            updates.append((c.id, current, proposed))

        print(f"Casos que pueden normalizarse: {len(updates)}")
        print(f"Casos sin datos suficientes: {len(skipped_no_data)}")
        print()

        for cid, old, new in updates[:20]:
            print(f"  case#{cid}: {old!r} → {new!r}")
        if len(updates) > 20:
            print(f"  ... y {len(updates)-20} más")

        if args.apply:
            collisions = []
            for cid, old, new in updates:
                # Verificar colisión
                exists = db.execute(
                    text("SELECT id FROM cases WHERE folder_name=:n AND id!=:id"),
                    {"n": new, "id": cid},
                ).fetchone()
                if exists:
                    # Sufijo numérico
                    suffix = 2
                    while True:
                        candidate = f"{new} (#{suffix})"
                        exists2 = db.execute(
                            text("SELECT id FROM cases WHERE folder_name=:n"),
                            {"n": candidate},
                        ).fetchone()
                        if not exists2:
                            new = candidate
                            collisions.append((cid, candidate))
                            break
                        suffix += 1
                db.execute(
                    text("UPDATE cases SET folder_name=:n WHERE id=:id"),
                    {"n": new, "id": cid},
                )
                db.add(AuditLog(
                    case_id=cid,
                    field_name="folder_name",
                    old_value=old or "",
                    new_value=new,
                    action="P3_RENAME_FOLDER",
                    source="cleanup_p3_rename_folders.py",
                ))
                if old is None:
                    null_fixed += 1
                else:
                    noncanon_fixed += 1
            if collisions:
                print(f"\n⚠️  {len(collisions)} colisiones resueltas con sufijo numérico:")
                for cid, name in collisions[:5]:
                    print(f"   case#{cid} → {name}")
            db.commit()
            print(f"\n✅ Aplicado: {null_fixed} folder_name creados, {noncanon_fixed} normalizados")
        else:
            db.rollback()
            print(f"\n⚠️  DRY-RUN. Re-ejecuta con --apply.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
