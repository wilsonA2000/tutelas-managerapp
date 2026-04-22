"""v5.1 Sprint 1 — Reconciliacion de inconsistencias historicas.

Soluciona los 3 descuadres detectados en el diagnostico post v5.0:
1. Documents con case_id apuntando a DUPLICATE_MERGED (deben ir al canonico)
2. Emails con case_id apuntando a DUPLICATE_MERGED (idem)
3. Documents con file_path fuera del folder_path del caso (tras renames)

Uso:
    from backend.services.reconcile_db import reconcile_db
    result = reconcile_db(db, dry_run=True)   # reporte sin cambios
    result = reconcile_db(db, dry_run=False)  # aplica cambios
"""

import logging
import re
from pathlib import Path

from sqlalchemy.orm import Session

from backend.database.models import Case, Document, Email, AuditLog

logger = logging.getLogger("tutelas.reconcile")


def _find_canonical_for_merged(db: Session, merged_case: Case) -> Case | None:
    """Buscar el caso canonico al que deberia apuntar este DUPLICATE_MERGED.

    Estrategia:
    1. Si las observaciones contienen 'canonical=idN' (R3/R1 marcaron esto), usar N.
    2. Si no, buscar caso con mismo rad_corto y juzgado activo.
    3. Si tampoco, devolver None (dejar como esta, requerir revision manual).
    """
    # Estrategia 1: id marcado en observaciones/audit_log
    obs = merged_case.observaciones or ""
    m = re.search(r"(?:canonical=|canonico:|id=)\s*(\d+)", obs)
    if m:
        c = db.query(Case).filter(Case.id == int(m.group(1))).first()
        if c and c.processing_status != "DUPLICATE_MERGED":
            return c

    # Buscar en audit_log acciones de merge de este caso
    audit = db.query(AuditLog).filter(
        AuditLog.case_id == merged_case.id,
        AuditLog.action.in_(["MERGE", "R1_MERGE_V50", "R3_MERGE_V50", "DUPLICATE_MERGED"]),
    ).order_by(AuditLog.id.desc()).first()
    if audit:
        source = audit.source or ""
        mm = re.search(r"(?:canonical=|id)\s*(\d+)", source)
        if mm:
            c = db.query(Case).filter(Case.id == int(mm.group(1))).first()
            if c and c.processing_status != "DUPLICATE_MERGED":
                return c

    # Estrategia 2: mismo rad_corto (y juzgado si rad23 disponible)
    if merged_case.radicado_23_digitos:
        digits = re.sub(r"\D", "", merged_case.radicado_23_digitos)
        m23 = re.search(r"(20\d{2})(\d{5})\d{2}$", digits)
        if m23:
            rc = f"{m23.group(1)}-{m23.group(2)}"
            juzgado_code = digits[5:12] if len(digits) >= 12 else ""
            # Buscar casos activos con mismo rad23 primero
            cand_by_rad23 = db.query(Case).filter(
                Case.id != merged_case.id,
                Case.processing_status != "DUPLICATE_MERGED",
                Case.radicado_23_digitos.isnot(None),
            ).all()
            for c in cand_by_rad23:
                c_digits = re.sub(r"\D", "", c.radicado_23_digitos or "")
                if len(c_digits) >= 18 and c_digits[:20] == digits[:20]:
                    return c
            # Fallback: folder con mismo rad_corto + juzgado matching
            cand_by_folder = db.query(Case).filter(
                Case.id != merged_case.id,
                Case.processing_status != "DUPLICATE_MERGED",
                Case.folder_name.like(f"{rc[:4]}-{rc[5:]}%"),
            ).all()
            for c in cand_by_folder:
                if juzgado_code and c.radicado_23_digitos:
                    c_digits = re.sub(r"\D", "", c.radicado_23_digitos)
                    if len(c_digits) >= 12 and c_digits[5:12] != juzgado_code:
                        continue
                return c

    return None


def reconcile_db(db: Session, dry_run: bool = True) -> dict:
    """Reconciliar inconsistencias historicas.

    Args:
        dry_run: si True, solo reporta cambios sin aplicarlos.

    Returns:
        dict con conteos de cambios aplicados o detectados.
    """
    report = {
        "dry_run": dry_run,
        "docs_en_duplicate_merged": 0,
        "docs_reubicados": 0,
        "docs_sin_canonico": [],
        "emails_en_duplicate_merged": 0,
        "emails_reubicados": 0,
        "emails_sin_canonico": [],
        "file_paths_desalineados": 0,
        "file_paths_corregidos": 0,
    }

    # ─────────────────────────────────────────────────────────────────
    # Fase 1: Documents con case_id apuntando a DUPLICATE_MERGED
    # ─────────────────────────────────────────────────────────────────
    merged_cases = db.query(Case).filter(Case.processing_status == "DUPLICATE_MERGED").all()
    canonical_map = {}  # merged_id -> canonical_case

    for mc in merged_cases:
        canon = _find_canonical_for_merged(db, mc)
        if canon:
            canonical_map[mc.id] = canon

    docs_in_merged = db.query(Document).filter(
        Document.case_id.in_([mc.id for mc in merged_cases])
    ).all() if merged_cases else []
    report["docs_en_duplicate_merged"] = len(docs_in_merged)

    for doc in docs_in_merged:
        canon = canonical_map.get(doc.case_id)
        if not canon:
            report["docs_sin_canonico"].append({
                "doc_id": doc.id, "case_id": doc.case_id, "filename": doc.filename,
            })
            continue
        if dry_run:
            report["docs_reubicados"] += 1
            continue
        old_case_id = doc.case_id
        doc.case_id = canon.id
        # Actualizar file_path si la carpeta del canonico existe
        if canon.folder_path and doc.file_path:
            old_folder = Path(doc.file_path).parent
            new_path = Path(canon.folder_path) / Path(doc.file_path).name
            if old_folder != Path(canon.folder_path):
                # Mover archivo fisico si existe y no colisiona
                if Path(doc.file_path).exists() and not new_path.exists():
                    try:
                        Path(doc.file_path).rename(new_path)
                        doc.file_path = str(new_path)
                    except Exception as e:
                        logger.warning("Mover doc %d fallo: %s", doc.id, e)
        db.add(AuditLog(
            case_id=canon.id, field_name="case_id",
            old_value=str(old_case_id), new_value=str(canon.id),
            action="RECONCILE_V51", source="reconcile_db",
        ))
        report["docs_reubicados"] += 1

    # ─────────────────────────────────────────────────────────────────
    # Fase 2: Emails con case_id apuntando a DUPLICATE_MERGED
    # ─────────────────────────────────────────────────────────────────
    emails_in_merged = db.query(Email).filter(
        Email.case_id.in_([mc.id for mc in merged_cases])
    ).all() if merged_cases else []
    report["emails_en_duplicate_merged"] = len(emails_in_merged)

    for em in emails_in_merged:
        canon = canonical_map.get(em.case_id)
        if not canon:
            report["emails_sin_canonico"].append({
                "email_id": em.id, "case_id": em.case_id, "subject": (em.subject or "")[:50],
            })
            continue
        if dry_run:
            report["emails_reubicados"] += 1
            continue
        em.case_id = canon.id
        report["emails_reubicados"] += 1

    # ─────────────────────────────────────────────────────────────────
    # Fase 3: Documents con file_path fuera de folder_path del caso
    # ─────────────────────────────────────────────────────────────────
    misaligned = db.query(Document, Case).join(Case, Document.case_id == Case.id).filter(
        Document.file_path.isnot(None),
        Case.folder_path.isnot(None),
    ).all()

    for doc, case in misaligned:
        if not doc.file_path or not case.folder_path:
            continue
        if doc.file_path.startswith(case.folder_path):
            continue
        report["file_paths_desalineados"] += 1
        # Intentar corregir: construir nuevo path dentro de folder_path
        new_path = Path(case.folder_path) / Path(doc.file_path).name
        if dry_run:
            report["file_paths_corregidos"] += 1
            continue
        old_path = Path(doc.file_path)
        # Si archivo existe en el path viejo, moverlo
        if old_path.exists() and not new_path.exists():
            try:
                new_path.parent.mkdir(parents=True, exist_ok=True)
                old_path.rename(new_path)
                doc.file_path = str(new_path)
                report["file_paths_corregidos"] += 1
            except Exception as e:
                logger.warning("Mover path doc %d fallo: %s", doc.id, e)
        elif new_path.exists():
            # Archivo ya esta en destino correcto, solo actualizar DB
            doc.file_path = str(new_path)
            report["file_paths_corregidos"] += 1

    if not dry_run:
        db.commit()

    return report
