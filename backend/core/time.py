"""Utilidad de tiempo compartida.

`datetime.utcnow()` quedó deprecado en Python 3.12+ y será removido en 3.13+.
`utcnow()` lo reemplaza preservando el contrato del proyecto: **UTC naive**
(sin tzinfo), que es como toda la DB guarda fechas (date_received, updated_at,
created_at, etc.). Usar un datetime *aware* rompería comparaciones contra esas
columnas naive (TypeError offset-naive vs offset-aware).
"""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """UTC naive — reemplazo no-deprecado de datetime.utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
