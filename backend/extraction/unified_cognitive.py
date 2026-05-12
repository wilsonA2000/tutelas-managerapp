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

from backend.database.models import Case, Document, Email, AuditLog
from backend.extraction.ir_builder import build_case_ir
from backend.extraction.pipeline import extract_document_text, classify_doc_type

# v6.1.1: regex extractors mecánicos restaurados (Fase 3 que se omitió en v6.0)
from backend.agent.extractors.base import ExtractionResult
from backend.extraction.unified import _EXTRACTORS
from backend.agent.forest_extractor import extract_forest_from_sources

from backend.cognition.canonical_identifiers import harvest_from_case_ir
from backend.cognition.bayesian_assignment import infer_assignment
# v8.0: actor_graph eliminado (output nunca usado downstream)
from backend.cognition.procedural_timeline import build_timeline
from backend.cognition.case_classifier import classify_case
from backend.cognition.cognitive_fill import cognitive_fill
from backend.cognition.live_consolidator import consolidate_case
from backend.cognition.cognitive_persist import persist_case
from backend.cognition.entropy import entropy_of_case


logger = logging.getLogger("tutelas.unified_cognitive")


MAX_CONVERGENCE_ITERATIONS = 3


def unified_cognitive_extract(db: Session, case, base_dir: str = "",
                               classify_docs: bool = False,
                               skip_consolidation_and_persist: bool = False) -> dict:
    """Ejecuta el pipeline cognitivo v6.0 sobre un caso.

    Firma compatible con unified_extract legacy: (db, case, base_dir, classify_docs).

    Args:
        skip_consolidation_and_persist: si True, corre solo las Capas 0-5 y
            retorna antes de Capa 6 (live_consolidator) y Capa 7 (persist).
            Lo usa el pod RunPod, que ejecuta el cómputo pesado y deja las
            capas cross-case + persist para el cliente (backend local).
    """
    case_id = case.id if hasattr(case, "id") else case
    if not hasattr(case, "documents"):
        case = db.query(Case).filter(Case.id == case_id).first()
        if not case:
            return {"status": "error", "reason": "caso no existe"}

    # Switch a extracción remota (RunPod) cuando está habilitado.
    # Solo aplica si NO estamos dentro del pod (skip=False) para evitar recursión.
    if not skip_consolidation_and_persist:
        try:
            from backend.core.settings import settings
            if bool(getattr(settings, "USE_REMOTE_EXTRACTION", False)):
                from backend.extraction.remote_client import run_remote_extract
                remote_stats = run_remote_extract(db, case)
                if remote_stats is not None:
                    return remote_stats
                # Pod falló. Decidir: fallback local (consume RAM) o mantener pendiente (strict).
                strict = bool(getattr(settings, "REMOTE_EXTRACTION_STRICT", False))
                if strict:
                    logger.warning("V6 case=%d remote falló y STRICT=true, caso queda PENDIENTE",
                                   case_id)
                    try:
                        case.processing_status = "PENDIENTE"
                        db.commit()
                    except Exception:
                        db.rollback()
                    return {"status": "remote_failed_strict", "case_id": case_id,
                            "source": "remote_pod"}
                logger.warning("V6 case=%d remote falló, fallback local", case_id)
        except Exception as e:
            logger.exception("V6 case=%d error en switch remote, fallback local: %s",
                             case_id, e)

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
        # Capa 3 (v8.0): Actor graph ELIMINADO — output nunca se persistía ni
        # consumía downstream. Los campos accionante/accionados/vinculados se
        # llenan vía cognitive_fill (Capa 3.8). Ahorra una pasada de NER spaCy
        # por cada documento.
        # =================================================================

        # =================================================================
        # FASE 3 REGEX (v6.1.1) — extractores mecánicos: juzgado, ciudad, abogado, fechas
        # Restaurada en v6.1.1; estaba ausente en v6.0 (regresión 12 campos en 0%).
        # =================================================================
        logger.info("V6 case=%d Fase 3 regex: extractores mecánicos", case_id)
        doc_dicts_regex = [
            {
                "filename": d.filename, "doc_type": d.doc_type,
                "text": d.full_text, "full_text": d.full_text, "content": d.full_text,
                "priority": getattr(d, "priority", 0),
                "zones": [{"zone_type": z.zone_type, "text": z.text,
                           "metadata": getattr(z, "metadata", {}),
                           "page": getattr(z, "page", 0),
                           "confidence": getattr(z, "confidence", 0.0)}
                          for z in d.zones],
            }
            for d in case_ir.documents
        ]
        case_emails_for_regex = db.query(Email).filter(Email.case_id == case.id).all()
        regex_results: dict = {}
        for field_name, extractor in _EXTRACTORS.items():
            try:
                result = extractor.extract_regex(doc_dicts_regex, case_emails_for_regex)
                if result:
                    is_valid, _reason = extractor.validate(result.value)
                    if is_valid:
                        regex_results[field_name] = result
            except Exception as e:
                logger.debug("Extractor %s falló case=%d: %s", field_name, case.id, e)
        # FOREST especial
        try:
            forest = extract_forest_from_sources(doc_dicts_regex, case_emails_for_regex)
            if forest and forest.value:
                regex_results["radicado_forest"] = ExtractionResult(
                    value=forest.value,
                    confidence=forest.confidence if isinstance(forest.confidence, int) else 90,
                    source=forest.source, method="regex",
                    reasoning=f"FOREST de {forest.source}",
                )
        except Exception as e:
            logger.debug("FOREST extractor falló case=%d: %s", case.id, e)
        # Persistir directo en Case (no sobrescribir si ya tiene valor)
        saved_regex = 0
        for field_name, result in regex_results.items():
            attr = Case.CSV_FIELD_MAP.get(field_name.upper(), field_name)
            if attr and not getattr(case, attr, None):
                setattr(case, attr, result.value)
                saved_regex += 1
                db.add(AuditLog(
                    case_id=case.id, field_name=field_name,
                    old_value="", new_value=result.value[:200],
                    action="REGEX_IR_V61", source=result.source or "regex",
                ))
        stats["regex_fields"] = saved_regex
        logger.info("V6 case=%d Fase 3 regex: %d campos guardados", case_id, saved_regex)
        db.commit()

        # =================================================================
        # FASE 3.5 ABOGADO (v6.1.1) — extrae abogado_responsable de DOCX (Proyectó/Elaboró)
        # Portado de pipeline.py:141-187. Prioriza por tipo doc + accionante en filename.
        # =================================================================
        if not case.abogado_responsable:
            try:
                from backend.extraction.docx_extractor import extract_docx
                DOCX_LAWYER_PRIORITY = {
                    "DOCX_RESPUESTA": 1, "DOCX_CONTESTACION": 2, "DOCX_CUMPLIMIENTO": 3,
                    "DOCX_IMPUGNACION": 4, "DOCX_DESACATO": 5,
                }
                lawyer_candidates = []
                for doc in case.documents:
                    if not doc.file_path:
                        continue
                    ext = Path(doc.file_path).suffix.lower()
                    if ext not in (".docx", ".doc"):
                        continue
                    doc_type = classify_doc_type(doc.filename) if doc.filename else ""
                    if doc_type not in DOCX_LAWYER_PRIORITY:
                        continue
                    try:
                        docx_result = extract_docx(doc.file_path)
                        if docx_result.lawyer_name:
                            lawyer_candidates.append({
                                "name": docx_result.lawyer_name,
                                "filename": doc.filename, "type": doc_type,
                                "priority": DOCX_LAWYER_PRIORITY.get(doc_type, 9),
                            })
                    except Exception:
                        pass
                lawyer_chosen = ""
                if lawyer_candidates:
                    import unicodedata
                    def _n(s: str) -> str:
                        return "".join(c for c in unicodedata.normalize("NFD", s)
                                       if unicodedata.category(c) != "Mn").upper()
                    acc_norm = _n(case.accionante or "")
                    acc_words = [w for w in acc_norm.split() if len(w) >= 4]
                    for lc in sorted(lawyer_candidates, key=lambda x: x["priority"]):
                        fn_norm = _n(lc["filename"])
                        if any(w in fn_norm for w in acc_words[:3]):
                            lawyer_chosen = lc["name"]
                            break
                    if not lawyer_chosen:
                        lawyer_chosen = sorted(lawyer_candidates, key=lambda x: x["priority"])[0]["name"]
                if lawyer_chosen:
                    # Fuzzy match contra abogados_sed.json (corrige variantes/typos)
                    try:
                        import json as _json
                        abogados_path = Path(__file__).resolve().parent.parent / "data" / "abogados_sed.json"
                        if abogados_path.exists():
                            with open(abogados_path) as f:
                                abogados = _json.load(f)
                            chosen_norm = _n(lawyer_chosen)
                            chosen_words = set(chosen_norm.split())
                            for av in abogados:
                                av_norm = _n(av)
                                av_words = set(av_norm.split())
                                if len(av_words & chosen_words) >= 2:
                                    lawyer_chosen = av  # canonical
                                    break
                    except Exception:
                        pass
                    case.abogado_responsable = lawyer_chosen
                    db.add(AuditLog(
                        case_id=case.id, field_name="abogado_responsable",
                        old_value="", new_value=lawyer_chosen[:200],
                        action="REGEX_IR_V61", source="docx_footer",
                    ))
                    logger.info("V6 case=%d abogado_responsable: %s", case_id, lawyer_chosen)
            except Exception as e:
                logger.debug("Fase 3.5 abogado falló case=%d: %s", case_id, e)
        db.commit()

        # =================================================================
        # FASE 3.6 EXTRACTORES TEMÁTICOS (v6.1.1) — campos restantes vacíos
        # oficina_responsable, juzgado_2nd, quien_impugno, fecha_apertura_incidente
        # =================================================================
        import re as _re
        full_text_all = "\n".join(d.full_text or "" for d in case_ir.documents if d.full_text)
        ft_lower = full_text_all.lower()

        # oficina_responsable: 99% de casos es Sec. Educación; secundario "Apoyo Jurídico"
        if not case.oficina_responsable:
            if _re.search(r"secretar[ií]a\s+de\s+educaci[oó]n\s+(?:de\s+)?santander", full_text_all, _re.IGNORECASE):
                case.oficina_responsable = "Secretaría de Educación de Santander"
            elif _re.search(r"apoyo\s+jur[ií]dico", full_text_all, _re.IGNORECASE):
                case.oficina_responsable = "Apoyo Jurídico"
            elif _re.search(r"oficina\s+jur[ií]dica", full_text_all, _re.IGNORECASE):
                case.oficina_responsable = "Oficina Jurídica"

        # juzgado_2nd v8.1.1: patrones más amplios + sala única + corte suprema
        # v8.3 GUARD: solo asignar si existe doc de fallo 2nd o impugnación.
        # En caso contrario, "Corte Suprema/Constitucional" en el texto suele ser
        # jurisprudencia citada por el juez de 1ra (no juzgado real del expediente).
        if not case.juzgado_2nd:
            from backend.cognition.cognitive_fill import _detect_stage_flags as _detect_stage
            _doc_dicts_for_stage = [
                {"filename": d.filename, "doc_type": getattr(d, "doc_type", "")}
                for d in case_ir.documents
            ]
            _stage = _detect_stage(_doc_dicts_for_stage)
            allow_juz2 = _stage["has_fallo_2nd"] or _stage["has_impugnacion"]

            if allow_juz2:
                patterns_juz2 = [
                    # Tribunal Superior con/sin "Distrito Judicial" + ciudad + sala
                    r"(tribunal\s+superior(?:\s+(?:del\s+distrito\s+judicial\s+)?de\s+[A-Za-záéíóúñÁÉÍÓÚÑ\s]{4,40}?)?(?:\s*[-,]\s*sala\s+(?:civil|penal|laboral|de\s+familia|de\s+decisi[oó]n[^.\n]{0,60})?)?)\b",
                    # Tribunal Administrativo
                    r"(tribunal\s+administrativo\s+(?:de\s+[A-Za-záéíóúñ\s]{4,40})?)",
                    # Sala única / Sala de decisión + ciudad
                    r"(sala\s+(?:civil|penal|laboral|familia|única|unica|de\s+decisi[oó]n[a-z\s]{0,40})\s+del\s+tribunal[^.\n]{0,60})",
                    # Corte Suprema (raro como 2da en tutelas; solo en casación)
                    r"(corte\s+suprema\s+de\s+justicia(?:\s*[-,]\s*sala\s+[a-z\s]{0,40})?)",
                    # Juzgado X de circuito (segunda instancia para ciertas materias)
                    r"(juzgado\s+\w+\s+civil\s+del\s+circuito\s+de\s+[A-Za-záéíóúñ\s]{4,40})",
                ]
                for pat in patterns_juz2:
                    m = _re.search(pat, full_text_all, _re.IGNORECASE)
                    if m and len(m.group(1)) >= 12:
                        case.juzgado_2nd = _re.sub(r"\s+", " ", m.group(1).strip())[:200]
                        break
            else:
                logger.info("V6 case=%d STAGE_GUARD juzgado_2nd: skip (etapa sin fallo 2nd ni impugnación)", case_id)

        # quien_impugno v8.1.1: enum simplificado ACCIONANTE/ACCIONADO/MINISTERIO_PUBLICO
        if not case.quien_impugno and case.impugnacion in ("SI", "Sí"):
            text_low = full_text_all.lower()
            # Heurísticas por menciones explícitas
            if _re.search(r"impugna(?:ci[oó]n|d[ao])?\s+(?:interpuest[ao]\s+)?por\s+(?:el|la|los)?\s*(?:accionante|tutelante|demandante|actor)", text_low):
                case.quien_impugno = "ACCIONANTE"
            elif _re.search(r"impugna(?:ci[oó]n|d[ao])?\s+(?:interpuest[ao]\s+)?por\s+(?:el|la|los)?\s*(?:accionad[ao]|demandad[ao]|tutelad[ao])", text_low):
                case.quien_impugno = "ACCIONADO"
            elif _re.search(r"impugna(?:ci[oó]n|d[ao])?\s+(?:interpuest[ao]\s+)?por\s+(?:el\s+)?(?:ministerio\s+p[uú]blico|procurador|defensor)", text_low):
                case.quien_impugno = "MINISTERIO_PUBLICO"
            else:
                # Heurísticas por contexto: si fallo 1ra fue CONCEDE, lógica usual = accionado impugna
                # Si fallo 1ra fue NIEGA o IMPROCEDENTE, lógica usual = accionante impugna
                fallo_1 = (case.sentido_fallo_1st or "").upper()
                if fallo_1 in ("NIEGA", "IMPROCEDENTE"):
                    case.quien_impugno = "ACCIONANTE"
                elif fallo_1 == "CONCEDE":
                    case.quien_impugno = "ACCIONADO"

        # forest_impugnacion v6.1 (B.1) — radicado FOREST de docs de 2da instancia.
        # La función ya existía en decision_extractor:298 pero no se invocaba desde
        # el pipeline. Cobertura objetivo 0% → 70%.
        if not case.forest_impugnacion and case.impugnacion in ("SI", "Sí"):
            try:
                from backend.cognition.decision_extractor import (
                    extract_forest_impugnacion as _forest_imp,
                )
                for d in (case_ir.documents if hasattr(case_ir, "documents") else []):
                    fname = (d.filename if hasattr(d, "filename") else "") or ""
                    fname_lower = fname.lower()
                    is_2da = (
                        "impugna" in fname_lower
                        or "segunda" in fname_lower
                        or "tribunal" in fname_lower
                        or "fallo_2" in fname_lower
                        or "2da" in fname_lower
                    )
                    if not is_2da:
                        continue
                    dtext = ""
                    for z in (d.zones if hasattr(d, "zones") else []) or []:
                        ztext = getattr(z, "text", None) if not isinstance(z, dict) else z.get("text")
                        if ztext:
                            dtext += "\n" + ztext
                    if not dtext:
                        dtext = (d.full_text if hasattr(d, "full_text") else "") or ""
                    if not dtext:
                        continue
                    forest = _forest_imp(dtext, fname)
                    if forest:
                        case.forest_impugnacion = forest[:30]
                        break
            except Exception as e:
                logger.debug("v6.1 B.1 forest_impugnacion fallo case=%d: %s",
                             case_id, e)

        # fecha_apertura_incidente — corregido audit 2026-05-03
        #
        # Audit empírico identificó que captura mal "Documento generado en
        # [FECHA]" (esa es fecha de generación PDF, NO apertura del incidente).
        # Marker correcto del corpus SED: header de email Personería que
        # adjunta el incidente, format "Fecha [Día] [DD/MM/YYYY]".
        if not case.fecha_apertura_incidente and case.incidente in ("SI", "Sí"):
            patterns_fecha_inc = [
                # PATRÓN A (audit 2026-05-03): email Outlook directo Personería
                # Format: "Desde Personeria... Fecha Jue 12/02/2026 11:39 AM Para..."
                r"INCIDENTE\s+DE\s+DESACATO[^\n]{0,200}?(?:Desde|De)\s+[Pp]ersoneria[^\n]{0,150}?Fecha\s+\w+\s+(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
                # PATRÓN B (audit 2026-05-03): email Gmail forwardeado
                # Format: "Gmail - RV: AUTO APERTURA INCIDENTE DESACATO ... 11 de febrero de 2026 a las HH:MM"
                # Solo si el SUBJECT del email indica APERTURA (no abstención ni revocación).
                r"RV:\s*AUTO[^\n]*?APERTUR[AO][^\n]*?INCIDENTE[^\n]*?\s+(\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+de\s+\d{4})\s+a\s+las",
                # Patterns originales v8.1 (mantener como fallback)
                r"(?:apertura|abr(?:i[oó]|ese)|admit(?:i[oó]|ese))\s+(?:del?\s+)?incidente[^.]{0,100}?(\d{1,2}[\s/\-de]+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre|\d{1,2})[\s/\-de]+\d{2,4})",
                r"incidente\s+de\s+desacato\s+(?:de\s+fecha\s+)?(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
                r"(?:auto\s+de\s+\d+\s+de\s+)?(\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+(?:de\s+)?\d{2,4})[^.]{0,80}?(?:incidente|desacato|apertura)",
            ]
            for pat in patterns_fecha_inc:
                m = _re.search(pat, full_text_all, _re.IGNORECASE | _re.DOTALL)
                if m:
                    fecha = m.group(1).strip()
                    # Validar que NO sea una fecha "Documento generado en" (PDF gen)
                    # Buscar contexto previo a la fecha para descartar
                    pos = full_text_all.find(fecha)
                    if pos > 0:
                        ctx_pre = full_text_all[max(0, pos-80):pos].lower()
                        if "documento generado" in ctx_pre:
                            continue  # Saltar, es fecha de PDF gen
                    case.fecha_apertura_incidente = fecha[:50]
                    break

        # responsable_desacato y decision_incidente — v9.4.6
        # Reemplaza los patterns v8.1 (que producían "A JUVENTAL DIAZ MATEUS"
        # con prefijo "A " mal capturado) por las funciones validadas en
        # decision_extractor contra muestras reales SED.
        if case.incidente in ("SI", "Sí"):
            try:
                from backend.cognition.decision_extractor import (
                    extract_responsable_desacato as _resp_desac,
                    extract_decision_incidente as _dec_inc,
                )
                # Iterar docs de incidente (filename / doc_type)
                for d in case_ir.documents if hasattr(case_ir, "documents") else []:
                    fname = (d.filename if hasattr(d, "filename") else "") or ""
                    fname_lower = fname.lower()
                    is_inc = ("incident" in fname_lower or "desacato" in fname_lower
                              or "apertura" in fname_lower or "sancion" in fname_lower
                              or "auto" in fname_lower)
                    if not is_inc:
                        continue
                    # DocumentIR.zones es list[DocumentZone] (no dict)
                    dtext = ""
                    for z in (d.zones if hasattr(d, "zones") else []) or []:
                        ztext = getattr(z, "text", None) if not isinstance(z, dict) else z.get("text")
                        if ztext:
                            dtext += "\n" + ztext
                    if not dtext:
                        continue
                    if not case.responsable_desacato:
                        r = _resp_desac(dtext)
                        if r:
                            case.responsable_desacato = r[:200]
                    if not case.decision_incidente:
                        decis = _dec_inc(dtext)
                        if decis:
                            case.decision_incidente = decis[:300]
                    if case.responsable_desacato and case.decision_incidente:
                        break
            except Exception as e:
                logger.debug("v9.4.6 desacato extractors fallaron case=%d: %s",
                             case_id, e)

        db.commit()

        # =================================================================
        # FASE 4.5 NEURAL REFINEMENT (v8.0) — clasificadores sklearn entrenados
        # con dataset histórico Excel CONTROL TUTELAS (4,369 casos curados).
        # Solo predice campos vacíos; threshold de confianza por target.
        # =================================================================
        try:
            from backend.ml.inference.models import predict_field, is_available
            ml_text = (
                (case.asunto or "") + " "
                + (case.pretensiones or "") + " "
                + (case.observaciones or "") + " "
                + full_text_all[:3000]
            ).strip()

            ml_predictions = []  # para audit_log
            # tema_normalized → categoria_tematica
            if not getattr(case, "categoria_tematica", None) and is_available("tema_normalized"):
                pred = predict_field("tema_normalized", ml_text)
                if pred:
                    case.categoria_tematica = pred.value
                    ml_predictions.append(("categoria_tematica", pred))

            # direccion (L1) y dependencia (L2)
            if not case.direccion and is_available("direccion"):
                pred = predict_field("direccion", ml_text)
                if pred:
                    case.direccion = pred.value
                    ml_predictions.append(("direccion", pred))
            if not case.grupo and is_available("dependencia"):
                pred = predict_field("dependencia", ml_text)
                if pred:
                    case.grupo = pred.value
                    ml_predictions.append(("grupo", pred))

            # tipo (TUTELA/DESACATO) — solo si tipo_actuacion no está poblado
            if not getattr(case, "tipo_actuacion", None) and is_available("tipo"):
                pred = predict_field("tipo", ml_text)
                if pred:
                    case.tipo_actuacion = pred.value
                    ml_predictions.append(("tipo_actuacion", pred))

            for field, pred in ml_predictions:
                db.add(AuditLog(
                    case_id=case.id, field_name=field,
                    old_value="",
                    new_value=f"{pred.value} (conf={pred.confidence:.3f})"[:200],
                    action="ML_PREDICT",
                    source=f"sklearn_{pred.target}_{pred.model_version}",
                ))
            if ml_predictions:
                logger.info("V6 case=%d Capa 4.5 ML: %d predicciones",
                            case_id, len(ml_predictions))
                db.commit()
        except Exception as e:
            logger.debug("Capa 4.5 ML falló case=%d: %s", case_id, e)

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
            "derecho_vulnerado": case.derecho_vulnerado or "",
            "accionados": case.accionados or "",
            "accionante": case.accionante or "",
        }
        try:
            cog_results = cognitive_fill(case_meta, full_text, existing=None,
                                          documents=None)
            # Aplicar resultados:
            # - Por default, no sobrescribir si el campo ya tiene valor.
            # - Excepción: campo `accionante` SÍ se sobrescribe cuando el valor
            #   actual no parece nombre real (ej. "ANTECEDENTES", "pretende que")
            #   pero cognitive_fill encontró uno válido vía regex header / NER.
            from backend.cognition.folder_renamer import is_likely_real_name as _is_name
            for field, result in cog_results.items():
                current = getattr(case, field, None)
                if not current:
                    setattr(case, field, result.value)
                    continue
                if field == "accionante" and not _is_name(current) and _is_name(result.value):
                    logger.info("V6 case=%d accionante override: %r → %r (current no era nombre real)",
                                case_id, current[:40], result.value[:40])
                    setattr(case, field, result.value)
        except Exception as e:
            logger.debug("cognitive_fill falló para case=%d: %s", case_id, e)

        # =================================================================
        # Capa 4.6 v9.4: Reglas deterministas jurídicas (legal_schema)
        # Aplica derivación juzgado_2nd (factor funcional Decreto 1983/2017)
        # y clasificación SED L1/L2/L3 (Decretos 544/2021 + 048/2022).
        # Sin tokens IA. Nunca sobreescribe valores existentes.
        # =================================================================
        try:
            from backend.cognition.agent.semantic_enricher import apply_deterministic_rules
            case_dict = {col.name: getattr(case, col.name, None)
                         for col in case.__table__.columns}
            deterministic_updates = apply_deterministic_rules(case_dict)
            applied = 0
            for col, val in deterministic_updates.items():
                if val and not getattr(case, col, None):
                    setattr(case, col, val)
                    db.add(AuditLog(
                        case_id=case.id, field_name=col,
                        old_value="", new_value=str(val)[:200],
                        action="DETERMINISTIC_RULES",
                        source="legal_schema_v94",
                    ))
                    applied += 1
            if applied:
                db.commit()
                logger.info("V6 case=%d Capa 4.6 deterministas: %d campos rellenados",
                            case_id, applied)
        except Exception as e:
            logger.debug("Capa 4.6 deterministas falló case=%d: %s", case_id, e)

        # Timeline + clasificación
        tl = build_timeline(case)
        cls = classify_case(case, tl)
        case.origen = cls.origen
        case.estado_incidente = cls.estado_incidente
        db.commit()
        stats["phase_entropies"]["post_cognition"] = entropy_of_case(case).entropy_bits

        # =================================================================
        # Pod mode: saltar Capas 6-7 (las hace el cliente con su DB real)
        # =================================================================
        if skip_consolidation_and_persist:
            stats["status"] = "PHASES_0_5_OK"
            stats["iterations"] = 1
            return stats

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
        # Capa 6.5 (NEW): IA local complementaria — llena campos vacíos aplicables
        # antes de calcular entropy. Reduce REVISION dramáticamente.
        # =================================================================
        try:
            from backend.cognition.cognitive_complementary_ai import fill_missing_fields_with_ia
            ia_stats = fill_missing_fields_with_ia(db, case, full_text)
            stats["complementary_ia"] = ia_stats
            if ia_stats.get("filled", 0) > 0:
                logger.info("V6 case=%d Fase 6.5: IA llenó %d campos", case_id, ia_stats["filled"])
        except Exception as e:
            logger.debug("V6 case=%d Fase 6.5 falló: %s", case_id, e)

        # =================================================================
        # Capa 6.6 (NEW): Flag normalizer — auto-corrige impugnacion/incidente
        # cuando los datos contradicen las flags. Elimina inconsistencias falsas.
        # =================================================================
        try:
            from backend.cognition.flag_normalizer import normalize_flags
            flag_changes = normalize_flags(case)
            if flag_changes:
                logger.info("V6 case=%d Fase 6.6: flags normalizadas: %s", case_id, flag_changes)
                stats["flag_normalizations"] = flag_changes
        except Exception as e:
            logger.debug("V6 case=%d Fase 6.6 falló: %s", case_id, e)

        # =================================================================
        # Capa 6.7 (NEW): Reglas deterministas de enriquecimiento
        # juzgado_2nd vía mapa judicial Santander (Decreto 1983/2017) +
        # SED tematic L1/L2/L3. Sin LLM. ~16ms/caso.
        # Lift empírico: +25 puntos juzgado_2nd cuando impugnacion=SI.
        # =================================================================
        try:
            from backend.cognition.agent.semantic_enricher import apply_deterministic_rules

            class _CaseRow:
                """Adapter sqlite3.Row-like sobre SQLAlchemy Case."""
                _fields = ("id", "juzgado_2nd", "impugnacion", "juzgado",
                           "accionados", "ciudad", "asunto", "pretensiones",
                           "direccion", "grupo", "equipo", "categoria_tematica")
                def __init__(self, c):
                    self._d = {f: getattr(c, f, None) for f in self._fields}
                def keys(self):
                    return self._d.keys()
                def __getitem__(self, k):
                    return self._d.get(k)
                def __contains__(self, k):
                    return k in self._d

            derived = apply_deterministic_rules(_CaseRow(case))
            if derived:
                for k, v in derived.items():
                    if hasattr(case, k) and not getattr(case, k):
                        setattr(case, k, v)
                db.flush()
                logger.info("V6 case=%d Fase 6.7: deterministas %d campos: %s",
                            case_id, len(derived), list(derived.keys()))
                stats["deterministic_enrichment"] = derived
        except Exception as e:
            logger.debug("V6 case=%d Fase 6.7 falló: %s", case_id, e)

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

        # F2 (2026-05-02): confidence scoring por campo, post-persistencia.
        # Solo activo si USE_FIELD_CONFIDENCE=True. Computa score 0-1 por campo
        # del protocolo y lo persiste en cases.field_confidences_json.
        # No modifica valores extraídos — solo agrega metadata para UI/SLA.
        try:
            from backend.cognition.confidence import persist_confidences
            persist_confidences(case, db)
        except Exception as e:
            logger.debug("F2 confidence scoring falló case=%d: %s", case_id, e)

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
