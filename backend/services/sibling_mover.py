"""Sibling mover v4.8: mover paquetes email inmutables entre casos.

Implementa la regla "hermanos viajan juntos":
- Si un Document tiene email_id != NULL, mover UNO implica mover TODOS los
  hermanos del mismo paquete.
- La operacion es atomica: si falla en medio, se hace rollback completo
  (tanto DB como archivos en disco).

Uso desde endpoints:
    from backend.services.sibling_mover import move_document_or_package
    result = move_document_or_package(db, doc_id, target_case_id)
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.database.models import AuditLog, Case, Document
from backend.services.provenance_service import get_siblings

logger = logging.getLogger("tutelas.sibling_mover")


def move_document_or_package(
    db: Session,
    doc_id: int,
    target_case_id: int,
    reason: str = "manual_move",
) -> dict[str, Any]:
    """Mueve un documento o su paquete completo a otro caso.

    Regla de v4.8: si el doc tiene email_id, TODOS sus hermanos se mueven.
    Si el doc no tiene email_id (legacy), solo se mueve ese doc.

    Args:
        db: sesion SQLAlchemy (el caller hace commit)
        doc_id: ID del doc origen
        target_case_id: case destino
        reason: string para AuditLog

    Returns:
        dict con {moved_ids, package_mode, source_case_id, target_case_id, errors}
    """
    result: dict[str, Any] = {
        "doc_id": doc_id,
        "target_case_id": target_case_id,
        "moved_ids": [],
        "package_mode": False,
        "source_case_id": None,
        "errors": [],
        "file_moves": [],
    }

    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        result["errors"].append(f"Document {doc_id} no existe")
        return result

    target = db.query(Case).filter(Case.id == target_case_id).first()
    if not target:
        result["errors"].append(f"Target case {target_case_id} no existe")
        return result

    result["source_case_id"] = doc.case_id

    # Decidir si mover solo el doc o el paquete completo
    if doc.email_id is not None:
        # Modo paquete: todos los hermanos viajan juntos
        siblings = get_siblings(db, doc_id)
        result["package_mode"] = True
        result["email_id"] = doc.email_id
        docs_to_move = siblings
        logger.info(
            "Package mode: doc_id=%d tiene email_id=%d, moviendo %d hermanos",
            doc_id, doc.email_id, len(siblings),
        )
    else:
        # Modo individual: solo este doc
        docs_to_move = [doc]
        logger.info("Solo mode: doc_id=%d sin email_id (legacy)", doc_id)

    # Validar que target tenga folder_path
    if not target.folder_path:
        result["errors"].append(f"Target case {target_case_id} no tiene folder_path")
        return result
    target_folder = Path(target.folder_path)
    if not target_folder.exists():
        result["errors"].append(f"Target folder no existe: {target_folder}")
        return result

    # Mover archivos en disco + actualizar DB
    # Rollback manual si algo falla a mitad
    moved_disk: list[tuple[Path, Path]] = []  # (new, old) para rollback

    try:
        for d in docs_to_move:
            if not d.file_path:
                continue
            old_path = Path(d.file_path)
            if not old_path.exists():
                logger.warning("File not found on disk: %s (skip move)", old_path)
                # Actualizar DB igualmente
                _update_doc_db_only(d, target_case_id, d.case_id, reason)
                result["moved_ids"].append(d.id)
                continue

            new_path = target_folder / d.filename
            # Si ya existe un archivo con mismo nombre en destino, agregar sufijo
            counter = 1
            original_new_path = new_path
            while new_path.exists():
                stem = original_new_path.stem
                suffix = original_new_path.suffix
                new_path = target_folder / f"{stem}_moved{counter}{suffix}"
                counter += 1

            shutil.move(str(old_path), str(new_path))
            moved_disk.append((new_path, old_path))

            old_case_id = d.case_id
            d.file_path = str(new_path)
            d.case_id = target_case_id
            d.verificacion = "OK"
            d.verificacion_detalle = f"Movido desde caso {old_case_id} (paquete)" if result["package_mode"] else f"Movido desde caso {old_case_id}"

            # AuditLog
            db.add(AuditLog(
                case_id=target_case_id,
                field_name="documento",
                old_value=f"case_id={old_case_id} doc_id={d.id}",
                new_value=f"case_id={target_case_id} doc_id={d.id}",
                action="CLEANUP_MOVE" if reason.startswith("cleanup") else "MANUAL_MOVE",
                source=f"sibling_mover:{reason}",
            ))
            result["moved_ids"].append(d.id)
            result["file_moves"].append({
                "doc_id": d.id,
                "old_path": str(old_path),
                "new_path": str(new_path),
            })

    except Exception as e:
        # Rollback: restaurar archivos en disco
        logger.error("Error moviendo paquete, rollback disk: %s", e)
        for new_path, old_path in moved_disk:
            try:
                if new_path.exists() and not old_path.exists():
                    shutil.move(str(new_path), str(old_path))
            except Exception as rollback_err:
                logger.error("Rollback disk fallo para %s: %s", new_path, rollback_err)
        # Rollback DB (el caller haria rollback, pero rollback aqui por seguridad)
        db.rollback()
        result["errors"].append(str(e))
        return result

    return result


def _update_doc_db_only(doc: Document, new_case_id: int, old_case_id: int, reason: str):
    """Actualiza solo la DB del documento (para casos donde el archivo no existe)."""
    doc.case_id = new_case_id
    doc.verificacion = "OK"
    doc.verificacion_detalle = f"Movido desde caso {old_case_id} (sin archivo disco)"


def preview_package_move(db: Session, doc_id: int) -> dict[str, Any]:
    """Preview de que pasaria si mueves este doc (sin ejecutar).

    Util para mostrar al usuario "esto movera N hermanos" antes de confirmar.
    """
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        return {"error": f"Document {doc_id} no existe"}

    if doc.email_id is None:
        return {
            "doc_id": doc_id,
            "package_mode": False,
            "siblings_count": 1,
            "siblings": [{
                "id": doc.id,
                "filename": doc.filename,
                "doc_type": doc.doc_type,
            }],
            "message": "Este documento no pertenece a ningun paquete email (legacy)",
        }

    siblings = get_siblings(db, doc_id)
    return {
        "doc_id": doc_id,
        "package_mode": True,
        "email_id": doc.email_id,
        "siblings_count": len(siblings),
        "siblings": [
            {"id": s.id, "filename": s.filename, "doc_type": s.doc_type}
            for s in siblings
        ],
        "message": f"Al mover este documento se moveran tambien {len(siblings) - 1} hermanos del mismo correo",
    }
