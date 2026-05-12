"""Router de casos de tutela."""

import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.database.models import Case
from backend.services.case_service import (
    list_cases, get_case, update_case, get_filter_options,
)

router = APIRouter(prefix="/api/cases", tags=["cases"])


@router.get("")
def api_list_cases(
    search: str = "",
    estado: str = "",
    fallo: str = "",
    abogado: str = "",
    ciudad: str = "",
    status: str = "",
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_cases(db, search, estado, fallo, abogado, ciudad, status, page, per_page)


@router.get("/filters")
def api_filter_options(db: Session = Depends(get_db)):
    return get_filter_options(db)


@router.get("/table")
def api_cases_table(db: Session = Depends(get_db)):
    """Todos los casos con 28 campos para vista de cuadro interactivo (sin paginar).

    v8.3: incluye `_confidences` por caso. Mapea `attr → {band: OK|REVISAR|BAJO}`
    desde `field_confidences_json`. El frontend usa esto para colorear celdas.
    """
    import json as _json
    cases = db.query(Case).filter(
        Case.folder_name.isnot(None), Case.folder_name != "None", Case.folder_name != "",
        Case.processing_status != "DUPLICATE_MERGED",
    ).order_by(Case.id.desc()).all()
    items = []
    for c in cases:
        data = {"id": c.id, "tipo_actuacion": c.tipo_actuacion or "TUTELA", "folder_name": c.folder_name or ""}
        filled = 0
        for csv_col, attr in Case.CSV_FIELD_MAP.items():
            val = getattr(c, attr) or ""
            data[csv_col] = val
            if val.strip():
                filled += 1
        data["completitud"] = round(filled / len(Case.CSV_FIELD_MAP) * 100)

        # v8.3: bandas de confianza por campo (subset)
        if c.field_confidences_json:
            try:
                raw = _json.loads(c.field_confidences_json)
                # Persistimos solo {csv_col: band} para minimizar payload
                conf_by_col: dict[str, str] = {}
                for csv_col, attr in Case.CSV_FIELD_MAP.items():
                    meta = raw.get(attr)
                    if meta and meta.get("band"):
                        conf_by_col[csv_col] = meta["band"]
                if conf_by_col:
                    data["_confidences"] = conf_by_col
            except (_json.JSONDecodeError, AttributeError):
                pass
        items.append(data)
    return items


@router.get("/export-audit")
def api_export_audit(db: Session = Depends(get_db)):
    """v8.3: XLSX de auditoria con 4 hojas (Resumen, Cuadro, Confianza, Findings).

    Reusa el auditor de scripts/audit_cases.py + executive_kpis para generar
    un reporte unificado descargable.
    """
    from backend.reports.export_audit import generate_audit_xlsx

    out_dir = Path(tempfile.gettempdir())
    fname = f"auditoria_tutelas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    out_path = out_dir / fname
    meta = generate_audit_xlsx(db, str(out_path))
    return FileResponse(
        str(out_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=fname,
        headers={"X-Audit-Cases": str(meta["cases"]), "X-Audit-Sheets": ",".join(meta["sheets"])},
    )


@router.get("/{case_id}")
def api_get_case(case_id: int, db: Session = Depends(get_db)):
    result = get_case(db, case_id)
    if not result:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    return result


@router.get("/{case_id}/email-packages")
def api_get_case_email_packages(case_id: int, db: Session = Depends(get_db)):
    """v4.8 Provenance: lista los paquetes email de un caso para timeline cronologico.

    Devuelve los emails que tienen al menos 1 Document hijo vinculado,
    ordenados por fecha de recepcion descendente. Cada paquete es una unidad
    atomica (email body + adjuntos + .md).
    """
    from backend.services.provenance_service import list_packages_in_case

    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Caso no encontrado")

    packages = list_packages_in_case(db, case_id)
    # Serializar datetimes
    for pkg in packages:
        if pkg.get("date_received"):
            pkg["date_received"] = pkg["date_received"].isoformat() + "Z"
    return {
        "case_id": case_id,
        "case_folder": case.folder_name,
        "packages_count": len(packages),
        "packages": packages,
    }


@router.patch("/{case_id}/pii-mode")
def api_set_pii_mode(
    case_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    """Cambia el modo de anonimización del caso (v5.3).

    Body: {"mode": "selective" | "aggressive" | null}
    - null → usa PII_MODE_DEFAULT global.
    - Cambio invalida processing_status para forzar re-extract.
    """
    mode = payload.get("mode")
    if mode not in (None, "selective", "aggressive"):
        raise HTTPException(status_code=400, detail="mode debe ser 'selective', 'aggressive' o null")
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    prev = case.pii_mode
    case.pii_mode = mode
    if prev != mode:
        case.processing_status = "PENDIENTE"  # señal para re-extract
    db.commit()
    return {"case_id": case_id, "pii_mode": mode, "prev": prev, "requires_reextract": prev != mode}


@router.get("/{case_id}/pii-hints")
def api_get_pii_hints(case_id: int, db: Session = Depends(get_db)):
    """Heurísticas que sugieren activar modo aggressive (v5.3).

    Analiza documentos del caso buscando señales de alta sensibilidad:
    menor con discapacidad crónica, violencia de género, salud mental.
    """
    import re as _re
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Caso no encontrado")

    hints: list[str] = []
    blob = " ".join(filter(None, [
        case.observaciones or "", case.asunto or "", case.pretensiones or "",
        case.derecho_vulnerado or "",
    ])).lower()

    if _re.search(r"\b(?:menor|niñ[oa]|adolescent)", blob) and _re.search(r"discapacidad|diagn[oó]stic[oa]|s[ií]ndrome|autismo|par[aá]lisis", blob):
        hints.append("menor_con_condicion_salud")
    if _re.search(r"violenc|maltrat|abus|agres", blob):
        hints.append("violencia_detectada")
    if _re.search(r"salud\s+mental|ansiedad|depresi[oó]n|psiqui[aá]tric", blob):
        hints.append("salud_mental")
    if _re.search(r"registro\s+civil|RC\s+\d", blob, _re.IGNORECASE):
        hints.append("nuip_menor_presente")

    return {
        "case_id": case_id,
        "current_mode": case.pii_mode,
        "hints": hints,
        "recommend_aggressive": bool(hints),
    }


@router.put("/{case_id}")
def api_update_case(case_id: int, fields: dict, db: Session = Depends(get_db)):
    result = update_case(db, case_id, fields)
    if not result:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    return result


@router.delete("/{case_id}")
def api_delete_case(case_id: int, db: Session = Depends(get_db)):
    """Eliminar un caso completo: DB + carpeta en disco."""
    import shutil
    from pathlib import Path
    from backend.database.models import Document, Email, Extraction, AuditLog as AL, ComplianceTracking, TokenUsage

    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Caso no encontrado")

    folder_name = case.folder_name
    folder_path = case.folder_path

    # Eliminar relaciones en DB
    db.query(Document).filter(Document.case_id == case_id).delete()
    db.query(Extraction).filter(Extraction.case_id == case_id).delete()
    db.query(AL).filter(AL.case_id == case_id).delete()
    db.query(ComplianceTracking).filter(ComplianceTracking.case_id == case_id).delete()
    db.query(TokenUsage).filter(TokenUsage.case_id == case_id).delete()
    db.query(Email).filter(Email.case_id == case_id).update({"case_id": None, "status": "PENDIENTE"})
    db.delete(case)
    db.commit()

    # Eliminar carpeta en disco
    if folder_path and Path(folder_path).exists():
        try:
            shutil.rmtree(folder_path)
        except Exception:
            pass

    return {"message": f"Caso '{folder_name}' eliminado"}


@router.delete("/{case_id}/docs/{doc_id}")
def api_delete_document(case_id: int, doc_id: int, db: Session = Depends(get_db)):
    """Eliminar un documento específico: DB + archivo en disco."""
    from pathlib import Path
    from backend.database.models import Document, Extraction

    doc = db.query(Document).filter(Document.id == doc_id, Document.case_id == case_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    filename = doc.filename
    file_path = doc.file_path

    # Eliminar extracciones vinculadas
    db.query(Extraction).filter(Extraction.document_id == doc_id).delete()
    db.delete(doc)
    db.commit()

    # Eliminar archivo en disco
    if file_path and Path(file_path).exists():
        try:
            Path(file_path).unlink()
        except Exception:
            pass

    return {"message": f"Documento '{filename}' eliminado"}


@router.post("/{case_id}/merge/{target_id}")
def api_merge_case(case_id: int, target_id: int, db: Session = Depends(get_db)):
    """Fusionar un caso duplicado (case_id) con su tutela base (target_id).
    Mueve documentos y emails del duplicado al caso base, luego elimina el duplicado."""
    from backend.database.models import Document, Email, Extraction, AuditLog as AL

    source = db.query(Case).filter(Case.id == case_id).first()
    target = db.query(Case).filter(Case.id == target_id).first()
    if not source or not target:
        raise HTTPException(status_code=404, detail="Caso no encontrado")

    # Mover documentos
    docs_moved = db.query(Document).filter(Document.case_id == case_id).update({"case_id": target_id})
    # Mover emails
    emails_moved = db.query(Email).filter(Email.case_id == case_id).update({"case_id": target_id})
    # Mover extracciones
    db.query(Extraction).filter(Extraction.case_id == case_id).update({"case_id": target_id})

    # Registrar en audit_log del target
    db.add(AL(
        case_id=target_id,
        field_name="MERGE",
        old_value=source.folder_name,
        new_value=f"Fusionado: +{docs_moved} docs, +{emails_moved} emails",
        action="MERGE",
        source=f"merge_from_id_{case_id}",
    ))

    # Eliminar caso duplicado
    db.query(AL).filter(AL.case_id == case_id).delete()
    db.delete(source)
    db.commit()

    return {
        "message": f"Caso '{source.folder_name}' fusionado con '{target.folder_name}'",
        "docs_moved": docs_moved,
        "emails_moved": emails_moved,
    }


@router.post("/{case_id}/sync")
def api_sync_single_case(case_id: int, db: Session = Depends(get_db)):
    """Sincronizar documentos de una carpeta individual con el disco."""
    from pathlib import Path
    from backend.database.models import Document
    from backend.database.seed import classify_document

    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    if not case.folder_path or not Path(case.folder_path).exists():
        raise HTTPException(status_code=400, detail="Carpeta no encontrada en disco")

    VALID_EXT = {".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg", ".md"}
    folder = Path(case.folder_path)
    existing = {d.filename for d in case.documents}

    docs_added = 0
    docs_removed = 0

    # Agregar archivos nuevos
    for f in sorted(folder.iterdir()):
        if not f.is_file() or f.suffix.lower() not in VALID_EXT or f.name in existing:
            continue
        db.add(Document(
            case_id=case.id, filename=f.name, file_path=str(f),
            doc_type=classify_document(f.name), file_size=f.stat().st_size,
        ))
        docs_added += 1

    # Eliminar documentos que ya no existen en disco
    for doc in case.documents:
        if doc.file_path and not Path(doc.file_path).exists():
            db.delete(doc)
            docs_removed += 1

    db.commit()

    # Verificacion inteligente de pertenencia (0 llamadas IA, todo local)
    from backend.extraction.doc_ops import verify_document_belongs, extract_document_text

    docs_moved = 0
    docs_suspicious = 0
    reassign_stats = {}

    db.refresh(case)
    for doc in list(case.documents):
        if doc.verificacion in ("OK", "REASIGNADO"):
            continue
        if not doc.extracted_text and doc.file_path and Path(doc.file_path).exists():
            try:
                text, method = extract_document_text(doc)
                if text and len(text.strip()) >= 50:
                    doc.extracted_text = text
                    doc.extraction_method = method
            except Exception:
                pass
        if not doc.extracted_text or len(doc.extracted_text or "") < 100:
            continue

        status, detalle = verify_document_belongs(case, doc)
        doc.verificacion = status
        doc.verificacion_detalle = detalle

        if status == "NO_PERTENECE":
            docs_moved += 1
            from backend.database.models import AuditLog
            db.add(AuditLog(
                case_id=case.id,
                field_name="DOC_NO_PERTENECE",
                old_value=doc.filename,
                new_value=detalle[:200],
                action="SYNC_VERIFY",
                source="sync_individual",
            ))
        elif status == "SOSPECHOSO":
            docs_suspicious += 1

    db.commit()
    return {
        "message": f"+{docs_added} docs, -{docs_removed} eliminados, {docs_moved} reasignados, {docs_suspicious} sospechosos",
        "docs_added": docs_added,
        "docs_removed": docs_removed,
        "docs_moved": docs_moved,
        "docs_suspicious": docs_suspicious,
    }


# ============================================================
# v8.1: Endpoint validador heurístico + LLM opcional
# ============================================================

@router.post("/{case_id}/validate")
def validate_case(
    case_id: int,
    use_llm: bool = False,
    timeout_s: int = 30,
    db: Session = Depends(get_db),
):
    """v8.1: valida los campos extraídos del case contra el texto de los docs.

    - Siempre devuelve heurística determinista (firmante↔accionante, mezcla rad).
    - Si `use_llm=true` y `LLM_LOCAL_PRIMARY=true`, también invoca LoRA con
      timeout duro. Si LoRA falla/timeout, solo retorna heurística (no bloquea).

    Returns:
        {
            "case_id": int,
            "heuristic": {field: {verdict, razon}, ...},
            "llm": {... raw response ...} | None,
            "elapsed_s": float
        }
    """
    import time
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case no encontrado")

    from backend.cognition.cognitive_complementary_ai import (
        validate_case_extraction, _heuristic_validation,
        _build_authority_weighted_text,
    )

    text = _build_authority_weighted_text(db, case, max_chars=4000) or ""
    if not text:
        # Fallback: concatenar texto de docs OK
        from backend.database.models import Document
        docs = db.query(Document).filter(
            Document.case_id == case_id,
            Document.verificacion == "OK",
        ).limit(5).all()
        text = "\n\n".join((d.extracted_text or "")[:1500] for d in docs)

    t0 = time.time()
    if use_llm:
        result = validate_case_extraction(case, text, timeout_s=float(timeout_s))
        result["case_id"] = case_id
        result["elapsed_s"] = round(time.time() - t0, 2)
        return result
    # Solo heurística: <1ms, no falla nunca
    h = _heuristic_validation(case, text)
    return {
        "case_id": case_id,
        "heuristic": h,
        "llm": None,
        "elapsed_s": round(time.time() - t0, 3),
    }
