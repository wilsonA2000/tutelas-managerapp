"""FastAPI - Plataforma de Gestion Juridica de Tutelas.

Versión limpia post 2026-05-09: Claude es el motor de extracción (vía agentes
de sesión, no API). El backend solo expone el cuadro, edición manual,
exportación Excel y endpoints de soporte.
"""

import sys
import threading
import time as _time
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Asegurar que el directorio padre este en el path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.settings import settings  # noqa: F401 — inicializa flags
from backend.core.logging import setup_logging, get_logger
from backend.core.middleware import RequestIDMiddleware, global_exception_handler
from backend.database.database import init_db, wal_checkpoint

setup_logging(log_dir=str(Path(__file__).resolve().parent.parent / "logs"))
logger = get_logger("main")


def _wal_checkpoint_loop():
    """Flush WAL → archivo principal cada 5 min para mantener .db-wal pequeño."""
    while True:
        _time.sleep(300)
        try:
            r = wal_checkpoint("PASSIVE")
            if r.get("log_pages", 0) > 500:
                logger.info("WAL checkpoint: %s/%s pages", r.get("checkpointed"), r.get("log_pages"))
        except Exception as e:
            logger.warning("WAL checkpoint error: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    threading.Thread(target=_wal_checkpoint_loop, daemon=True, name="wal-checkpoint").start()
    logger.info("Aplicacion iniciada (modo Claude-as-engine)")
    yield
    logger.info("Aplicacion detenida")


app = FastAPI(
    title="Tutelas Manager",
    description="Plataforma de Gestion Juridica de Tutelas - Gobernacion de Santander",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestIDMiddleware)
app.add_exception_handler(Exception, global_exception_handler)

# Routers
from backend.auth.router import router as auth_router
from backend.routers import cases, documents, dashboard, emails, reports, auxiliares

app.include_router(auth_router)
app.include_router(cases.router)
app.include_router(documents.router)
app.include_router(dashboard.router)
app.include_router(emails.router)
app.include_router(reports.router)
app.include_router(auxiliares.router)


@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "Tutelas Manager v2.0"}
