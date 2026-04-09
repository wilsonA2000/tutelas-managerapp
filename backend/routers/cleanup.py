"""Router de limpieza profunda v4.8.

Endpoints:
- GET /api/cleanup/diagnosis      — reporte de problemas (read-only)
- GET /api/cleanup/diagnosis.md   — mismo reporte en markdown

Las fases F2-F5 (hash, move, emails, verify) se agregan en siguientes
iteraciones — esta primera version expone solo F1.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.services.cleanup_diagnosis import diagnose, render_markdown

router = APIRouter(prefix="/api/cleanup", tags=["cleanup"])


@router.get("/diagnosis")
def api_cleanup_diagnosis(db: Session = Depends(get_db)):
    """Diagnostico read-only: agrupa todo el desorden en un reporte JSON.

    Incluye:
    - Totales de casos/docs/emails
    - Cobertura de provenance (email_id)
    - Grupos de casos con misma identidad (auto-mergeable + manual)
    - Fragmentos detectados (casos con <3 docs)
    - Folders sospechosos
    - Typos en folder names
    - Docs sin content_hash
    - Docs NO_PERTENECE / SOSPECHOSO
    - Emails sin .md generado
    - Estadisticas de disco
    """
    return diagnose(db)


@router.get("/diagnosis.md", response_class=PlainTextResponse)
def api_cleanup_diagnosis_markdown(db: Session = Depends(get_db)):
    """Mismo diagnostico en formato markdown (para copiar/pegar o guardar)."""
    report = diagnose(db)
    return render_markdown(report)
