"""Router de casos de tutela."""

import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.database.models import Case
from backend.services.case_service import (
    list_cases, get_case, update_case, get_filter_options, _get_case_completitud,
)

# Caso-shell de la ingesta de Gmail: huérfanos sin radicado. No es una tutela real,
# así que NO aparece en el cuadro ni en el Excel (sí en el listado de Tutelas, para triaje).
SHELL_FOLDER = "__SIN_RADICADO__"

router = APIRouter(prefix="/api/cases", tags=["cases"])


@router.get("")
def api_list_cases(
    search: str = "",
    estado: str = "",
    fallo: str = "",
    abogado: str = "",
    ciudad: str = "",
    status: str = "",
    revision: str = "",
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_cases(db, search, estado, fallo, abogado, ciudad, status, revision, page, per_page)


@router.get("/filters")
def api_filter_options(db: Session = Depends(get_db)):
    return get_filter_options(db)


@router.get("/table")
def api_cases_table(db: Session = Depends(get_db)):
    """Todos los casos (sin paginar) con los 37 campos del cuadro v9 para la vista interactiva.

    `completitud` = % de campos del cuadro v9 diligenciados (mismo cálculo que el dashboard;
    excluye los 5 campos heredados de v8 que v9 no escribe). Excluye el caso-shell de huérfanos.
    """
    cases = db.query(Case).filter(
        Case.folder_name.isnot(None), Case.folder_name != "None", Case.folder_name != "",
        Case.folder_name != SHELL_FOLDER,
        Case.processing_status != "DUPLICATE_MERGED",
    ).order_by(Case.id.desc()).all()
    items = []
    for c in cases:
        data = {"id": c.id, "tipo_actuacion": c.tipo_actuacion or "TUTELA", "folder_name": c.folder_name or ""}
        for csv_col, attr in Case.CSV_FIELD_MAP.items():
            data[csv_col] = getattr(c, attr) or ""
        data["completitud"] = round(_get_case_completitud(c))
        # Acumulación procesal (v9.2): se expone para badges/columna en Cuadro.
        data["tipo_acumulacion"] = c.tipo_acumulacion
        data["acumulado_a_case_id"] = c.acumulado_a_case_id
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


@router.get("/{case_id}/acumulacion")
def api_get_case_acumulacion(case_id: int, db: Session = Depends(get_db)):
    """Información de acumulación procesal del case.

    Devuelve:
      - `tipo`: 'RECTOR' / 'ACUMULADO' / null
      - `rector`: si es ACUMULADO, datos del case rector (id, folder, rad, fecha del auto).
      - `acumulados`: si es RECTOR, lista de cases acumulados a éste.
      - `auto_doc`: doc del auto que ordenó la acumulación (si aplica).
    """
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Caso no encontrado")

    def serialize_case_lite(c: Case) -> dict:
        return {
            "id": c.id,
            "folder_name": c.folder_name,
            "radicado_23_digitos": c.radicado_23_digitos,
            "juzgado": c.juzgado,
            "accionante": c.accionante,
        }

    out: dict = {
        "case_id": case.id,
        "tipo": case.tipo_acumulacion,
        "fecha": case.acumulacion_fecha,
        "rector": None,
        "acumulados": [],
        "auto_doc": None,
    }
    if case.acumulacion_auto_doc_id:
        from backend.database.models import Document
        d = db.get(Document, case.acumulacion_auto_doc_id)
        if d:
            out["auto_doc"] = {"id": d.id, "filename": d.filename, "case_id": d.case_id, "doc_type": d.doc_type}

    if case.tipo_acumulacion == "ACUMULADO" and case.acumulado_a_case_id:
        rector = db.get(Case, case.acumulado_a_case_id)
        if rector:
            out["rector"] = serialize_case_lite(rector)
    elif case.tipo_acumulacion == "RECTOR":
        acumulados = db.query(Case).filter(Case.acumulado_a_case_id == case.id).all()
        out["acumulados"] = [serialize_case_lite(c) for c in acumulados]

    return out


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


# (Retirado) Los endpoints /{case_id}/pii-mode y /{case_id}/pii-hints — la anonimización
# PII no aplica en modo local-only. La "sensibilidad" del expediente (sujeto de especial
# protección) se deriva de `observaciones` y se muestra como badge en la ficha y el listado.


@router.put("/{case_id}")
def api_update_case(case_id: int, fields: dict, db: Session = Depends(get_db)):
    result = update_case(db, case_id, fields)
    if not result:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    return result


# Caracteres no válidos en un nombre de carpeta de filesystem.
_FS_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@router.post("")
def api_create_case(payload: dict, db: Session = Depends(get_db)):
    """Crear un expediente vacío (sin documentos) listo para recibir docs por traslado manual.

    Acepta dos formatos en el campo `radicado_23_digitos` (o alias `radicado_corto`):
      - Rad23 completo (≥21 dígitos) → caso con rad23 canónico, status=PENDIENTE.
      - Rad corto YYYY-NNNNN (los juzgados muchas veces no entregan el rad23) → caso
        con rad23=NULL, status=REVISION, observaciones piden completar el rad23 después.

    Permite resolver el caso "rad_corto homónimo entre juzgados distintos" creando el
    expediente correcto desde la UI y trasladando el doc en el mismo flujo.

    Body: {"radicado_23_digitos": "68344408900120260002800" | "2026-00028",
           "accionante": "DARÍANY ...", "juzgado"?: "...", "ciudad"?: "..."}
    """
    from backend.core.settings import settings
    from backend.email.rad_utils import derive_rad_corto_from_rad23, normalize_rad23
    from backend.database.models import AuditLog

    # Aceptamos rad23 o rad_corto en el mismo campo (autodetección por longitud/forma).
    rad_input = ((payload or {}).get("radicado_23_digitos") or (payload or {}).get("radicado_corto") or "")
    rad_input = str(rad_input).strip()
    accionante_raw = (payload or {}).get("accionante", "")
    juzgado_raw = (payload or {}).get("juzgado", "") or ""
    ciudad_raw = (payload or {}).get("ciudad", "") or ""

    accionante = re.sub(r"\s+", " ", str(accionante_raw or "")).strip()
    if not accionante:
        raise HTTPException(status_code=400, detail="accionante es requerido")

    rad23: str | None = None
    rad_corto: str | None = None

    digits = re.sub(r"\D", "", rad_input)
    if len(digits) >= 21:
        # Rad23 canónico
        rad23 = normalize_rad23(rad_input)
        if not rad23 or len(rad23) < 21:
            raise HTTPException(status_code=400, detail="radicado_23_digitos inválido (mínimo 21 dígitos)")
        rad_corto = derive_rad_corto_from_rad23(rad23)
        if not rad_corto:
            raise HTTPException(status_code=400, detail="No se pudo derivar el radicado corto desde rad23")
    else:
        # Rad corto YYYY-NNNNN, opcionalmente con sufijo -NN (recurso) que algunos
        # juzgados anexan al oficio (ej. "2026-00028-00"). Aceptamos separadores
        # varios (-, espacio, /, _) y ceros a la izquierda en la secuencia.
        m = re.match(r"^\s*(20\d{2})[\s\-/_]*0*(\d{1,5})(?:[\s\-/_]+\d{1,3})?\s*$", rad_input)
        if not m:
            raise HTTPException(
                status_code=400,
                detail="Radicado inválido. Use 23 dígitos (ej. 68344408900120260002800) o el corto YYYY-NNNNN (ej. 2026-00028 o 2026-00028-00).",
            )
        year, seq = m.group(1), m.group(2).zfill(5)
        rad_corto = f"{year}-{seq}"

    # Unicidad por rad23
    if rad23:
        dup = db.query(Case).filter(Case.radicado_23_digitos == rad23).first()
        if dup:
            raise HTTPException(status_code=409, detail=f"Ya existe un expediente con ese radicado (#{dup.id} «{dup.folder_name}»)")

    # Folder name = "<rad_corto> <ACCIONANTE>" con saneado FS (preserva tildes/ñ).
    folder_name = re.sub(r"\s+", " ", _FS_INVALID_CHARS.sub("", f"{rad_corto} {accionante.upper()}")).strip().strip(".").strip()
    folder_name = folder_name[:200]
    if not folder_name or folder_name == SHELL_FOLDER:
        raise HTTPException(status_code=400, detail="folder_name resultante inválido")

    clash = db.query(Case).filter(Case.folder_name == folder_name).first()
    if clash:
        raise HTTPException(status_code=409, detail=f"Ya existe el expediente «{folder_name}» (#{clash.id})")

    base_dir = Path(settings.BASE_DIR)
    folder_path = base_dir / folder_name
    if folder_path.exists():
        raise HTTPException(status_code=409, detail=f"Ya existe la carpeta «{folder_name}» en disco")

    try:
        folder_path.mkdir(parents=True, exist_ok=False)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"No se pudo crear la carpeta en disco: {e}")

    now = datetime.utcnow()
    if rad23:
        status = "PENDIENTE"
        observaciones = "Expediente creado manualmente desde la UI"
    else:
        status = "REVISION"
        observaciones = (
            f"Expediente creado manualmente con radicado corto {rad_corto} — falta el radicado de 23 dígitos. "
            "Completar cuando el juzgado lo proporcione."
        )

    case = Case(
        radicado_23_digitos=rad23,
        accionante=accionante,
        juzgado=juzgado_raw.strip() or None,
        ciudad=ciudad_raw.strip() or None,
        folder_name=folder_name,
        folder_path=str(folder_path),
        processing_status=status,
        tipo_actuacion="TUTELA",
        origen="TUTELA",
        observaciones=observaciones,
        created_at=now,
        updated_at=now,
    )
    db.add(case)
    db.flush()
    db.add(AuditLog(
        case_id=case.id, field_name="case", old_value="",
        new_value=f"id={case.id} folder={folder_name} rad23={rad23 or '(pendiente)'}",
        action="CREACION_MANUAL", source="usuario",
    ))
    db.commit()

    # Refrescar cache O(1) del monitor para que el próximo email matchee a este caso
    try:
        from backend.email.case_lookup_cache import get_cache
        get_cache().refresh_one(db, case.id)
    except Exception:
        pass

    return get_case(db, case.id)


@router.put("/{case_id}/folder-name")
def api_rename_case_folder(case_id: int, payload: dict, db: Session = Depends(get_db)):
    """Renombra la carpeta de un expediente.

    Actualiza `folder_name` y `folder_path` en la DB, renombra el directorio en disco
    (si existe) y reapunta los `file_path` de los documentos. Registra la edición en
    `AuditLog`. Rechaza colisiones con otro expediente (en DB o en disco).

    Body: {"folder_name": "2026-00368 JUAN SEBASTIÁN OJEDA VILLAMIZAR"}
    """
    from backend.core.settings import settings
    from backend.database.models import AuditLog, Document

    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    old_name = case.folder_name or ""
    if old_name == SHELL_FOLDER:
        raise HTTPException(status_code=400, detail="No se puede renombrar el caso-shell de huérfanos")

    raw = (payload or {}).get("folder_name", "")
    new_name = re.sub(r"\s+", " ", _FS_INVALID_CHARS.sub("", str(raw or ""))).strip().strip(".").strip()
    if not new_name or len(new_name) > 200:
        raise HTTPException(status_code=400, detail="Nombre de carpeta inválido (vacío o más de 200 caracteres)")
    if new_name == SHELL_FOLDER:
        raise HTTPException(status_code=400, detail="Nombre reservado")
    if new_name == old_name:
        return get_case(db, case_id)

    clash = db.query(Case).filter(Case.folder_name == new_name, Case.id != case_id).first()
    if clash:
        raise HTTPException(status_code=409, detail=f"Ya existe un expediente con la carpeta «{new_name}» (#{clash.id})")

    base_dir = Path(settings.BASE_DIR)
    old_path = Path(case.folder_path) if case.folder_path else None
    new_path = base_dir / new_name

    if old_path and old_path.exists():
        if new_path.exists():
            raise HTTPException(status_code=409, detail=f"Ya existe una carpeta «{new_name}» en disco")
        try:
            old_path.rename(new_path)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"No se pudo renombrar la carpeta en disco: {e}")
        old_str, new_str = str(old_path), str(new_path)
        for doc in db.query(Document).filter(Document.case_id == case_id).all():
            if doc.file_path and doc.file_path.startswith(old_str):
                doc.file_path = new_str + doc.file_path[len(old_str):]
        case.folder_path = new_str
    else:
        # La carpeta no existe en disco → solo actualizamos la referencia.
        case.folder_path = str(new_path)

    case.folder_name = new_name
    case.updated_at = datetime.utcnow()
    db.add(AuditLog(
        case_id=case.id, field_name="folder_name", old_value=old_name, new_value=new_name,
        action="EDICION_MANUAL", source="usuario",
    ))
    db.commit()
    return get_case(db, case_id)


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


# (Modernización Fase 7.4) El endpoint POST /api/cases/{id}/validate (validador heurístico
# + LLM v8.1) se retiró: dependía de `cognition.cognitive_complementary_ai` (motor v8).
# v9 extrae de forma determinista (1 autoridad por campo) y registra la confianza en
# `Case.field_confidences_json`; la verificación de pertenencia doc↔caso vive en el
# bibliotecario v9 (`doc_librarian` / `verify_document_belongs`) y en la página de
# Mantenimiento ("docs sospechosos").
