"""Router de limpieza profunda v4.8.

Endpoints:
- GET  /api/cleanup/diagnosis          — reporte read-only (F1)
- GET  /api/cleanup/diagnosis.md       — reporte en markdown
- POST /api/cleanup/hash-backfill      — F2 backfill content_hash
- POST /api/cleanup/emails-md-backfill — F4 genera .md faltantes
- POST /api/cleanup/merge-identity     — F3 fusion grupos (dry_run | deep)
"""

from pydantic import BaseModel
from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.services.cleanup_diagnosis import (
    diagnose, render_markdown,
    detect_forest_fragments, detect_incomplete_radicados,
    propose_duplicate_cleanup, identify_reextraction_candidates,
)
from backend.services.cleanup_actions import (
    backfill_content_hash,
    backfill_emails_md,
    merge_identity_groups,
    batch_move_no_pertenece,
    purge_duplicates,
    merge_forest_fragments,
    backfill_radicado_23d,
)

router = APIRouter(prefix="/api/cleanup", tags=["cleanup"])


class DryRunBody(BaseModel):
    dry_run: bool = True


@router.get("/audit")
def api_cleanup_audit(db: Session = Depends(get_db)):
    """v5.0: Auditoria completa con detectores ampliados.

    Incluye: diagnostico base + fragmentos FOREST + radicados incompletos
    + propuesta duplicados + candidatos re-extraccion.
    """
    return diagnose(db)


@router.get("/diagnosis")
def api_cleanup_diagnosis(db: Session = Depends(get_db)):
    """F1: Diagnostico read-only del desorden actual."""
    return diagnose(db)


@router.get("/diagnosis.md", response_class=PlainTextResponse)
def api_cleanup_diagnosis_markdown(db: Session = Depends(get_db)):
    """F1 en formato markdown."""
    report = diagnose(db)
    return render_markdown(report)


@router.post("/hash-backfill")
def api_cleanup_hash_backfill(body: DryRunBody = DryRunBody(), db: Session = Depends(get_db)):
    """F2: Backfill MD5 hash para docs sin content_hash.

    Safe: solo escribe file_hash, no mueve ni borra nada.
    """
    return backfill_content_hash(db, dry_run=body.dry_run)


@router.post("/emails-md-backfill")
def api_cleanup_emails_md(body: DryRunBody = DryRunBody(), db: Session = Depends(get_db)):
    """F4: Genera .md faltantes de emails con body_preview.

    Safe: solo crea archivos nuevos en disco + registra Documents con email_id.
    """
    return backfill_emails_md(db, dry_run=body.dry_run)


class MoveNoPertBody(BaseModel):
    dry_run: bool = True
    min_confidence: str = "ALTA"


@router.post("/move-no-pertenece")
def api_cleanup_move_no_pertenece(
    body: MoveNoPertBody = MoveNoPertBody(),
    db: Session = Depends(get_db),
):
    """F3b: Mueve docs NO_PERTENECE a su caso correcto sugerido.

    Regla 'hermanos viajan juntos' aplica automaticamente: si el doc tiene
    email_id, sus hermanos del paquete lo acompañan al destino.
    """
    return batch_move_no_pertenece(
        db,
        dry_run=body.dry_run,
        min_confidence=body.min_confidence,
    )


class MergeBody(BaseModel):
    dry_run: bool = True
    only_auto_mergeable: bool = True


@router.post("/merge-identity")
def api_cleanup_merge_identity(body: MergeBody = MergeBody(), db: Session = Depends(get_db)):
    """F3: Fusion de grupos con misma identidad (radicado_23d + accionante + tipo_rep).

    Por default solo procesa grupos auto_mergeable (con radicado 23d valido).
    Por default dry_run=True — muestra que haria sin ejecutar.
    """
    return merge_identity_groups(
        db,
        dry_run=body.dry_run,
        only_auto_mergeable=body.only_auto_mergeable,
    )


# --- v5.0 Endpoints ---

class PurgeDuplicatesBody(BaseModel):
    dry_run: bool = True
    scope: str = "intra"  # intra | inter | all


@router.post("/purge-duplicates")
def api_cleanup_purge_duplicates(body: PurgeDuplicatesBody = PurgeDuplicatesBody(), db: Session = Depends(get_db)):
    """v5.0: Purga duplicados por hash MD5.

    scope='intra': dentro del mismo caso (seguro, mueve a _duplicados/).
    scope='inter': entre casos, solo NO_PERTENECE.
    scope='all': ambos.
    """
    return purge_duplicates(db, scope=body.scope, dry_run=body.dry_run)


class ForestMergeBody(BaseModel):
    dry_run: bool = True
    min_confidence: str = "ALTA"


@router.post("/merge-forest-fragments")
def api_cleanup_merge_forest(body: ForestMergeBody = ForestMergeBody(), db: Session = Depends(get_db)):
    """v5.0: Fusiona fragmentos FOREST con su caso padre detectado.

    Detecta casos creados con número FOREST como folder y los vincula
    al caso original encontrado por radicado 23d en sus documentos.
    """
    return merge_forest_fragments(db, dry_run=body.dry_run, min_confidence=body.min_confidence)


@router.post("/backfill-radicados")
def api_cleanup_backfill_radicados(body: DryRunBody = DryRunBody(), db: Session = Depends(get_db)):
    """v5.0: Busca y asigna radicado_23_digitos desde el texto de documentos.

    Solo auto-asigna con confianza ALTA (radicado en 2+ docs).
    Los de confianza MEDIA se reportan como sugerencia.
    """
    return backfill_radicado_23d(db, dry_run=body.dry_run)
