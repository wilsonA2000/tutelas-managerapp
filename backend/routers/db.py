"""Router para operaciones de base de datos: backup, restore, rebuild."""

import threading

from fastapi import APIRouter, Depends
from backend.auth.dependencies import get_current_user
from backend.services.backup_service import create_backup, list_backups, restore_backup

router = APIRouter(prefix="/api/db", tags=["database"])

# Estado global del rebuild
rebuild_in_progress = False
rebuild_progress = {}


@router.post("/backup")
def api_create_backup(user=Depends(get_current_user)):
    """Crear backup manual de la base de datos."""
    result = create_backup(reason="manual")
    return result


@router.get("/backups")
def api_list_backups(user=Depends(get_current_user)):
    """Listar todos los backups disponibles."""
    backups = list_backups()
    return {"backups": backups, "total": len(backups)}


@router.post("/restore")
def api_restore_backup(filename: str, user=Depends(get_current_user)):
    """Restaurar la DB desde un backup. Requiere reinicio del servidor."""
    result = restore_backup(filename)
    return result


@router.post("/rebuild")
def api_rebuild_db(
    extract_text: bool = True,
    import_csv: bool = True,
    user=Depends(get_current_user),
):
    """Reconstruir DB en sandbox desde carpetas fisicas (0 IA).

    Genera data/sandbox/tutelas_sandbox.db sin tocar la DB principal.
    """
    global rebuild_in_progress, rebuild_progress

    if rebuild_in_progress:
        return {"status": "running", "message": "Rebuild en progreso", "progress": rebuild_progress}

    def _run_rebuild():
        global rebuild_in_progress, rebuild_progress
        from backend.services.rebuild_service import rebuild_from_folders

        def progress_cb(step, current, total, detail):
            rebuild_progress.update({
                "step": step,
                "current": current,
                "total": total,
                "detail": detail,
            })

        try:
            rebuild_progress = {"step": "Iniciando rebuild...", "current": 0, "total": 5, "detail": ""}
            result = rebuild_from_folders(
                extract_text=extract_text,
                import_csv_data=import_csv,
                progress_callback=progress_cb,
            )
            rebuild_progress["step"] = "Completado"
            rebuild_progress["result"] = result
        except Exception as e:
            rebuild_progress["step"] = f"Error: {e}"
            rebuild_progress["error"] = str(e)
        finally:
            rebuild_in_progress = False

    rebuild_in_progress = True
    rebuild_progress = {"step": "Iniciando...", "current": 0, "total": 5, "detail": ""}
    threading.Thread(target=_run_rebuild, daemon=True).start()
    return {"status": "started", "message": "Rebuild iniciado en sandbox (0 IA)"}


@router.get("/rebuild/status")
def api_rebuild_status(user=Depends(get_current_user)):
    """Estado del rebuild en curso."""
    return {"in_progress": rebuild_in_progress, **rebuild_progress}


@router.get("/sandbox/compare")
def api_sandbox_compare(user=Depends(get_current_user)):
    """Comparar sandbox DB vs DB principal."""
    from backend.services.rebuild_service import generate_comparison_report
    return generate_comparison_report()
