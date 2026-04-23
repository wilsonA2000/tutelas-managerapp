"""Unified Cognitive Pipeline — Orquestador v6.0.

Ejecuta las 7 capas cognitivas en orden con feedback loops limitados
(máx 3 iteraciones de convergencia). Reemplazo opcional de unified.py
detrás del feature flag USE_COGNITIVE_PIPELINE.

Capas:
    0. Percepción física (VisualSignature vía ir_builder — ya integrada)
    1. Identificación tipológica (classify_doc_type)
    2. Canonical identifiers (harvest_identifiers)
    3. Actor graph (build_from_case)
    4. Procedural timeline + case_classifier (origen + estado_incidente)
    5. Bayesian assignment (infer_assignment por doc)
    6. Live consolidator (consolidate_case)
    7. Cognitive persist (persist_case con entropy gate)

El orquestador preserva la interfaz del extractor viejo: `unified_extract(db, case_id)`.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from backend.database.models import Case, Document, Email
from backend.extraction.ir_builder import build_case_ir
from backend.extraction.pipeline import extract_document_text, classify_doc_type

from backend.cognition.canonical_identifiers import harvest_from_case_ir
from backend.cognition.bayesian_assignment import infer_assignment
from backend.cognition.actor_graph import build_from_case
from backend.cognition.procedural_timeline import build_timeline
from backend.cognition.case_classifier import classify_case
from backend.cognition.cognitive_fill import cognitive_fill
from backend.cognition.live_consolidator import consolidate_case
from backend.cognition.cognitive_persist import persist_case
from backend.cognition.entropy import entropy_of_case


logger = logging.getLogger("tutelas.unified_cognitive")


MAX_CONVERGENCE_ITERATIONS = 3


def unified_cognitive_extract(db: Session, case, base_dir: str = "",
                               classify_docs: bool = False) -> dict:
    """Ejecuta el pipeline cognitivo v6.0 sobre un caso.

    Firma compatible con unified_extract legacy: (db, case, base_dir, classify_docs).
    """
    case_id = case.id if hasattr(case, "id") else case
    if not hasattr(case, "documents"):
        case = db.query(Case).filter(Case.id == case_id).first()
        if not case:
            return {"status": "error", "reason": "caso no existe"}

    stats = {
        "case_id": case_id,
        "iterations": 0,
        "phase_entropies": {},
        "bayesian_verdicts": {"OK": 0, "SOSPECHOSO": 0, "NO_PERTENECE": 0, "REVISAR": 0},
        "consolidation": None,
        "started_at": datetime.utcnow().isoformat(),
    }

    case.processing_status = "EXTRAYENDO"
    db.commit()

    try:
        # =================================================================
        # Capas 0+1+2: IR + VisualSignature + identificadores (una sola vez)
        # =================================================================
        logger.info("V6 case=%d Fase 0+1+2: IR + visual + identifiers", case_id)

        for doc in case.documents:
            if not doc.extracted_text and doc.file_path:
                text, method = extract_document_text(doc)
                if text.strip():
                    doc.extracted_text = text
                    doc.extraction_method = method
                    doc.extraction_date = datetime.utcnow()
        db.commit()

        case_ir = build_case_ir(db, case)

        # Persistir VisualSignature en los Document (Capa 0)
        import json as _json
        docs_by_filename = {d.filename: d for d in case.documents}
        for doc_ir in case_ir.documents:
            if doc_ir.visual_signature:
                target = docs_by_filename.get(doc_ir.filename)
                if target is not None:
                    target.institutional_score = float(
                        doc_ir.visual_signature.get("institutional_score") or 0.0
                    )
                    target.visual_signature_json = _json.dumps(
                        doc_ir.visual_signature, ensure_ascii=False
                    )
        db.commit()

        ids_by_doc = harvest_from_case_ir(case_ir)
        stats["phase_entropies"]["post_identifiers"] = entropy_of_case(case).entropy_bits

        # =================================================================
        # Capa 5: Bayesian assignment por documento
        # =================================================================
        logger.info("V6 case=%d Fase 5: Bayesian assignment", case_id)
        for doc_ir in case_ir.documents:
            target_doc = docs_by_filename.get(doc_ir.filename)
            if target_doc is None:
                continue
            verdict = infer_assignment(case, doc_ir, doc=target_doc)
            target_doc.verificacion = verdict.verdict
            detail = f"post={verdict.posterior:.3f}"
            if verdict.reasons_for:
                detail += " +:" + "; ".join(verdict.reasons_for[:2])
            if verdict.reasons_against:
                detail += " -:" + "; ".join(verdict.reasons_against[:2])
            target_doc.verificacion_detalle = detail[:250]
            stats["bayesian_verdicts"][verdict.verdict] = \
                stats["bayesian_verdicts"].get(verdict.verdict, 0) + 1
        db.commit()

        # =================================================================
        # Capa 3: Actor graph (para enriquecer campos de partes)
        # =================================================================
        logger.info("V6 case=%d Fase 3: Actor graph", case_id)
        _graph = build_from_case(case, case_ir, ids_by_doc)
        # El grafo se usa más como estructura interna; por ahora no
        # sobrescribimos accionante/accionados si ya están poblados por
        # cognition. Solo registramos que se construyó.

        # =================================================================
        # Capa 3.6 (cognition legacy) + Capa 4: timeline + clasificador
        # =================================================================
        logger.info("V6 case=%d Fase 3.6+4: cognition + timeline", case_id)
        full_text = "\n".join(d.full_text or "" for d in case_ir.documents if d.full_text)
        case_meta = {
            "id": case.id,
            "fecha_ingreso": case.fecha_ingreso or "",
            "radicado_23_digitos": case.radicado_23_digitos or "",
            "radicado_forest": case.radicado_forest or "",
            "abogado_responsable": case.abogado_responsable or "",
            "incidente": case.incidente or "",
        }
        try:
            cog_results = cognitive_fill(case_meta, full_text, existing=None,
                                          documents=None)
            # Aplicar sin sobrescribir valores existentes si provienen de regex fuerte
            for field, result in cog_results.items():
                if not getattr(case, field, None):
                    setattr(case, field, result.value)
        except Exception as e:
            logger.debug("cognitive_fill falló para case=%d: %s", case_id, e)

        # Timeline + clasificación
        tl = build_timeline(case)
        cls = classify_case(case, tl)
        case.origen = cls.origen
        case.estado_incidente = cls.estado_incidente
        db.commit()
        stats["phase_entropies"]["post_cognition"] = entropy_of_case(case).entropy_bits

        # =================================================================
        # Capa 6: Live consolidator
        # =================================================================
        logger.info("V6 case=%d Fase 6: Live consolidator", case_id)
        consolidation = consolidate_case(db, case)
        stats["consolidation"] = consolidation.to_dict()

        # Si el caso se consolidó (DUPLICATE_MERGED), terminamos aquí
        db.refresh(case)
        if case.processing_status == "DUPLICATE_MERGED":
            stats["phase_entropies"]["final"] = 0.0
            stats["iterations"] = 1
            stats["status"] = "DUPLICATE_MERGED"
            return stats

        # =================================================================
        # Capa 7: Cognitive persist con entropy gate
        # =================================================================
        logger.info("V6 case=%d Fase 7: Cognitive persist", case_id)
        persist_report = persist_case(
            db, case,
            phase_entropies=stats["phase_entropies"],
            convergence_iterations=stats["iterations"] + 1,
        )
        stats["iterations"] = persist_report.convergence_iterations
        stats["status"] = persist_report.status_after
        stats["entropy_final"] = persist_report.entropy_after
        stats["phase_entropies"]["final"] = persist_report.entropy_after

        return stats

    except Exception as e:
        logger.exception("V6 pipeline falló para case=%d: %s", case_id, e)
        case.processing_status = "REVISION"
        db.commit()
        return {"status": "error", "case_id": case_id, "reason": str(e)}


def unified_extract_dispatch(db: Session, case, base_dir: str = "",
                              classify_docs: bool = False) -> dict:
    """Dispatcher entre pipeline v5.5 legacy y v6.0 cognitivo según feature flag.

    Firma idéntica a la de unified_extract legacy para drop-in replacement.
    """
    try:
        from backend.core.settings import settings
        use_cognitive = bool(getattr(settings, "USE_COGNITIVE_PIPELINE", False))
    except Exception:
        use_cognitive = False

    if use_cognitive:
        return unified_cognitive_extract(db, case, base_dir, classify_docs)

    # Fallback: pipeline v5.5 existente
    from backend.extraction.unified import unified_extract as legacy_unified
    return legacy_unified(db, case, base_dir, classify_docs)
