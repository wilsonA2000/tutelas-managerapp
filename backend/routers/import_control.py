"""Router para importar el cuadro de control externo de la oficina jurídica."""
from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime
from backend.core.time import utcnow
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.services.control_tutelas_importer import import_control_tutelas

router = APIRouter(prefix="/api/import", tags=["import"])


@router.post("/control-tutelas")
async def import_xlsx(
    file: UploadFile = File(...),
    apply: bool = True,
    dry_run: bool = False,
    db: Session = Depends(get_db),
):
    """Importa cuadro CONTROL TUTELAS .xlsx de la oficina jurídica.

    - apply=True: aplica reconciliación (actualiza abogado_canonical/dependencia_canonical
      cuando DB no tenía y Excel sí). Cases en disenso quedan flagged para revisión.
    - dry_run=True: solo retorna preview, no commitea.
    """
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(400, "Archivo debe ser .xlsx")

    # Persistir el upload temporalmente
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        version = utcnow().strftime("%Y-%m-%d_%H%M")
        report = import_control_tutelas(
            db, tmp_path,
            source_version=version,
            apply_reconciliation=apply,
            dry_run=dry_run,
        )
        return report
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@router.post("/control-tutelas-from-path")
def import_xlsx_from_path(
    body: dict,
    apply: bool = True,
    dry_run: bool = False,
    db: Session = Depends(get_db),
):
    """Variante que recibe ruta del filesystem (para uso interno desde scripts)."""
    path = body.get("path")
    if not path or not Path(path).exists():
        raise HTTPException(400, f"Archivo no existe: {path}")
    version = body.get("version") or utcnow().strftime("%Y-%m-%d_%H%M")
    return import_control_tutelas(
        db, path, source_version=version,
        apply_reconciliation=apply, dry_run=dry_run,
    )


@router.get("/control-tutelas/last-import")
def last_import_summary(db: Session = Depends(get_db)):
    """Resumen del último import: cuántas actuaciones por versión, etc."""
    from backend.database.models import CaseActuacion
    from sqlalchemy import func
    rows = (db.query(CaseActuacion.source_version, func.count(CaseActuacion.id))
              .group_by(CaseActuacion.source_version)
              .order_by(CaseActuacion.source_version.desc())
              .limit(10).all())
    return {"versions": [{"version": r[0], "count": r[1]} for r in rows]}


@router.get("/control-tutelas/disensos")
def get_disensos(db: Session = Depends(get_db)):
    """Lista cases con disenso DB↔Excel para revisión humana.

    Construye dinámicamente: case con abogado_canonical en DB pero distinto
    al consenso de las actuaciones recientes del Excel.
    """
    from backend.database.models import CaseActuacion, Case
    from collections import Counter
    from sqlalchemy import func

    # Última versión importada
    last_version = (db.query(CaseActuacion.source_version)
                      .order_by(CaseActuacion.imported_at.desc())
                      .limit(1).scalar())
    if not last_version:
        return {"disensos": [], "message": "Sin importaciones aún"}

    actuaciones = (db.query(CaseActuacion)
                     .filter(CaseActuacion.source_version == last_version,
                             CaseActuacion.case_id.isnot(None),
                             CaseActuacion.abogado_canonical.isnot(None))
                     .all())

    # Consenso por rad
    by_case = {}
    for a in actuaciones:
        by_case.setdefault(a.case_id, []).append(a.abogado_canonical)

    disensos = []
    for case_id, abogados in by_case.items():
        excel_consenso = Counter(abogados).most_common(1)[0][0]
        case = db.query(Case).filter(Case.id == case_id).first()
        if not case or not case.abogado_canonical:
            continue
        if case.abogado_canonical != excel_consenso:
            disensos.append({
                "case_id": case.id,
                "folder_name": case.folder_name,
                "radicado": case.radicado_23_digitos,
                "db_abogado": case.abogado_canonical,
                "excel_abogado": excel_consenso,
                "n_actuaciones_excel": len(abogados),
            })
    return {"version": last_version, "total": len(disensos), "disensos": disensos}
