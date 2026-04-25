"""Bearer token auth para el extraction worker.

El token se lee de la env var MODEL_SERVER_TOKEN al arranque.
Los clientes deben enviar Authorization: Bearer <token> en cada request.
"""

from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException, status


_EXPECTED_TOKEN = os.environ.get("MODEL_SERVER_TOKEN", "").strip()


def require_bearer(authorization: str | None = Header(default=None)) -> None:
    if not _EXPECTED_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MODEL_SERVER_TOKEN no configurado en el servidor",
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    provided = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(provided, _EXPECTED_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid bearer token",
        )
