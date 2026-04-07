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
