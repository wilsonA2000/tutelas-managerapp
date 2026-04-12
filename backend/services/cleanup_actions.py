"""Cleanup actions v5.0: operaciones mutadoras.

Cada accion es idempotente y registrable en AuditLog. Se invocan desde
cleanup_service.py (orquestador) o directamente via endpoint/CLI.

F2: backfill_content_hash — completa MD5 de docs sin hash
F4: backfill_emails_md — genera .md faltantes y vincula al email
F3: batch_move_mismatched, merge_identity_groups — reasignacion segura
v5.0: purge_duplicates, merge_forest_fragments, backfill_radicado_23d

Todas las funciones DEVUELVEN estadisticas en vez de loggearlas.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.database.models import AuditLog, Case, Document, Email
from backend.extraction.pipeline import compute_file_hash

logger = logging.getLogger("tutelas.cleanup_actions")


# ============================================================
# F2: backfill content_hash
# ============================================================

def backfill_content_hash(
    db: Session,
    batch_size: int = 100,
    dry_run: bool = False,
    progress_cb = None,
) -> dict[str, Any]:
    """Backfill MD5 hash para documents sin file_hash.

    Idempotente: skip docs que ya tienen hash.
    Commit por batches para no explotar la transaccion.

    Args:
        db: sesion SQLAlchemy
        batch_size: commit cada N docs
        dry_run: si True, no escribe nada (solo cuenta)
        progress_cb: callback(current, total) para progress

    Returns:
        dict con estadisticas: total, hashed, skipped, missing_file, errors, duration_s
    """
    start = datetime.utcnow()
    stats: dict[str, Any] = {
        "total_candidates": 0,
        "hashed": 0,
        "skipped_already_has_hash": 0,
        "missing_file_on_disk": 0,
        "empty_file_path": 0,
        "errors": 0,
        "dry_run": dry_run,
        "duration_s": 0.0,
    }

    # Candidatos: docs sin hash (empty string o NULL)
    candidates = db.query(Document).filter(
        (Document.file_hash == "") | (Document.file_hash.is_(None))
    ).all()
    stats["total_candidates"] = len(candidates)

    if not candidates:
        stats["duration_s"] = (datetime.utcnow() - start).total_seconds()
        return stats

    logger.info("F2 backfill: %d docs sin hash", len(candidates))

    processed = 0
    for doc in candidates:
        try:
            if not doc.file_path:
                stats["empty_file_path"] += 1
                processed += 1
                continue

            path = Path(doc.file_path)
            if not path.exists():
                stats["missing_file_on_disk"] += 1
                processed += 1
                continue

            file_hash = compute_file_hash(str(path))
            if not file_hash:
                stats["errors"] += 1
                processed += 1
                continue

            if not dry_run:
                doc.file_hash = file_hash
            stats["hashed"] += 1
            processed += 1

            # Commit por batches
            if not dry_run and processed % batch_size == 0:
                db.commit()
                logger.info("F2 batch commit: %d/%d", processed, len(candidates))

            if progress_cb:
                try:
                    progress_cb(processed, len(candidates))
                except Exception:
                    pass
        except Exception as e:
            logger.error("F2 error doc_id=%d: %s", doc.id, e)
            stats["errors"] += 1
            processed += 1

    # Commit final
    if not dry_run:
        db.commit()
        # AuditLog con resumen
        try:
            # case_id es NOT NULL en el schema. Usamos un case "marcador global"
            # (el primero) para entradas de cleanup que no son especificas de un caso.
            _marker_case = db.query(Case.id).first()
            _marker_id = _marker_case[0] if _marker_case else 0
            db.add(AuditLog(
                case_id=_marker_id,
                field_name="content_hash",
                action="CLEANUP_HASH",
                source="cleanup_actions:backfill_content_hash",
                new_value=f"hashed={stats['hashed']} missing_file={stats['missing_file_on_disk']} empty_path={stats['empty_file_path']}",
            ))
            db.commit()
        except Exception as e:
            logger.warning("F2 audit log write failed: %s", e)

    stats["duration_s"] = round((datetime.utcnow() - start).total_seconds(), 1)
    return stats


# ============================================================
# F4: backfill emails .md (genera .md faltantes + vincula)
# ============================================================

def backfill_emails_md(db: Session, dry_run: bool = False) -> dict[str, Any]:
    """Genera archivos .md de emails que aun no tienen uno.

    Reusa save_email_md() de gmail_monitor, que ya vincula por email_id
    gracias a F0b. Solo procesa emails con case_id asignado y body_preview.

    Idempotente: save_email_md() retorna None si el .md ya existe en disco.

    Returns:
        dict con stats: total_emails, generated, skipped_existing, errors
    """
    from backend.email.gmail_monitor import save_email_md

    start = datetime.utcnow()
    stats: dict[str, Any] = {
        "total_emails_with_case": 0,
        "generated": 0,
        "skipped_no_body": 0,
        "skipped_no_folder": 0,
        "skipped_existing_md": 0,
        "errors": 0,
        "dry_run": dry_run,
    }

    # Solo emails vinculados a caso con body_preview
    emails = db.query(Email).filter(
        Email.case_id.isnot(None),
        Email.body_preview.isnot(None),
        Email.body_preview != "",
    ).all()
    stats["total_emails_with_case"] = len(emails)

    if not emails:
        stats["duration_s"] = (datetime.utcnow() - start).total_seconds()
        return stats

    logger.info("F4 backfill: %d emails candidatos para generar .md", len(emails))

    for em in emails:
        try:
            case = db.query(Case).filter(Case.id == em.case_id).first()
            if not case or not case.folder_path:
                stats["skipped_no_folder"] += 1
                continue

            folder = Path(case.folder_path)
            if not folder.exists():
                stats["skipped_no_folder"] += 1
                continue

            if dry_run:
                stats["generated"] += 1
                continue

            date_str = em.date_received.strftime("%a, %d %b %Y %H:%M") if em.date_received else ""
            result = save_email_md(
                folder,
                {
                    "subject": em.subject or "",
                    "sender": em.sender or "",
                    "date": date_str,
                    "folder_name": case.folder_name,
                },
                em.body_preview,
                em.attachments or [],
                db=db,
                case_id=case.id,
                email_id=em.id,
                email_message_id=em.message_id,
            )
            if result:
                stats["generated"] += 1
            else:
                # save_email_md retorna None si ya existe
                stats["skipped_existing_md"] += 1
        except Exception as e:
            logger.error("F4 error email_id=%d: %s", em.id, e)
            stats["errors"] += 1

    if not dry_run:
        db.commit()
        try:
            # case_id es NOT NULL en el schema. Usamos un case "marcador global"
            # (el primero) para entradas de cleanup que no son especificas de un caso.
            _marker_case = db.query(Case.id).first()
            _marker_id = _marker_case[0] if _marker_case else 0
            db.add(AuditLog(
                case_id=_marker_id,
                field_name="emails_md",
                action="CLEANUP_EMAIL_MD",
                source="cleanup_actions:backfill_emails_md",
                new_value=f"generated={stats['generated']} existing={stats['skipped_existing_md']}",
            ))
            db.commit()
        except Exception as e:
            logger.warning("F4 audit log write failed: %s", e)

    stats["duration_s"] = round((datetime.utcnow() - start).total_seconds(), 1)
    return stats


# ============================================================
# F3b: batch_move_no_pertenece (reasignacion individual con sibling rule)
# ============================================================

def batch_move_no_pertenece(
    db: Session,
    dry_run: bool = True,
    min_confidence: str = "ALTA",
) -> dict[str, Any]:
    """Mueve documentos NO_PERTENECE a su caso correcto sugerido.

    Reusa api_suggest_target logic inline para evitar dependencia del router.
    Solo mueve si hay sugerencia con confidence >= min_confidence.
    La regla "hermanos viajan juntos" aplica automaticamente via sibling_mover.

    Args:
        db: sesion SQLAlchemy
        dry_run: si True, solo cuenta sin mover
        min_confidence: 'ALTA' | 'MEDIA' | 'BAJA'

    Returns:
        dict con estadisticas + lista de moves ejecutados/propuestos
    """
    import re
    from backend.services.sibling_mover import move_document_or_package

    start = datetime.utcnow()
    stats: dict[str, Any] = {
        "dry_run": dry_run,
        "total_no_pertenece": 0,
        "moved": 0,
        "skipped_no_suggestion": 0,
        "skipped_low_confidence": 0,
        "errors": 0,
        "actions": [],
    }

    CONFIDENCE_RANK = {"ALTA": 3, "MEDIA": 2, "BAJA": 1}
    min_rank = CONFIDENCE_RANK.get(min_confidence, 3)

    candidates = db.query(Document).filter(Document.verificacion == "NO_PERTENECE").all()
    stats["total_no_pertenece"] = len(candidates)

    # Precargar todos los casos para reusar
    all_cases = db.query(Case).all()
    cases_by_id = {c.id: c for c in all_cases}

    already_moved_ids: set[int] = set()  # evita mover hermanos 2 veces

    for doc in candidates:
        if doc.id in already_moved_ids:
            continue

        try:
            text = (doc.extracted_text or "")[:10000].upper()
            detalle = doc.verificacion_detalle or ""
            source_case = cases_by_id.get(doc.case_id)
            if not source_case:
                stats["errors"] += 1
                continue

            source_rad23 = re.sub(r'[\s\-\.]', '', (source_case.radicado_23_digitos or ''))

            # Estrategia A: radicado 23d en texto
            rad23_matches = re.findall(r'(68[\d]{17,21})', re.sub(r'[\s\-\.]', '', text))
            suggestion = None
            for rad23 in rad23_matches:
                if len(rad23) >= 20 and rad23 != source_rad23:
                    for c in all_cases:
                        if c.id == doc.case_id:
                            continue
                        c_rad = re.sub(r'[\s\-\.]', '', c.radicado_23_digitos or '')
                        if c_rad and len(c_rad) >= 15 and c_rad[-12:] == rad23[-12:]:
                            suggestion = {"case_id": c.id, "confidence": "ALTA", "reason": f"rad23={rad23}"}
                            break
                    if suggestion:
                        break

            # Estrategia B: radicado corto en verificacion_detalle
            if not suggestion:
                m = re.search(r'Radicado\s+(20\d{2})[-\s]?0*(\d{2,5})', detalle)
                if m:
                    target_seq = m.group(2).zfill(5)
                    pattern = f"{m.group(1)}-{target_seq}"
                    for c in all_cases:
                        if c.id == doc.case_id:
                            continue
                        if c.folder_name and pattern in c.folder_name:
                            suggestion = {"case_id": c.id, "confidence": "MEDIA", "reason": f"rad_corto={pattern}"}
                            break

            if not suggestion:
                stats["skipped_no_suggestion"] += 1
                continue

            if CONFIDENCE_RANK.get(suggestion["confidence"], 0) < min_rank:
                stats["skipped_low_confidence"] += 1
                continue

            target_id = suggestion["case_id"]

            if dry_run:
                stats["moved"] += 1
                stats["actions"].append({
                    "doc_id": doc.id,
                    "filename": (doc.filename or "")[:60],
                    "source_case_id": doc.case_id,
                    "target_case_id": target_id,
                    "confidence": suggestion["confidence"],
                    "reason": suggestion["reason"],
                })
            else:
                result = move_document_or_package(db, doc.id, target_id, reason="cleanup_no_pertenece")
                if result.get("errors"):
                    stats["errors"] += 1
                else:
                    moved_ids = result.get("moved_ids", [])
                    stats["moved"] += len(moved_ids)
                    already_moved_ids.update(moved_ids)
                    stats["actions"].append({
                        "doc_id": doc.id,
                        "moved_ids": moved_ids,
                        "package_mode": result.get("package_mode", False),
                        "target_case_id": target_id,
                        "confidence": suggestion["confidence"],
                    })

        except Exception as e:
            logger.error("batch_move_no_pertenece error doc_id=%d: %s", doc.id, e)
            stats["errors"] += 1

    if not dry_run:
        db.commit()

    stats["duration_s"] = round((datetime.utcnow() - start).total_seconds(), 1)
    return stats


# ============================================================
# F3: merge_identity_groups (usa la regla de identidad)
# ============================================================

def merge_identity_groups(
    db: Session,
    dry_run: bool = True,
    only_auto_mergeable: bool = True,
) -> dict[str, Any]:
    """Merge casos que comparten la misma identidad (radicado_23d + accionante + tipo_rep).

    Regla estricta: SOLO fusiona si todos los casos del grupo tienen radicado_23d
    no-vacio y coincidente. Los grupos manual_review NO se tocan.

    El caso "canonico" es el que tiene mas documents. El resto de casos mueven
    sus docs (con sibling_mover para preservar paquetes), sus emails, sus
    extractions y sus audit logs al canonico. Luego el caso duplicado queda vacio
    y se marca processing_status='DUPLICATE_MERGED'.

    Returns:
        dict con stats y lista de acciones propuestas/ejecutadas.
    """
    from backend.services.cleanup_diagnosis import diagnose
    from backend.services.sibling_mover import move_document_or_package

    start = datetime.utcnow()
    stats: dict[str, Any] = {
        "dry_run": dry_run,
        "groups_processed": 0,
        "cases_merged": 0,
        "docs_moved": 0,
        "emails_reassigned": 0,
        "errors": 0,
        "actions": [],
    }

    # Obtener grupos del diagnostico
    diag = diagnose(db)
    ig = diag.get("identity_groups", {})
    groups = ig.get("auto_mergeable", [])

    if not only_auto_mergeable:
        groups = groups + ig.get("manual_review", [])

    logger.info("F3 merge: %d grupos candidatos", len(groups))

    for group in groups:
        try:
            case_ids = group["case_ids"]
            cases = db.query(Case).filter(Case.id.in_(case_ids)).all()
            if len(cases) < 2:
                continue

            # Canonico = caso con mas documents (o el primero en caso de empate)
            canonical = max(cases, key=lambda c: (len(c.documents), -c.id))
            others = [c for c in cases if c.id != canonical.id]

            action: dict[str, Any] = {
                "group_key": f"{group.get('radicado_23d')}/{group.get('accionante')[:30]}/{group.get('tipo_representacion')}",
                "canonical_id": canonical.id,
                "canonical_folder": (canonical.folder_name or "")[:60],
                "canonical_docs_before": len(canonical.documents),
                "merge_from": [
                    {"id": c.id, "folder": (c.folder_name or "")[:60], "docs": len(c.documents)}
                    for c in others
                ],
                "docs_moved": 0,
                "emails_reassigned": 0,
            }

            if not dry_run:
                # Mover documents de cada otro al canonico
                for other in others:
                    # Snapshot de los docs antes de mover
                    other_doc_ids = [d.id for d in other.documents]
                    moved_this = 0
                    for doc_id in other_doc_ids:
                        result = move_document_or_package(
                            db, doc_id, canonical.id, reason="cleanup_merge"
                        )
                        if not result.get("errors"):
                            moved_this += len(result.get("moved_ids", []))
                    action["docs_moved"] = moved_this
                    stats["docs_moved"] += moved_this

                    # Reasignar emails del otro caso al canonico
                    emails_to_move = db.query(Email).filter(Email.case_id == other.id).all()
                    for em in emails_to_move:
                        em.case_id = canonical.id
                    action["emails_reassigned"] += len(emails_to_move)
                    stats["emails_reassigned"] += len(emails_to_move)

                    # Marcar el caso duplicado como fusionado
                    other.processing_status = "DUPLICATE_MERGED"

                    # AuditLog
                    db.add(AuditLog(
                        case_id=canonical.id,
                        field_name="merge",
                        action="CLEANUP_MERGE",
                        source="cleanup_actions:merge_identity_groups",
                        old_value=f"case_id={other.id} folder={other.folder_name[:60] if other.folder_name else ''}",
                        new_value=f"merged_into case_id={canonical.id}",
                    ))

                db.commit()
                stats["cases_merged"] += len(others)
            else:
                # En dry_run solo cuenta lo que moveria
                for other in others:
                    action["docs_moved"] += len(other.documents)
                    action["emails_reassigned"] += db.query(Email).filter(Email.case_id == other.id).count()
                stats["docs_moved"] += action["docs_moved"]
                stats["emails_reassigned"] += action["emails_reassigned"]
                stats["cases_merged"] += len(others)

            stats["actions"].append(action)
            stats["groups_processed"] += 1

        except Exception as e:
            logger.error("F3 error group %s: %s", group.get("radicado_23d"), e, exc_info=True)
            stats["errors"] += 1
            if not dry_run:
                db.rollback()

    stats["duration_s"] = round((datetime.utcnow() - start).total_seconds(), 1)
    return stats


# ============================================================
# v5.0: Purga de duplicados por hash
# ============================================================

def purge_duplicates(
    db: Session,
    scope: str = "intra",
    dry_run: bool = True,
) -> dict[str, Any]:
    """Purga documentos duplicados por hash MD5.

    Args:
        scope: 'intra' (dentro del mismo caso, seguro),
               'inter' (entre casos, solo si uno es NO_PERTENECE),
               'all' (ambos)
        dry_run: si True, solo cuenta sin eliminar

    Returns:
        dict con estadisticas y acciones.
    """
    from collections import defaultdict
    import shutil

    start = datetime.utcnow()
    stats: dict[str, Any] = {
        "dry_run": dry_run,
        "scope": scope,
        "intra_removed": 0,
        "inter_removed": 0,
        "errors": 0,
        "actions": [],
    }

    docs = db.query(Document).filter(
        Document.file_hash.isnot(None),
        Document.file_hash != "",
    ).all()

    hash_groups: dict[str, list[Document]] = defaultdict(list)
    for d in docs:
        hash_groups[d.file_hash].append(d)

    for h, group in hash_groups.items():
        if len(group) < 2:
            continue

        case_ids = {d.case_id for d in group}

        # INTRA-CASO: todos en el mismo caso
        if len(case_ids) == 1 and scope in ("intra", "all"):
            canonical = min(group, key=lambda d: (d.email_id is None, d.id))
            for d in group:
                if d.id == canonical.id:
                    continue
                if not dry_run:
                    if d.file_path:
                        src = Path(d.file_path)
                        if src.exists():
                            dup_dir = src.parent / "_duplicados"
                            dup_dir.mkdir(exist_ok=True)
                            try:
                                shutil.move(str(src), str(dup_dir / src.name))
                            except Exception as e:
                                logger.warning("No se pudo mover %s: %s", src, e)
                    db.delete(d)
                stats["intra_removed"] += 1
                if len(stats["actions"]) < 50:
                    stats["actions"].append({
                        "type": "intra",
                        "removed_doc_id": d.id,
                        "kept_doc_id": canonical.id,
                        "filename": (d.filename or "")[:60],
                        "case_id": d.case_id,
                    })

        # INTER-CASO: en diferentes casos, solo eliminar NO_PERTENECE
        elif len(case_ids) > 1 and scope in ("inter", "all"):
            no_pert = [d for d in group if d.verificacion == "NO_PERTENECE"]
            for d in no_pert:
                if not dry_run:
                    if d.file_path:
                        src = Path(d.file_path)
                        if src.exists():
                            dup_dir = src.parent / "_duplicados"
                            dup_dir.mkdir(exist_ok=True)
                            try:
                                shutil.move(str(src), str(dup_dir / src.name))
                            except Exception as e:
                                logger.warning("No se pudo mover %s: %s", src, e)
                    db.delete(d)
                stats["inter_removed"] += 1
                if len(stats["actions"]) < 50:
                    stats["actions"].append({
                        "type": "inter",
                        "removed_doc_id": d.id,
                        "filename": (d.filename or "")[:60],
                        "case_id": d.case_id,
                        "reason": "NO_PERTENECE + duplicado en otro caso",
                    })

    if not dry_run:
        db.commit()
        _marker = db.query(Case.id).first()
        _mid = _marker[0] if _marker else 0
        db.add(AuditLog(
            case_id=_mid,
            field_name="duplicates",
            action="CLEANUP_PURGE_DUPLICATES",
            source="cleanup_actions:purge_duplicates",
            new_value=f"scope={scope} intra={stats['intra_removed']} inter={stats['inter_removed']}",
        ))
        db.commit()

    stats["duration_s"] = round((datetime.utcnow() - start).total_seconds(), 1)
    return stats


# ============================================================
# v5.0: Fusion de fragmentos FOREST
# ============================================================

def merge_forest_fragments(
    db: Session,
    dry_run: bool = True,
    min_confidence: str = "ALTA",
) -> dict[str, Any]:
    """Fusiona fragmentos FOREST con su caso padre detectado.

    Usa detect_forest_fragments() para encontrar fragmentos y su caso padre sugerido.
    Solo fusiona si la confianza >= min_confidence.

    Returns:
        dict con estadisticas y acciones.
    """
    from backend.services.cleanup_diagnosis import detect_forest_fragments
    from backend.services.sibling_mover import move_document_or_package

    CONF_RANK = {"ALTA": 3, "MEDIA": 2, "BAJA": 1}
    min_rank = CONF_RANK.get(min_confidence, 3)

    start = datetime.utcnow()
    stats: dict[str, Any] = {
        "dry_run": dry_run,
        "min_confidence": min_confidence,
        "fragments_found": 0,
        "fragments_merged": 0,
        "docs_moved": 0,
        "emails_reassigned": 0,
        "skipped_no_parent": 0,
        "skipped_low_confidence": 0,
        "errors": 0,
        "actions": [],
    }

    fragments = detect_forest_fragments(db)
    stats["fragments_found"] = len(fragments)

    for frag in fragments:
        parent_id = frag.get("suggested_parent_case_id")
        confidence = frag.get("confidence")

        if not parent_id:
            stats["skipped_no_parent"] += 1
            continue

        if CONF_RANK.get(confidence, 0) < min_rank:
            stats["skipped_low_confidence"] += 1
            continue

        frag_case_id = frag["fragment_case_id"]
        frag_case = db.query(Case).filter(Case.id == frag_case_id).first()
        parent_case = db.query(Case).filter(Case.id == parent_id).first()

        if not frag_case or not parent_case:
            stats["errors"] += 1
            continue

        action = {
            "fragment_id": frag_case_id,
            "fragment_folder": (frag_case.folder_name or "")[:60],
            "parent_id": parent_id,
            "parent_folder": (parent_case.folder_name or "")[:60],
            "confidence": confidence,
            "docs_moved": 0,
            "emails_reassigned": 0,
        }

        if dry_run:
            doc_count = db.query(Document).filter(Document.case_id == frag_case_id).count()
            email_count = db.query(Email).filter(Email.case_id == frag_case_id).count()
            action["docs_moved"] = doc_count
            action["emails_reassigned"] = email_count
            stats["docs_moved"] += doc_count
            stats["emails_reassigned"] += email_count
            stats["fragments_merged"] += 1
        else:
            try:
                frag_docs = db.query(Document).filter(Document.case_id == frag_case_id).all()
                moved = 0
                for doc in frag_docs:
                    result = move_document_or_package(db, doc.id, parent_id, reason="cleanup_forest_merge")
                    if not result.get("errors"):
                        moved += len(result.get("moved_ids", []))
                action["docs_moved"] = moved
                stats["docs_moved"] += moved

                frag_emails = db.query(Email).filter(Email.case_id == frag_case_id).all()
                for em in frag_emails:
                    em.case_id = parent_id
                action["emails_reassigned"] = len(frag_emails)
                stats["emails_reassigned"] += len(frag_emails)

                frag_case.processing_status = "DUPLICATE_MERGED"

                db.add(AuditLog(
                    case_id=parent_id,
                    field_name="merge",
                    action="CLEANUP_FOREST_MERGE",
                    source="cleanup_actions:merge_forest_fragments",
                    old_value=f"fragment_id={frag_case_id} folder={frag_case.folder_name[:60] if frag_case.folder_name else ''}",
                    new_value=f"merged_into parent_id={parent_id} docs={moved}",
                ))

                db.commit()
                stats["fragments_merged"] += 1
            except Exception as e:
                logger.error("merge_forest error frag=%d: %s", frag_case_id, e)
                stats["errors"] += 1
                db.rollback()

        stats["actions"].append(action)

    stats["duration_s"] = round((datetime.utcnow() - start).total_seconds(), 1)
    return stats


# ============================================================
# v5.0: Backfill radicado_23_digitos desde documentos
# ============================================================

def backfill_radicado_23d(
    db: Session,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Busca y asigna radicado_23_digitos desde el texto de los documentos.

    Solo asigna automaticamente si el radicado se encuentra en 2+ documentos
    del caso (confianza ALTA). Los de 1 doc se reportan como sugerencia.

    Returns:
        dict con estadisticas y acciones.
    """
    import re
    from backend.services.cleanup_diagnosis import detect_incomplete_radicados

    start = datetime.utcnow()
    stats: dict[str, Any] = {
        "dry_run": dry_run,
        "auto_assigned": 0,
        "suggested_only": 0,
        "normalized": 0,
        "errors": 0,
        "actions": [],
    }

    result = detect_incomplete_radicados(db)

    for sug in result.get("suggestions", []):
        if sug["confidence"] == "ALTA":
            case = db.query(Case).filter(Case.id == sug["case_id"]).first()
            if not case:
                continue

            rad = sug["suggested_rad23"]
            if len(rad) >= 23:
                formatted = f"{rad[:16]}-{rad[16:21]}-{rad[21:23]}"
            elif len(rad) >= 20:
                formatted = rad
            else:
                formatted = rad

            if not dry_run:
                old_val = case.radicado_23_digitos or ""
                case.radicado_23_digitos = formatted
                db.add(AuditLog(
                    case_id=case.id,
                    field_name="radicado_23_digitos",
                    action="CLEANUP_BACKFILL_RAD23",
                    source="cleanup_actions:backfill_radicado_23d",
                    old_value=old_val,
                    new_value=formatted,
                ))

            stats["auto_assigned"] += 1
            stats["actions"].append({
                "case_id": sug["case_id"],
                "folder_name": sug["folder_name"],
                "assigned_rad23": formatted,
                "found_in_docs": sug["found_in_docs"],
                "confidence": "ALTA",
                "type": "auto",
            })
        else:
            stats["suggested_only"] += 1
            stats["actions"].append({
                "case_id": sug["case_id"],
                "folder_name": sug["folder_name"],
                "suggested_rad23": sug["suggested_rad23"],
                "found_in_docs": sug["found_in_docs"],
                "confidence": sug["confidence"],
                "type": "suggestion",
            })

    for mal in result.get("malformed", []):
        case = db.query(Case).filter(Case.id == mal["case_id"]).first()
        if not case or not case.radicado_23_digitos:
            continue

        digits = re.sub(r"\D", "", case.radicado_23_digitos)
        if 20 <= len(digits) <= 25:
            if len(digits) >= 23:
                formatted = f"{digits[:16]}-{digits[16:21]}-{digits[21:23]}"
            else:
                formatted = digits

            if formatted != case.radicado_23_digitos:
                if not dry_run:
                    old_val = case.radicado_23_digitos
                    case.radicado_23_digitos = formatted
                    db.add(AuditLog(
                        case_id=case.id,
                        field_name="radicado_23_digitos",
                        action="CLEANUP_NORMALIZE_RAD23",
                        source="cleanup_actions:backfill_radicado_23d",
                        old_value=old_val,
                        new_value=formatted,
                    ))

                stats["normalized"] += 1
                stats["actions"].append({
                    "case_id": mal["case_id"],
                    "folder_name": mal["folder_name"],
                    "old_rad23": case.radicado_23_digitos,
                    "new_rad23": formatted,
                    "type": "normalize",
                })

    if not dry_run:
        db.commit()

    stats["duration_s"] = round((datetime.utcnow() - start).total_seconds(), 1)
    return stats
