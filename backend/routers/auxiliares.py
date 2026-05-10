"""Endpoints auxiliares: Corte Constitucional, directorio de correos, export Excel."""
from __future__ import annotations

import io
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.database.models import Case, CorteRevision, DirectorioCorreos

router = APIRouter(prefix="/api", tags=["auxiliares"])


# ============================================================
# Corte Constitucional
# ============================================================

@router.get("/corte/cases")
def list_corte(db: Session = Depends(get_db)):
    rows = db.query(CorteRevision).order_by(CorteRevision.created_at.desc()).all()
    return [{
        "id": r.id,
        "case_id": r.case_id,
        "radicado_t": r.radicado_t,
        "radicado_corto": r.radicado_corto,
        "accionante": r.accionante,
        "tema": r.tema,
        "correo_juzgado": r.correo_juzgado,
        "sentencia_hito": r.sentencia_hito,
        "observaciones": r.observaciones,
        "estado_revision": r.estado_revision,
        "fecha_seleccion": r.fecha_seleccion,
        "fecha_fallo_corte": r.fecha_fallo_corte,
        "sentido_fallo_corte": r.sentido_fallo_corte,
    } for r in rows]


@router.put("/corte/{record_id}")
def update_corte(record_id: int, body: dict, db: Session = Depends(get_db)):
    rec = db.query(CorteRevision).filter(CorteRevision.id == record_id).first()
    if not rec:
        raise HTTPException(404, "No encontrado")
    for f in ("estado_revision", "fecha_seleccion", "fecha_fallo_corte",
              "sentido_fallo_corte", "sentencia_hito", "observaciones"):
        if f in body:
            setattr(rec, f, body[f])
    db.commit()
    return {"ok": True, "id": rec.id}


# ============================================================
# Directorio de correos por dependencia
# ============================================================

@router.get("/directorio-correos")
def list_directorio(dependencia: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(DirectorioCorreos).filter(DirectorioCorreos.activo == 1)
    if dependencia:
        q = q.filter(DirectorioCorreos.dependencia_canonical == dependencia)
    rows = q.all()
    return [{
        "id": r.id,
        "dependencia_canonical": r.dependencia_canonical,
        "tema": r.tema,
        "correos": r.correos,
        "responsable": r.responsable,
        "notas": r.notas,
    } for r in rows]


@router.get("/directorio-correos/sugerir/{case_id}")
def sugerir_correos_caso(case_id: int, db: Session = Depends(get_db)):
    """Para un caso, sugiere correos basado en dependencia_canonical."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case no encontrado")
    dep = case.dependencia_canonical
    suggestions = []
    if dep:
        rows = db.query(DirectorioCorreos).filter(
            DirectorioCorreos.dependencia_canonical == dep,
            DirectorioCorreos.activo == 1,
        ).all()
        suggestions = [{
            "tema": r.tema, "correos": r.correos, "notas": r.notas,
        } for r in rows]
    return {"dependencia": dep, "sugerencias": suggestions}


# ============================================================
# Export Excel formato compañera
# ============================================================

@router.get("/export/control-tutelas-format")
def export_control_format(db: Session = Depends(get_db)):
    """Exporta cases en formato compatible con CONTROL TUTELAS .xlsx"""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "TUTELAS 2026"

    headers = ["FECHA", "TUTELA", "DESACATO", "RADICADO", "ACCIONANTE",
               "CORREO JUZGADO", "TEMA", "DEPENDENCIA", "ABOGADO",
               "RADICADO FOREST", "TÉRMINO", "OBSERVACIONES",
               "FALLO 1RA", "FALLO 2DA", "ESTADO INCIDENTE", "RIESGO"]
    ws.append(headers)

    cases = db.query(Case).filter(Case.processing_status == "COMPLETO").all()
    now = datetime.utcnow()

    def short(name):
        if not name: return ""
        return name.split()[0]

    for case in cases:
        ws.append([
            case.fecha_ingreso or "",
            "TUTELA" if (case.origen == "TUTELA") else (case.origen or ""),
            "DESACATO" if (case.estado_incidente or "N/A") not in ("N/A",) else "",
            case.radicado_23_digitos or "",
            case.accionante or "",
            "",  # correo juzgado: lo tendría el extractor email; por ahora vacío
            (case.derecho_vulnerado or "")[:60],
            (case.dependencia_canonical or case.oficina_responsable or "")[:50],
            short(case.abogado_canonical or case.abogado_responsable or ""),
            case.radicado_forest or "",
            "",  # término legal: lo tendría compliance
            (case.observaciones or "")[:200],
            case.sentido_fallo_1st or "",
            case.sentido_fallo_2nd or "",
            case.estado_incidente or "N/A",
            "",
        ])

    # Ajustar anchos
    for i, w in enumerate([12, 10, 12, 28, 35, 40, 40, 28, 18, 20, 12, 60, 15, 15, 18, 10], start=1):
        ws.column_dimensions[chr(64 + i) if i <= 26 else "A" + chr(64 + i - 26)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="control-tutelas-export-{now.strftime("%Y%m%d")}.xlsx"'
        },
    )
