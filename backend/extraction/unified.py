"""Extractor Unificado con IR (Intermediate Representation).

Reemplaza tanto process_folder (Pipeline) como smart_extract_case (Agent)
con un solo motor de 6 fases:

1. INGESTIÓN: texto de documentos + clasificación
2. IR: representación intermedia estructurada (fitz/docx)
3. REGEX: 13 extractores mecánicos sobre zonas IR (~14 campos)
4. IA: prompt compacto solo para ~8 campos semánticos
5. MERGE: resolver regex vs IA por campo
6. PERSISTIR: guardar en DB, reasoning, KB, rename
"""

import logging
import re
import threading
import time

# Lock para operaciones I/O no-thread-safe (rename de carpetas, SQLite FTS5)
_io_lock = threading.Lock()
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from backend.database.models import Case, Document, Email, Extraction, AuditLog, TokenUsage, PrivacyStats
from backend.extraction.ir_models import CaseIR, DocumentIR
from backend.extraction.ir_builder import build_case_ir
from backend.privacy import redact_payload, rehydrate_fields, RedactionContext, assert_clean
from backend.privacy.redactor import persist_mapping
from backend.extraction.pipeline import (
    extract_document_text, classify_doc_type, verify_document_belongs,
    _rename_folder_if_needed, _check_and_link_to_base_case,
    _cross_validate_radicado, _validate_extracted_fields,
    _auto_reassign_document,
)
from backend.extraction.ai_extractor import (
    extract_with_ai, AIExtractionResult, SYSTEM_PROMPT,
)
from backend.agent.extractors.registry import (
    _EXTRACTORS, pre_extract_all, resolve_field, REGEX_PREFERRED_FIELDS,
)
from backend.agent.extractors.base import ExtractionResult
from backend.agent.forest_extractor import extract_forest_from_sources

logger = logging.getLogger("tutelas.unified")


def _collect_known_entities(regex_results: dict, case: Case) -> dict[str, list[str]]:
    """Construye blacklist determinística para la capa PII a partir de datos ya extraídos.

    La blacklist tiene prioridad máxima en el detector: garantiza que los nombres
    y CCs ya identificados por regex/forensic sean redactados sin depender del NER.
    """
    known: dict[str, list[str]] = {"PERSON": [], "CC": [], "NUIP": [], "RADICADO_FOREST": []}
    # De regex_results (clave → ExtractionResult)
    for key in ("accionante", "abogado_responsable"):
        r = regex_results.get(key)
        if r and r.value:
            known["PERSON"].append(r.value.strip())
    # De campos ya persistidos en el caso (si es re-extract)
    for attr, bucket in (
        ("accionante", "PERSON"), ("abogado_responsable", "PERSON"),
        ("radicado_forest", "RADICADO_FOREST"),
    ):
        v = getattr(case, attr, None)
        if v and v.strip():
            known[bucket].append(v.strip())
    # Deduplicar
    for k in list(known.keys()):
        known[k] = list({v for v in known[k] if v})
    return known


def unified_extract(db: Session, case: Case, base_dir: str = "",
                    classify_docs: bool = False) -> dict:
    """Extracción unificada: IR + Regex + IA enfocada.

    Funciona tanto para batch como individual — misma calidad, mismo fallback.

    Returns: dict con estadísticas del procesamiento.
    """
    start_time = time.time()
    stats = {
        "documents_extracted": 0,
        "documents_failed": 0,
        "regex_fields": 0,
        "ia_fields": 0,
        "total_fields": 0,
        "ai_error": None,
        "method": "unified_ir",
    }

    case.processing_status = "EXTRAYENDO"
    db.commit()

    try:
        # =================================================================
        # FASE 1: INGESTIÓN — extraer texto de documentos nuevos
        # =================================================================
        logger.info("Fase 1: Ingestión de %d documentos para caso %d", len(case.documents), case.id)

        lawyer_from_docx = ""
        DOCX_WITH_LAWYER = {"DOCX_RESPUESTA", "DOCX_CONTESTACION", "DOCX_DESACATO",
                            "DOCX_IMPUGNACION", "DOCX_CUMPLIMIENTO"}

        for doc in case.documents:
            if doc.extracted_text:
                # Ya tiene texto — verificar pertenencia
                v_status, v_detalle = verify_document_belongs(case, doc)
                doc.verificacion = v_status
                doc.verificacion_detalle = v_detalle
                stats["documents_extracted"] += 1
                continue

            if not doc.file_path:
                continue

            text, method = extract_document_text(doc)
            if text.strip():
                doc.extracted_text = text
                doc.extraction_method = method
                doc.extraction_date = datetime.utcnow()
                v_status, v_detalle = verify_document_belongs(case, doc)
                doc.verificacion = v_status
                doc.verificacion_detalle = v_detalle
                stats["documents_extracted"] += 1
            else:
                stats["documents_failed"] += 1

        # Extraer abogado de DOCX footers
        from backend.extraction.docx_extractor import extract_docx
        for doc in case.documents:
            ext = Path(doc.file_path).suffix.lower() if doc.file_path else ""
            if ext in (".docx", ".doc") and doc.file_path:
                doc_type = classify_doc_type(doc.filename)
                if doc_type in DOCX_WITH_LAWYER:
                    try:
                        docx_result = extract_docx(doc.file_path)
                        if docx_result.lawyer_name and not lawyer_from_docx:
                            lawyer_from_docx = docx_result.lawyer_name
                    except Exception:
                        pass

        db.commit()

        # =================================================================
        # FASE 2: IR — construir representación intermedia
        # =================================================================
        logger.info("Fase 2: Construyendo IR estructurado")
        case_ir = build_case_ir(db, case)

        # =================================================================
        # FASE 3: REGEX — extracción mecánica sobre zonas IR
        # =================================================================
        logger.info("Fase 3: Extracción regex sobre %d zonas", sum(len(d.zones) for d in case_ir.documents))

        # Preparar doc_dicts con zonas para los extractores
        doc_dicts = []
        for doc_ir in case_ir.documents:
            d = {
                "filename": doc_ir.filename,
                "doc_type": doc_ir.doc_type,
                "text": doc_ir.full_text,
                "full_text": doc_ir.full_text,
                "content": doc_ir.full_text,
                "priority": doc_ir.priority,
                "zones": [
                    {
                        "zone_type": z.zone_type,
                        "text": z.text,
                        "metadata": z.metadata,
                        "page": z.page,
                        "confidence": z.confidence,
                    }
                    for z in doc_ir.zones
                ],
            }
            doc_dicts.append(d)

        # Ejecutar extractores IR
        case_emails = db.query(Email).filter(Email.case_id == case.id).all()
        regex_results = {}

        for field_name, extractor in _EXTRACTORS.items():
            try:
                result = extractor.extract_regex(doc_dicts, case_emails)
                if result:
                    is_valid, reason = extractor.validate(result.value)
                    if is_valid:
                        regex_results[field_name] = result
            except Exception as e:
                logger.debug("Extractor %s fallo: %s", field_name, e)

        # FOREST extractor especial
        forest = extract_forest_from_sources(doc_dicts, case_emails)
        if forest:
            regex_results["radicado_forest"] = ExtractionResult(
                value=forest.value, confidence=forest.confidence if isinstance(forest.confidence, int) else 90,
                source=forest.source, method="regex",
                reasoning=f"FOREST de {forest.source}",
            )

        # Guardar campos regex directamente en Case (protección si IA falla)
        saved_regex = 0
        for field_name, result in regex_results.items():
            attr = Case.CSV_FIELD_MAP.get(field_name.upper())
            if attr and not getattr(case, attr, None):
                setattr(case, attr, result.value)
                saved_regex += 1
                db.add(AuditLog(
                    case_id=case.id, field_name=field_name,
                    old_value="", new_value=result.value,
                    action="REGEX_IR", source=result.source,
                ))

        # Abogado de DOCX siempre gana
        if lawyer_from_docx:
            case.abogado_responsable = lawyer_from_docx
            regex_results["abogado_responsable"] = ExtractionResult(
                value=lawyer_from_docx, confidence=95, source="docx_footer",
                method="docx", reasoning="Abogado de footer DOCX",
            )
            saved_regex += 1

        stats["regex_fields"] = saved_regex
        logger.info("Fase 3 completa: %d campos regex guardados", saved_regex)
        db.commit()

        # =================================================================
        # FASE 3.5 (v5.2): FORENSIC ENRICHMENT — emula cognicion humana sin IA
        # Complementa regex con: CC, NUIP menor, tutela online, acta reparto,
        # subject del email md, abogado del footer docx, clasificacion por contenido.
        # =================================================================
        try:
            from backend.services.folder_correlator import correlate_folder
            if case.folder_path and Path(case.folder_path).is_dir():
                forensic_report = correlate_folder(case.folder_path)
                stats["forensic"] = {
                    "file_count": forensic_report.get("file_count", 0),
                    "recommendation": forensic_report.get("recommendation", ""),
                    "accionantes_detected": forensic_report.get("accionantes_detected", []),
                    "ccs_detected": forensic_report.get("cc_detected", []),
                    "rad23_detected": forensic_report.get("rad23_detected", []),
                }
                # Si forensic detecto CC y el caso no la tiene en observaciones, añadirla
                ccs = forensic_report.get("cc_detected", [])
                if ccs:
                    current_obs = case.observaciones or ""
                    cc_missing = [cc for cc in ccs if cc not in current_obs]
                    if cc_missing:
                        cc_note = f"[CC detectada forensic: {', '.join(cc_missing)}]"
                        case.observaciones = (current_obs + " " + cc_note).strip()[:3000]
                        stats["forensic_cc_added"] = cc_missing
                # Si forensic detecto rad23 y el caso no lo tiene
                rads = forensic_report.get("rad23_detected", [])
                if rads and not case.radicado_23_digitos:
                    case.radicado_23_digitos = rads[0]
                    stats["forensic_rad23_added"] = rads[0]
                    saved_regex += 1
                # Si forensic detecto accionante y el caso no lo tiene
                accs = forensic_report.get("accionantes_detected", [])
                if accs and not case.accionante:
                    case.accionante = accs[0]
                    stats["forensic_accionante_added"] = accs[0]
                    saved_regex += 1
                db.commit()
                logger.info("Fase 3.5 Forensic: CCs=%d, rad23=%d, accionantes=%d",
                            len(ccs), len(rads), len(accs))
        except Exception as e:
            logger.debug("Forensic enrichment skipped: %s", e)

        # =================================================================
        # FASE 3.6 (v5.3.1): COGNICIÓN LOCAL — rellenar campos semánticos
        # SIN IA externa antes de decidir si la necesitamos.
        # =================================================================
        cognitive_results = {}
        try:
            from backend.cognition import cognitive_fill
            # Concatenar textos de documentos para visión global del caso
            full_text_parts = []
            for d in case.documents[:15]:  # límite para no explotar memoria
                if d.extracted_text:
                    full_text_parts.append(d.extracted_text)
            full_text = "\n\n".join(full_text_parts)
            case_meta = {
                "id": case.id,
                "fecha_ingreso": case.fecha_ingreso or "",
                "radicado_23_digitos": case.radicado_23_digitos or "",
                "radicado_forest": case.radicado_forest or "",
                "abogado_responsable": case.abogado_responsable or "",
                "incidente": case.incidente or "",
            }
            # Lista de docs con filename+text para timeline_builder
            docs_for_cognition = [
                {"filename": d.filename, "text": d.extracted_text or "",
                 "doc_type": d.doc_type or ""}
                for d in case.documents[:15] if d.extracted_text
            ]
            cognitive_results = cognitive_fill(
                case_meta, full_text, regex_results,
                documents=docs_for_cognition,
            )
            stats["cognitive_filled"] = len(cognitive_results)
            stats["cognitive_fields"] = sorted(cognitive_results.keys())
            logger.info("Fase 3.6 Cognición: %d campos llenados sin IA: %s",
                        len(cognitive_results), sorted(cognitive_results.keys()))
        except Exception as e:
            logger.warning("Cognición local falló: %s", e)

        # =================================================================
        # FASE 4: IA — solo campos semánticos que cognición NO logró
        # =================================================================
        semantic_fields = {
            "accionante", "accionados", "vinculados", "derecho_vulnerado",
            "asunto", "pretensiones", "sentido_fallo_1st", "sentido_fallo_2nd",
            "observaciones", "oficina_responsable", "quien_impugno",
            "decision_incidente",
        }
        # Quitar campos que regex o cognición ya llenó con suficiente confianza
        fields_needed = []
        for f in semantic_fields:
            if f in regex_results and regex_results[f].confidence >= 80:
                continue  # Regex ya lo tiene con confianza alta
            if f in cognitive_results and cognitive_results[f].confidence >= 65:
                continue  # Cognición lo llenó con confianza razonable
            attr = Case.CSV_FIELD_MAP.get(f.upper())
            if attr and getattr(case, attr, None):
                continue  # Ya tiene valor en DB
            fields_needed.append(f)

        ia_results = {}
        if fields_needed:
            logger.info("Fase 4: IA para %d campos semanticos: %s", len(fields_needed), fields_needed)

            # Construir prompt compacto con zonas IR relevantes
            compact_prompt = case_ir.to_compact_prompt(fields_needed)

            # Inyectar contexto del Knowledge Base si está habilitado
            from backend.core.settings import settings as _settings
            if _settings.KB_ENHANCED_EXTRACTION:
                try:
                    from backend.knowledge.search import search_by_case
                    kb_entries = search_by_case(db, case.id)
                    if kb_entries:
                        kb_context = "\n\n===CONTEXTO_KB (datos previos del caso)===\n"
                        for entry in kb_entries[:5]:  # Top 5 entradas
                            kb_context += f"[{entry.source_type}] {entry.source_name}: {(entry.content or '')[:500]}\n"
                        compact_prompt += kb_context
                        logger.info("KB: %d entradas inyectadas al prompt", min(len(kb_entries), 5))
                except Exception as e:
                    logger.debug("KB enhancement skipped: %s", e)

            # Cargar system prompt compacto
            try:
                prompt_path = Path(__file__).parent.parent / "prompts" / "extraction_compact.txt"
                system_prompt = prompt_path.read_text(encoding="utf-8")
            except Exception:
                system_prompt = SYSTEM_PROMPT  # Fallback al prompt original

            # Preparar doc_texts para extract_with_ai
            ia_doc_texts = [
                {"filename": "CONTEXTO_IR", "text": compact_prompt, "doc_type": "SISTEMA"},
            ]

            # PDF paths para multimodal (solo documentos criticos sin texto)
            pdf_file_paths = []
            for doc in case.documents:
                if doc.file_path and Path(doc.file_path).suffix.lower() == ".pdf":
                    if Path(doc.file_path).exists():
                        doc_type = classify_doc_type(doc.filename)
                        if doc_type in ("PDF_AUTO_ADMISORIO", "PDF_SENTENCIA"):
                            pdf_file_paths.append({
                                "filename": doc.filename,
                                "file_path": doc.file_path,
                            })

            # Llamar a IA (paralelo o secuencial segun feature flag)
            from backend.core.settings import settings as _ai_settings
            # F3 (v5.0): propagar rad23 oficial del caso para anti-contaminacion
            # en campos narrativos (obs/asunto). Evita que la IA mencione
            # "Caso 2026-66132" cuando el folder_name esta malformado pero el
            # rad23 del caso tiene el consecutivo real.
            rad_oficial = (case.radicado_23_digitos or "").strip()

            # =================================================================
            # v5.3 — CAPA PII: redactar antes de enviar a IA externa
            # =================================================================
            pii_mode = case.pii_mode or _ai_settings.PII_MODE_DEFAULT
            pii_stats = None
            if _ai_settings.PII_REDACTION_ENABLED:
                # Recopilar entidades ya conocidas (regex + forensic) como blacklist determinística
                known_entities = _collect_known_entities(regex_results, case)
                redaction_ctx = RedactionContext(
                    case_id=case.id, mode=pii_mode, known_entities=known_entities,
                )
                payload = redact_payload(ia_doc_texts, redaction_ctx)
                violations = assert_clean(
                    payload.docs, mode=pii_mode,
                    known_entities=known_entities,
                )
                if violations and _ai_settings.PII_GATE_STRICT:
                    logger.warning(
                        "PII gate bloqueó envío IA: %d violaciones (case=%s mode=%s). Marcando REVISION.",
                        len(violations), case.id, pii_mode,
                    )
                    case.processing_status = "REVISION"
                    stats["pii_gate_blocked"] = True
                    stats["pii_violations"] = [{"kind": v.kind, "snippet": v.snippet[:40]} for v in violations[:10]]
                    db.add(PrivacyStats(
                        case_id=case.id, mode=pii_mode,
                        spans_detected=payload.stats.get("spans_detected", 0),
                        tokens_minted=payload.stats.get("tokens_minted", 0),
                        violations_count=len(violations), gate_blocked=True,
                        redactor_ms=payload.stats.get("redactor_ms", 0),
                        notes=f"Violations: {[v.kind for v in violations[:5]]}",
                    ))
                    db.commit()
                    # No llamamos IA. El merge usará solo regex_results.
                    ia_doc_texts = None
                else:
                    ia_doc_texts = payload.docs
                    persist_mapping(db, case.id, payload.mapping)
                    pii_stats = PrivacyStats(
                        case_id=case.id, mode=pii_mode,
                        spans_detected=payload.stats.get("spans_detected", 0),
                        tokens_minted=payload.stats.get("tokens_minted", 0),
                        violations_count=len(violations), gate_blocked=False,
                        redactor_ms=payload.stats.get("redactor_ms", 0),
                        notes=f"Warn: {len(violations)} violaciones (gate non-strict)" if violations else None,
                    )
                    stats["pii_mode"] = pii_mode
                    stats["pii_tokens"] = payload.stats.get("tokens_minted", 0)

            if ia_doc_texts is None:
                ai_result = None
                raw_ai_results = []
            else:
                ai_result = extract_with_ai(
                    ia_doc_texts,
                    case.folder_name or "",
                    pdf_file_paths=pdf_file_paths[:4] if pdf_file_paths else None,
                    radicado_oficial=rad_oficial,
                )
                raw_ai_results = [ai_result]

            # Registrar tokens: 1 TokenUsage por provider ejecutado
            from backend.extraction.ai_extractor import PROVIDERS
            for r in (raw_ai_results or []):
                r_model_info = PROVIDERS.get(r.provider or "", {}).get("models", {}).get(r.model or "", {}) if r.provider else {}
                r_inp_price = r_model_info.get("input_price", 0)
                r_out_price = r_model_info.get("output_price", 0)
                r_cost_in = r.tokens_input * r_inp_price / 1_000_000
                r_cost_out = r.tokens_output * r_out_price / 1_000_000
                db.add(TokenUsage(
                    provider=r.provider or "unknown",
                    model=r.model or "unknown",
                    tokens_input=r.tokens_input,
                    tokens_output=r.tokens_output,
                    cost_input=f"{r_cost_in:.6f}",
                    cost_output=f"{r_cost_out:.6f}",
                    cost_total=f"{r_cost_in + r_cost_out:.6f}",
                    case_id=case.id,
                    fields_extracted=len(r.fields),
                    duration_ms=r.duration_ms,
                    error=r.error,
                    chunk_index=r.chunks_used,
                ))

            if ai_result is None:
                # PII gate bloqueó envío — no hubo llamada IA
                stats["ai_skipped_pii_gate"] = True
            elif ai_result.error:
                logger.warning("IA fallo: %s (pero %d campos regex ya guardados)", ai_result.error, saved_regex)
                stats["ai_error"] = ai_result.error
            else:
                # v5.3: REHIDRATAR tokens antes de persistir en DB
                if _ai_settings.PII_REDACTION_ENABLED:
                    import time as _t
                    _t0 = _t.time()
                    rehydrated_fields = {}
                    for fname, fresult in ai_result.fields.items():
                        from backend.privacy import rehydrate_text as _rehyd
                        rehydrated_fields[fname] = type(fresult)(
                            value=_rehyd(db, case.id, fresult.value or ""),
                            confidence=fresult.confidence,
                            source=fresult.source,
                        )
                    ai_result.fields = rehydrated_fields
                    if pii_stats is not None:
                        pii_stats.rehydrator_ms = int((_t.time() - _t0) * 1000)

                # Convertir AI fields a ExtractionResult para merge.
                # Normalizar key a lowercase: la IA devuelve MAYUSCULAS (del prompt)
                # pero regex_results usa minusculas (keys del registry). Sin esto,
                # all_fields en Fase 5 tratara "radicado_23_digitos" y
                # "RADICADO_23_DIGITOS" como campos distintos, y el segundo
                # sobrescribira al primero al escribir en case.
                for fname, fresult in ai_result.fields.items():
                    key = fname.lower() if isinstance(fname, str) else fname
                    ia_results[key] = ExtractionResult(
                        value=fresult.value,
                        confidence=90 if fresult.confidence == "ALTA" else 70 if fresult.confidence == "MEDIA" else 50,
                        source=fresult.source, method="ia",
                        reasoning=f"IA ({ai_result.provider}/{ai_result.model})",
                    )

            if ai_result is not None:
                stats["tokens_input"] = ai_result.tokens_input
                stats["tokens_output"] = ai_result.tokens_output
                stats["provider"] = ai_result.provider
                stats["model"] = ai_result.model

            if pii_stats is not None:
                db.add(pii_stats)
                db.commit()

        else:
            logger.info("Fase 4: Todos los campos ya cubiertos por regex, IA no necesaria")

        # =================================================================
        # FASE 5: MERGE — resolver regex vs IA por campo
        # =================================================================
        logger.info("Fase 5: Merge %d regex + %d IA", len(regex_results), len(ia_results))

        all_fields = set(list(regex_results.keys()) + list(ia_results.keys()) + list(cognitive_results.keys()))
        final_fields = {}

        for fname in all_fields:
            regex_r = regex_results.get(fname)
            ai_r = ia_results.get(fname)
            cog_r = cognitive_results.get(fname)
            # Merge de 3 fuentes: regex > cognition > ai (cuando cognition tiene
            # confianza razonable). Si no hay cognition o confianza baja, cae al
            # merge clásico regex+ia.
            if cog_r and (not ai_r) and (not regex_r or regex_r.confidence < 80):
                # Solo cognición disponible
                resolved = cog_r
            elif cog_r and regex_r and regex_r.confidence < 80 and (not ai_r):
                resolved = cog_r if cog_r.confidence > regex_r.confidence else regex_r
            else:
                resolved = resolve_field(fname, regex_r, ai_r)
                # Si resolve_field no encontró nada pero cognition sí, usarlo
                if (not resolved or not resolved.value) and cog_r and cog_r.value:
                    resolved = cog_r
            if resolved and resolved.value:
                final_fields[fname] = resolved.value

        # Guard observaciones: si los documentos y emails del caso no cambiaron
        # desde la ultima extraccion, preservar observaciones antigua para evitar
        # rewrites estocasticos de la IA que no aportan informacion nueva.
        # El docs_fingerprint se guarda en audit_log con action=OBS_FINGERPRINT.
        import hashlib
        hashes = sorted(
            [d.file_hash for d in case.documents if d.file_hash] +
            [e.message_id for e in db.query(Email).filter(Email.case_id == case.id).all() if e.message_id]
        )
        current_fp = hashlib.md5("|".join(hashes).encode()).hexdigest() if hashes else ""
        last_fp_row = db.query(AuditLog).filter(
            AuditLog.case_id == case.id,
            AuditLog.action == "OBS_FINGERPRINT",
        ).order_by(AuditLog.id.desc()).first()
        last_fp = last_fp_row.new_value if last_fp_row else ""
        docs_unchanged = bool(current_fp) and current_fp == last_fp
        if docs_unchanged and (case.observaciones or "").strip():
            logger.info("Observaciones: docs sin cambios (fp=%s), preservando anterior", current_fp[:8])
            final_fields.pop("observaciones", None)
            stats["observaciones_preserved"] = True

        # Guardar campos resueltos en Case
        ia_saved = 0
        for fname, value in final_fields.items():
            attr = Case.CSV_FIELD_MAP.get(fname.upper())
            if not attr:
                continue
            old_val = getattr(case, attr, None) or ""
            if not old_val.strip() or fname in ia_results:
                setattr(case, attr, value)
                if old_val != value:
                    db.add(AuditLog(
                        case_id=case.id, field_name=fname,
                        old_value=old_val, new_value=value,
                        action="UNIFIED_EXTRACT",
                        source=f"regex+ia",
                    ))
                    ia_saved += 1

        # Registrar fingerprint actual para comparar en la proxima extraccion
        if current_fp:
            db.add(AuditLog(
                case_id=case.id, field_name="docs_fingerprint",
                old_value=last_fp, new_value=current_fp,
                action="OBS_FINGERPRINT", source="unified_extract",
            ))

        stats["ia_fields"] = ia_saved
        stats["total_fields"] = saved_regex + ia_saved

        # =================================================================
        # FASE 6: VALIDAR + PERSISTIR
        # =================================================================
        logger.info("Fase 6: Validación y persistencia")

        # Post-validación
        try:
            from backend.extraction.post_validator import validate_extraction
            current = {}
            for csv_col, attr in Case.CSV_FIELD_MAP.items():
                val = getattr(case, attr, None)
                if val:
                    current[attr] = str(val)
            validated, warnings = validate_extraction(case, current)
            for field, value in validated.items():
                if hasattr(case, field):
                    setattr(case, field, value if value else None)
            if warnings:
                stats["validation_warnings"] = warnings
        except Exception:
            pass

        # Anti-contaminación: adaptar final_fields a formato esperado
        try:
            # _cross_validate_radicado espera dict[str, ExtractionResult]
            # final_fields es dict[str, str] — crear wrapper
            from types import SimpleNamespace
            cross_fields = {}
            for k, v in final_fields.items():
                cross_fields[k.upper()] = SimpleNamespace(value=v)
            _cross_validate_radicado(case, cross_fields, db, stats)
        except Exception as e:
            logger.debug("Anti-contaminación: %s", e)

        # Defaults
        if not case.incidente:
            case.incidente = "NO"
        if case.sentido_fallo_1st and not case.impugnacion:
            case.impugnacion = "NO"

        # OBSERVACIONES fallback
        if not case.observaciones and case.accionante:
            obs = []
            if case.asunto:
                obs.append(case.asunto)
            if case.sentido_fallo_1st:
                obs.append(f"Fallo 1ra instancia: {case.sentido_fallo_1st}")
            if case.impugnacion == "SI":
                obs.append("Fue impugnado")
            if case.incidente == "SI":
                obs.append("Tiene incidente de desacato")
            if obs:
                case.observaciones = ". ".join(obs) + "."

        # Abogado override final
        if lawyer_from_docx:
            case.abogado_responsable = lawyer_from_docx

        # F8 (v5.0): validacion pre-COMPLETO — exigir rad23 valido o folder+accionante.
        # Un caso sin rad23 NI nombre real del accionante no deberia marcarse COMPLETO.
        _rad23 = (case.radicado_23_digitos or "").strip()
        _rad23_digits = re.sub(r"\D", "", _rad23) if _rad23 else ""
        _has_valid_rad23 = len(_rad23_digits) >= 18
        _has_named_folder = bool(
            case.folder_name
            and "[PENDIENTE" not in (case.folder_name or "")
            and re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}", case.folder_name or "")
        )
        _has_accionante = bool((case.accionante or "").strip())

        # F9 (v5.0): detectar duplicado potencial por rad_corto canonico.
        # Buscar otro caso con mismo rad_corto (derivado de rad23 oficial). Si existe
        # y el actual es distinto, registrar en stats y log — la reconsolidacion
        # automatica se hace en remediacion historica (R1/R3) con revision manual.
        if _has_valid_rad23:
            rm_self = re.search(r"(20\d{2})(\d{5})\d{2}$", _rad23_digits)
            if rm_self:
                self_rc = f"{rm_self.group(1)}-{rm_self.group(2)}"
                self_jud = _rad23_digits[5:12] if len(_rad23_digits) >= 12 else ""
                candidates = db.query(Case).filter(
                    Case.id != case.id,
                    Case.processing_status != "DUPLICATE_MERGED",
                ).all()
                for other in candidates:
                    # Comparar por rad23 si ambos lo tienen
                    if other.radicado_23_digitos:
                        oth_d = re.sub(r"\D", "", other.radicado_23_digitos)
                        if len(oth_d) >= 18 and oth_d[:20] == _rad23_digits[:20]:
                            stats["potential_duplicate_of"] = other.id
                            logger.warning(
                                "F9: caso %d y %d tienen mismo rad23 %s — revisar consolidacion",
                                case.id, other.id, self_rc,
                            )
                            break
                    # Comparar por rad_corto + juzgado (cuando el otro no tiene rad23)
                    oth_folder = other.folder_name or ""
                    mf = re.match(r"(20\d{2})-0*(\d{1,5})\b", oth_folder)
                    if mf:
                        oth_rc = f"{mf.group(1)}-{int(mf.group(2)):05d}"
                        # Solo si NO es un folder forest-like (seq>=10000 o igual a forest del otro)
                        oth_seq = int(mf.group(2))
                        oth_forest_clean = re.sub(r"\D", "", other.radicado_forest or "")
                        oth_is_forest_folder = oth_seq >= 10000 and (
                            not oth_forest_clean or str(oth_seq) in oth_forest_clean
                        )
                        if not oth_is_forest_folder and oth_rc == self_rc:
                            stats["potential_duplicate_of"] = other.id
                            logger.warning(
                                "F9: caso %d tiene rad %s que coincide con folder %d ('%s') — revisar",
                                case.id, self_rc, other.id, oth_folder[:40],
                            )
                            break

        if stats.get("ai_error") and saved_regex < 5:
            case.processing_status = "REVISION"
        elif not _has_valid_rad23 and not (_has_named_folder and _has_accionante):
            # F8: sin rad23 valido y sin folder+accionante definido → no es COMPLETO
            case.processing_status = "REVISION"
            stats["reason_revision"] = "F8: falta rad23 valido o folder+accionante"
            logger.info(
                "F8: caso %d marcado REVISION (rad23_valido=%s, folder_nombrado=%s, accionante=%s)",
                case.id, _has_valid_rad23, _has_named_folder, _has_accionante,
            )
        else:
            case.processing_status = "COMPLETO"
            case.updated_at = datetime.utcnow()

        # Renombrar carpeta si aplica (serializado para thread-safety).
        # Si falla (p.ej. IntegrityError por folder_name UNIQUE colisión con
        # caso que comparte rad23), el flush deja la sesión sucia: obligatorio
        # db.rollback() antes de continuar, de lo contrario el db.commit() final
        # explota con "Session rolled back due to previous exception during flush".
        try:
            with _io_lock:
                _rename_folder_if_needed(db, case, stats)
                stats["renamed"] = True
        except Exception as _e_rename:
            logger.warning("F9 rename falló caso %d: %s — rollback defensivo", case.id, _e_rename)
            try:
                db.rollback()
            except Exception:
                pass

        # Link a caso base
        try:
            _check_and_link_to_base_case(db, case, stats)
        except Exception as _e_link:
            logger.warning("link_base falló caso %d: %s — rollback defensivo", case.id, _e_link)
            try:
                db.rollback()
            except Exception:
                pass

        # Knowledge Base (serializado — SQLite FTS5 single-writer)
        try:
            with _io_lock:
                from backend.knowledge.indexer import index_case_fields
                index_case_fields(db, case.id, final_fields)
        except Exception as _e_kb:
            logger.warning("KB index falló caso %d: %s — rollback defensivo", case.id, _e_kb)
            try:
                db.rollback()
            except Exception:
                pass

        # Re-aplicar processing_status y updated_at después de posibles rollbacks
        # (el rollback revierte estos cambios si venían en la misma transacción).
        _rad23 = (case.radicado_23_digitos or "").strip()
        _rad23_digits = re.sub(r"\D", "", _rad23) if _rad23 else ""
        _has_valid_rad23 = len(_rad23_digits) >= 18
        _has_named_folder = bool(
            case.folder_name
            and "[PENDIENTE" not in (case.folder_name or "")
            and re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}", case.folder_name or "")
        )
        _has_accionante = bool((case.accionante or "").strip())
        if stats.get("ai_error") and saved_regex < 5:
            case.processing_status = "REVISION"
        elif not _has_valid_rad23 and not (_has_named_folder and _has_accionante):
            case.processing_status = "REVISION"
        else:
            case.processing_status = "COMPLETO"
            case.updated_at = datetime.utcnow()

        db.commit()

        elapsed = round(time.time() - start_time, 1)
        stats["elapsed_seconds"] = elapsed
        logger.info(
            "Extracción unificada completa: caso %d (%s) | %d regex + %d IA = %d campos | %.1fs | status=%s",
            case.id, case.folder_name, saved_regex, ia_saved,
            stats["total_fields"], elapsed, case.processing_status,
        )

        return stats

    except Exception as e:
        logger.error("Error en extracción unificada caso %d: %s", case.id, e, exc_info=True)
        case.processing_status = "REVISION"
        db.commit()
        stats["ai_error"] = str(e)
        return stats
