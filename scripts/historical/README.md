# Scripts históricos

Scripts de migración / mantenimiento puntual ya ejecutados en producción.
Se conservan como referencia histórica, **no deben ejecutarse de nuevo** sin
adaptación previa (contienen IDs y paths hardcoded de un estado pasado de la DB).

| Script | Fecha aplicado | Propósito |
|--------|----------------|-----------|
| `cleanup_db.py` | mar 2026 | Deduplicar 118 casos del CSV inicial vs ~82 carpetas reales |
| `fix_accionantes.py` | mar 2026 | Backfill del campo `accionante` desde Excel histórico |

Para nuevas tareas de mantenimiento usar los endpoints `/api/cleanup/*` o
los servicios en `backend/services/cleanup_*.py`.
