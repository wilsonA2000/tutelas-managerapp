"""Router de reportes y exportacion Excel."""

import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.config import EXPORTS_DIR
from backend.database.database import get_db
from backend.database.models import Case
from backend.reports.excel_generator import generate_excel
from backend.reports.metrics import calculate_metrics

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.post("/excel")
def api_generate_excel(db: Session = Depends(get_db)):
    """Generar archivo Excel con todos los datos."""
    cases = db.query(Case).all()
    if not cases:
        raise HTTPException(status_code=404, detail="No hay casos en la base de datos")

    timestamp = datetime.now(timezone(timedelta(hours=-5))).strftime("%Y%m%d_%H%M")
    filename = f"TUTELAS_{timestamp}.xlsx"
    filepath = EXPORTS_DIR / filename

    generate_excel(cases, str(filepath))

    return {"filename": filename, "path": str(filepath), "cases_count": len(cases), "download_url": f"/api/reports/excel/download/{filename}"}


@router.get("/excel/download/{filename}")
def api_download_excel(filename: str):
    # Sanitizar filename - prevenir path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Nombre de archivo invalido")
    filepath = EXPORTS_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(
        path=str(filepath),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )


@router.get("/excel/list")
def api_list_exports():
    """Listar archivos Excel generados (más reciente primero)."""
    files = []
    if EXPORTS_DIR.exists():
        for f in sorted(EXPORTS_DIR.glob("*.xlsx"), key=lambda x: x.stat().st_mtime, reverse=True):
            stat = f.stat()
            files.append({
                "filename": f.name,
                "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone(timedelta(hours=-5))).isoformat(),
                "size_kb": round(stat.st_size / 1024, 1),
            })
    return files


@router.get("/metrics")
def api_metrics(db: Session = Depends(get_db)):
    cases = db.query(Case).all()
    return calculate_metrics(cases)
