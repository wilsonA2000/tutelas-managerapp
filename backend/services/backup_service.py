"""Servicio de backup y restauracion de la base de datos SQLite.

Funcionalidades:
- Backup manual y automatico (pre-operaciones pesadas)
- Retencion configurable (por defecto 7 backups)
- Restauracion desde backup seleccionado
- Listado de backups disponibles con metadata
"""

import shutil
import sqlite3
import logging
from pathlib import Path
from datetime import datetime

from backend.core.settings import settings

logger = logging.getLogger("backup")

BACKUPS_DIR = settings.app_dir / "data" / "backups"
MAX_BACKUPS = 7


def _ensure_backups_dir() -> Path:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUPS_DIR


def _cleanup_old_backups(keep: int = MAX_BACKUPS):
    """Eliminar backups antiguos, conservar los N mas recientes."""
    backups = sorted(BACKUPS_DIR.glob("tutelas_backup_*.db"), key=lambda f: f.stat().st_mtime)
    while len(backups) > keep:
        old = backups.pop(0)
        try:
            old.unlink()
            logger.info(f"Backup antiguo eliminado: {old.name}")
        except Exception as e:
            logger.warning(f"No se pudo eliminar {old.name}: {e}")


def create_backup(reason: str = "manual") -> dict:
    """Crear backup de la DB usando sqlite3 backup API (seguro con WAL).

    Args:
        reason: Motivo del backup (manual, pre_sync, pre_extraction, pre_gmail, scheduled)

    Returns:
        dict con filename, size_mb, path, reason, timestamp
    """
    _ensure_backups_dir()

    db_path = settings.db_path
    if not db_path.exists():
        return {"error": "Base de datos no encontrada", "path": str(db_path)}

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"tutelas_backup_{timestamp}_{reason}.db"
    backup_path = BACKUPS_DIR / backup_name

    try:
        # Usar sqlite3 backup API — seguro incluso con WAL mode activo
        source = sqlite3.connect(str(db_path))
        dest = sqlite3.connect(str(backup_path))
        source.backup(dest)
        dest.close()
        source.close()

        size_mb = round(backup_path.stat().st_size / (1024 * 1024), 2)
        logger.info(f"Backup creado: {backup_name} ({size_mb} MB) - {reason}")

        # Limpiar backups antiguos
        _cleanup_old_backups()

        return {
            "filename": backup_name,
            "size_mb": size_mb,
            "path": str(backup_path),
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"Error creando backup: {e}")
        # Limpiar backup parcial
        if backup_path.exists():
            backup_path.unlink()
        return {"error": str(e)}


def list_backups() -> list[dict]:
    """Listar todos los backups disponibles con metadata."""
    _ensure_backups_dir()

    backups = []
    for f in sorted(BACKUPS_DIR.glob("tutelas_backup_*.db"), key=lambda x: x.stat().st_mtime, reverse=True):
        stat = f.stat()
        # Parsear reason del nombre: tutelas_backup_YYYYMMDD_HHMMSS_reason.db
        parts = f.stem.split("_")
        reason = parts[4] if len(parts) >= 5 else "unknown"

        backups.append({
            "filename": f.name,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "reason": reason,
        })

    return backups


def restore_backup(filename: str) -> dict:
    """Restaurar la DB desde un backup.

    PELIGROSO: Reemplaza la DB actual. Crea backup de seguridad antes.

    Args:
        filename: Nombre del archivo de backup (sin path)

    Returns:
        dict con resultado de la operacion
    """
    backup_path = BACKUPS_DIR / filename

    if not backup_path.exists():
        return {"error": f"Backup no encontrado: {filename}"}

    # Verificar integridad del backup
    try:
        conn = sqlite3.connect(str(backup_path))
        result = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
        if result[0] != "ok":
            return {"error": f"Backup corrupto: {result[0]}"}
    except Exception as e:
        return {"error": f"No se puede leer el backup: {e}"}

    db_path = settings.db_path

    # Backup de seguridad de la DB actual antes de restaurar
    safety = create_backup(reason="pre_restore")
    if "error" in safety:
        logger.warning(f"No se pudo crear backup de seguridad: {safety['error']}")

    try:
        # Copiar backup sobre la DB actual
        shutil.copy2(str(backup_path), str(db_path))
        size_mb = round(db_path.stat().st_size / (1024 * 1024), 2)
        logger.info(f"DB restaurada desde {filename} ({size_mb} MB)")

        return {
            "restored_from": filename,
            "size_mb": size_mb,
            "safety_backup": safety.get("filename", "no se pudo crear"),
            "timestamp": datetime.now().isoformat(),
            "warning": "Reinicie el servidor para que los cambios tomen efecto completo",
        }

    except Exception as e:
        logger.error(f"Error restaurando backup: {e}")
        return {"error": str(e)}


def auto_backup(reason: str) -> dict | None:
    """Backup automatico antes de operaciones pesadas.

    Solo crea backup si el ultimo fue hace mas de 30 minutos.
    """
    _ensure_backups_dir()

    # Verificar ultimo backup
    backups = sorted(BACKUPS_DIR.glob("tutelas_backup_*.db"), key=lambda x: x.stat().st_mtime)
    if backups:
        last = backups[-1]
        age_minutes = (datetime.now().timestamp() - last.stat().st_mtime) / 60
        if age_minutes < 30:
            logger.debug(f"Backup reciente existe ({age_minutes:.0f} min), omitiendo auto-backup")
            return None

    return create_backup(reason=reason)
