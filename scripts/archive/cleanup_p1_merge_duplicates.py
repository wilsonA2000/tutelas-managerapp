"""P1 — Fusionar casos duplicados (mismo accionante + rad23).

Estrategia:
1. Identificar grupos duplicados.
2. Elegir canónico: el que tiene MÁS documentos (o si empate, el más viejo / más campos llenos).
3. Migrar documents, emails, extractions, audit_log de los hijos al canónico.
4. Migrar campos vacíos del canónico usando datos de los hijos (mergea, no sobrescribe).
5. Eliminar casos hijos.
6. Registrar todo en AuditLog.

Modo DRY-RUN por defecto (muestra qué haría sin ejecutar).
Ejecutar real con --apply.
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from backend.database.database import SessionLocal
from backend.database.models import Case, Document, Email, Extraction, AuditLog, ComplianceTracking, TokenUsage


def find_duplicates(db):
    """Retorna dict (accionante, rad23) → [cases ordenados por id]"""
    groups = defaultdict(list)
    cases = db.query(Case).filter(
        Case.accionante.isnot(None),
        Case.radicado_23_digitos.isnot(None),
    ).all()
    for c in cases:
        acc = (c.accionante or "").strip().upper()[:60]
        rad = (c.radicado_23_digitos or "").strip()
        if acc and rad:
            groups[(acc, rad)].append(c)
    return {k: v for k, v in groups.items() if len(v) > 1}


def choose_canonical(cases: list[Case]) -> Case:
    """Canónico = más documentos. Si empate: más campos llenos. Si empate: id menor."""
    def score(c: Case) -> tuple[int, int, int]:
        n_docs = len(c.documents) if c.documents else 0
        filled = sum(1 for f in (
            c.accionante, c.radicado_23_digitos, c.radicado_forest,
            c.asunto, c.derecho_vulnerado, c.observaciones, c.ciudad,
            c.fecha_ingreso, c.juzgado, c.sentido_fallo_1st,
        ) if f and str(f).strip())
        # Mayor = mejor. id menor = mejor (más antiguo), por eso -c.id
        return (n_docs, filled, -c.id)
    return max(cases, key=score)


def merge_fields(canonical: Case, child: Case) -> list[str]:
    """Llena campos vacíos del canónico con datos del hijo. Retorna lista de campos migrados."""
    migrated = []
    field_attrs = [a for a in dir(canonical) if not a.startswith("_") and not callable(getattr(canonical, a))]
    # Lista blanca: solo campos del CSV_FIELD_MAP
    for attr in Case.CSV_FIELD_MAP.values():
        canon_val = getattr(canonical, attr, None)
        child_val = getattr(child, attr, None)
        if (not canon_val or not str(canon_val).strip()) and child_val and str(child_val).strip():
            setattr(canonical, attr, child_val)
            migrated.append(attr)
    return migrated


def plan_merge(db):
    """Genera plan de merges sin ejecutar."""
    groups = find_duplicates(db)
    plan = []
    for (acc, rad), cases in groups.items():
        canonical = choose_canonical(cases)
        children = [c for c in cases if c.id != canonical.id]
        plan.append({
            "key": f"{acc[:40]} / {rad[:20]}",
            "canonical_id": canonical.id,
            "canonical_docs": len(canonical.documents) if canonical.documents else 0,
            "child_ids": [c.id for c in children],
            "child_docs_total": sum(len(c.documents) if c.documents else 0 for c in children),
            "canonical": canonical,
            "children": children,
        })
    return plan


def execute_merge(db, plan_items, apply_changes: bool):
    """Ejecuta el plan. Si apply_changes=False, solo muestra."""
    summary = {
        "groups_processed": 0,
        "docs_migrated": 0,
        "emails_migrated": 0,
        "extractions_migrated": 0,
        "audit_log_migrated": 0,
        "fields_filled": 0,
        "cases_deleted": 0,
    }

    # Usar SQL directo para evitar cascade automático de SQLAlchemy.
    # Fase 1: migrar todas las FK (docs, emails, etc.) con UPDATE directo.
    # Fase 2: eliminar children al final.
    from sqlalchemy import text

    to_delete_ids: list[int] = []

    for item in plan_items:
        canonical = item["canonical"]
        children = item["children"]

        print(f"\n[GROUP] {item['key']}")
        print(f"  Canónico: #{canonical.id} ({item['canonical_docs']} docs)")
        print(f"  Hijos a fusionar: {item['child_ids']}")

        for child in children:
            # Migrar campos vacíos
            migrated_fields = merge_fields(canonical, child)
            if migrated_fields:
                print(f"    #{child.id} → canónico: campos migrados {migrated_fields}")
                summary["fields_filled"] += len(migrated_fields)

            # Contar antes de UPDATE para reporte
            summary["docs_migrated"] += db.query(Document).filter(Document.case_id == child.id).count()
            summary["emails_migrated"] += db.query(Email).filter(Email.case_id == child.id).count()
            summary["extractions_migrated"] += db.query(Extraction).filter(Extraction.case_id == child.id).count()
            summary["audit_log_migrated"] += db.query(AuditLog).filter(AuditLog.case_id == child.id).count()

            if apply_changes:
                # UPDATEs directos SQL (sin ORM cascade)
                db.execute(text("UPDATE documents SET case_id=:c WHERE case_id=:ch"),
                           {"c": canonical.id, "ch": child.id})
                db.execute(text("UPDATE emails SET case_id=:c WHERE case_id=:ch"),
                           {"c": canonical.id, "ch": child.id})
                db.execute(text("UPDATE extractions SET case_id=:c WHERE case_id=:ch"),
                           {"c": canonical.id, "ch": child.id})
                db.execute(text("UPDATE audit_log SET case_id=:c WHERE case_id=:ch"),
                           {"c": canonical.id, "ch": child.id})
                db.execute(text("UPDATE compliance_tracking SET case_id=:c WHERE case_id=:ch"),
                           {"c": canonical.id, "ch": child.id})
                db.execute(text("UPDATE token_usage SET case_id=:c WHERE case_id=:ch"),
                           {"c": canonical.id, "ch": child.id})
                if 'pii_mappings' in [r[0] for r in db.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()]:
                    db.execute(text("UPDATE pii_mappings SET case_id=:c WHERE case_id=:ch"),
                               {"c": canonical.id, "ch": child.id})
                if 'privacy_stats' in [r[0] for r in db.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()]:
                    db.execute(text("UPDATE privacy_stats SET case_id=:c WHERE case_id=:ch"),
                               {"c": canonical.id, "ch": child.id})

                # Registrar merge en audit log
                db.add(AuditLog(
                    case_id=canonical.id,
                    field_name="case_merge",
                    old_value=f"merged_from_case_{child.id}",
                    new_value=f"canonical_preserved",
                    action="P1_MERGE_DUPLICATES",
                    source="scripts/cleanup_p1_merge_duplicates.py",
                ))
                db.flush()

            to_delete_ids.append(child.id)
            summary["cases_deleted"] += 1

        summary["groups_processed"] += 1

    # Fase 2: eliminar casos hijos (ahora que no tienen FKs apuntando a ellos)
    if apply_changes and to_delete_ids:
        db.execute(text(f"DELETE FROM cases WHERE id IN ({','.join(map(str, to_delete_ids))})"))
        db.commit()
        print(f"\n✅ Cambios aplicados. Casos eliminados: {len(to_delete_ids)}")
    else:
        db.rollback()
        print("\n⚠️  DRY-RUN: sin cambios. Re-ejecuta con --apply.")

    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Aplicar cambios (default: dry-run)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        plan = plan_merge(db)
        if not plan:
            print("Sin duplicados detectados. ✅")
            return
        print(f"Duplicados encontrados: {len(plan)} grupos")
        summary = execute_merge(db, plan, apply_changes=args.apply)
        print()
        print("=" * 60)
        print("RESUMEN")
        print("=" * 60)
        for k, v in summary.items():
            print(f"  {k}: {v}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
