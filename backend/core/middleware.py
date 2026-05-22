"""Middleware para request IDs y manejo global de excepciones."""

import uuid
import time
import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.core.logging import request_id_var

logger = logging.getLogger("tutelas.middleware")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Asigna un request ID único a cada request y lo incluye en la respuesta."""

    async def dispatch(self, request: Request, call_next):
        req_id = str(uuid.uuid4())[:8]
        request_id_var.set(req_id)

        start = time.time()
        response = await call_next(request)
        duration = int((time.time() - start) * 1000)

        response.headers["X-Request-ID"] = req_id

        # Log request (skip health checks and static files)
        path = request.url.path
        if not path.startswith("/api/health") and not path.startswith("/assets"):
            logger.info(
                "%s %s %d %dms",
                request.method, path, response.status_code, duration,
                extra={"duration_ms": duration},
            )

        return response


class AuthMiddleware(BaseHTTPMiddleware):
    """Exige JWT Bearer válido en todo `/api/*` salvo la lista blanca pública.

    Reusa `decode_token` (auth/service). Cubre routers Y endpoints definidos
    directo en `app` (sync, monitor, run-all, ...) — imposible olvidar uno.

    DEBE insertarse ANTES del CORSMiddleware en main.py para que las respuestas
    401 lleven cabeceras CORS y el refresh-on-401 del frontend funcione.
    """

    # Endpoints accesibles sin token. /docs, /openapi.json, /redoc quedan
    # públicos por decisión operativa (solo exponen el esquema, no datos).
    PUBLIC_PATHS = frozenset({
        "/api/auth/login",
        "/api/auth/refresh",
        "/api/health",
        "/api/health/normalizer",
    })

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Preflight CORS, rutas no-API (assets, docs) y lista blanca → pasan.
        if (
            request.method == "OPTIONS"
            or not path.startswith("/api/")
            or path in self.PUBLIC_PATHS
        ):
            return await call_next(request)

        from backend.auth.service import decode_token

        header = request.headers.get("Authorization", "")
        token = header[7:] if header.startswith("Bearer ") else None
        payload = decode_token(token) if token else None
        if not payload or payload.get("type") != "access":
            return JSONResponse(
                status_code=401,
                content={"detail": "Autenticación requerida"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)


async def global_exception_handler(request: Request, exc: Exception):
    """Captura excepciones no manejadas y retorna JSON estructurado."""
    logger.error(
        "Unhandled exception: %s %s - %s",
        request.method, request.url.path, str(exc),
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Error interno del servidor",
            "request_id": request_id_var.get(""),
        },
    )
