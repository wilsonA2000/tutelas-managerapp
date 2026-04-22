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


class ReconcileBody(BaseModel):
    dry_run: bool = True


@router.post("/reconcile")
def api_cleanup_reconcile(body: ReconcileBody = ReconcileBody(), db: Session = Depends(get_db)):
    """v5.1 Sprint 1: reconciliar inconsistencias historicas de la DB.

    Arregla 3 tipos de descuadre:
    - Documents con case_id apuntando a caso DUPLICATE_MERGED → mover al canonico
    - Emails con case_id apuntando a DUPLICATE_MERGED → mover al canonico
    - Documents con file_path fuera del folder_path de su caso → sincronizar path

    Usar con dry_run=true primero para ver el plan, luego dry_run=false para aplicar.
    """
    from backend.services.reconcile_db import reconcile_db
    return reconcile_db(db, dry_run=body.dry_run)


@router.post("/wal-checkpoint")
def api_wal_checkpoint(mode: str = "PASSIVE"):
    """v5.1 Sprint 1: forzar WAL checkpoint manual.

    Uso tipico: antes de hacer backup o ejecutar scripts CLI externos.
    Modos: PASSIVE (no bloqueante), FULL (espera writers), TRUNCATE (FULL + trunca .db-wal).
    """
    from backend.database.database import wal_checkpoint
    return wal_checkpoint(mode)


@router.get("/health-v50")
def api_cleanup_health(db: Session = Depends(get_db)):
    """v5.0 post-audit: KPIs accionables para panel Salud de Datos.

    Indicadores que miden cuan limpia esta la DB post fixes v5.0:
    - Folders [PENDIENTE REVISION] activos (target: 0)
    - COMPLETO sin rad23 (target: 0)
    - Folders con rad_corto disonante vs rad23 (B1 residual, target: 0)
    - Casos con obs que mencionan radicados ajenos (B4 residual)
    - Docs SOSPECHOSO por caso (top 10)
    - Pares duplicados detectados por rad23 (F9)
    - Distribucion processing_status
    """
    import re as _re
    from backend.database.models import Case, Document

    def rad_corto_from_23(rad23):
        if not rad23:
            return None
        digits = _re.sub(r"\D", "", rad23)
        m = _re.search(r"(20\d{2})(\d{5})\d{2}$", digits)
        return f"{m.group(1)}-{m.group(2)}" if m else None

    # 1. Folders [PENDIENTE REVISION] activos
    pendiente = db.query(Case).filter(
        Case.folder_name.like("%PENDIENTE%"),
        Case.processing_status != "DUPLICATE_MERGED",
    ).count()

    # 2. COMPLETO sin rad23
    completo_sin_rad23 = db.query(Case).filter(
        Case.processing_status == "COMPLETO",
        (Case.radicado_23_digitos.is_(None)) | (Case.radicado_23_digitos == ""),
    ).count()

    # 3. Folders disonantes rad_corto vs rad23 (B1 residual)
    all_cases = db.query(Case).filter(Case.processing_status != "DUPLICATE_MERGED").all()
    folder_bugged = []
    duplicates_by_rad = {}
    for c in all_cases:
        if not c.folder_name:
            continue
        fm = _re.match(r"(20\d{2})-0*(\d{1,6})", c.folder_name)
        if not fm:
            continue
        rc_folder = f"{fm.group(1)}-{int(fm.group(2)):05d}"
        rc_off = rad_corto_from_23(c.radicado_23_digitos)
        if rc_off and rc_folder != rc_off:
            forest_clean = _re.sub(r"\D", "", c.radicado_forest or "")
            seq = int(fm.group(2))
            folder_is_forest = (forest_clean and str(seq) in forest_clean) or (not forest_clean and seq >= 10000)
            if folder_is_forest:
                folder_bugged.append({"id": c.id, "folder": c.folder_name, "rad_oficial": rc_off})
        # F9: agrupar por rad_corto para detectar duplicados
        if rc_off:
            duplicates_by_rad.setdefault(rc_off, []).append(c.id)

    duplicate_pairs = [(rc, ids) for rc, ids in duplicates_by_rad.items() if len(ids) > 1]

    # 4. Obs con radicados ajenos
    obs_contaminated = []
    for c in all_cases:
        text = " ".join([c.observaciones or "", c.asunto or "", c.pretensiones or ""])
        if not text.strip():
            continue
        text_clean = _re.sub(
            r"(?i)(?:forest|radicado\s+(?:numero|n[uú]mero|interno)|n[uú]mero\s+de\s+radicado)\s*:?\s*\d{7,}",
            " ",
            text,
        )
        rc_off = rad_corto_from_23(c.radicado_23_digitos)
        rc_fold = None
        fm = _re.match(r"(20\d{2})-0*(\d{1,5})", c.folder_name or "")
        if fm:
            rc_fold = f"{fm.group(1)}-{int(fm.group(2)):05d}"
        # Si folder difiere de rad_off, no tolerar folder
        if rc_off and rc_fold and rc_off != rc_fold:
            rc_fold = None
        foreign = set()
        for mm in _re.finditer(r"\b(20\d{2})[-\s]0*(\d{1,5})(?!\d)\b", text_clean):
            norm = f"{mm.group(1)}-{int(mm.group(2)):05d}"
            if rc_off and norm == rc_off:
                continue
            if rc_fold and norm == rc_fold:
                continue
            foreign.add(norm)
        if foreign and rc_off:
            obs_contaminated.append({"id": c.id, "folder": c.folder_name, "ajenos": sorted(foreign)[:3]})

    # 5. Docs sospechosos por caso (top 10)
    from sqlalchemy import func
    susp_by_case = db.query(
        Document.case_id,
        func.count(Document.id).label("n"),
    ).filter(Document.verificacion == "SOSPECHOSO").group_by(Document.case_id).order_by(func.count(Document.id).desc()).limit(10).all()
    susp_list = []
    for case_id, n in susp_by_case:
        c = db.query(Case).filter(Case.id == case_id).first()
        susp_list.append({
            "case_id": case_id,
            "folder": c.folder_name if c else None,
            "n_sospechosos": n,
        })

    # 6. Distribucion de processing_status
    status_dist = {}
    for row in db.query(Case.processing_status, func.count(Case.id)).group_by(Case.processing_status).all():
        status_dist[row[0] or "NULL"] = row[1]

    # 7. Distribucion de doc verificacion
    verif_dist = {}
    for row in db.query(Document.verificacion, func.count(Document.id)).group_by(Document.verificacion).all():
        verif_dist[row[0] or "NULL"] = row[1]

    return {
        "summary": {
            "folders_pendiente_revision_activos": pendiente,
            "completo_sin_rad23": completo_sin_rad23,
            "folders_disonantes_b1_residual": len(folder_bugged),
            "obs_contaminadas_b4_residual": len(obs_contaminated),
            "pares_duplicados_f9": len(duplicate_pairs),
            "docs_sospechosos_total": verif_dist.get("SOSPECHOSO", 0),
        },
        "folders_bugged": folder_bugged[:20],
        "obs_contaminated": obs_contaminated[:20],
        "duplicate_pairs": [{"rad_corto": rc, "case_ids": ids} for rc, ids in duplicate_pairs[:20]],
        "top_sospechosos": susp_list,
        "processing_status_distribution": status_dist,
        "verificacion_distribution": verif_dist,
    }
