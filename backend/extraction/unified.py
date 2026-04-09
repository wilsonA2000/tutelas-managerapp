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
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from backend.database.models import Case, Document, Email, Extraction, AuditLog, TokenUsage
from backend.extraction.ir_models import CaseIR, DocumentIR
from backend.extraction.ir_builder import build_case_ir
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
            attr = Case.CSV_FIELD_MAP.get(field_name)
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
        # FASE 4: IA — solo campos semánticos
        # =================================================================
        semantic_fields = {
            "accionante", "accionados", "vinculados", "derecho_vulnerado",
            "asunto", "pretensiones", "sentido_fallo_1st", "sentido_fallo_2nd",
            "observaciones", "oficina_responsable", "quien_impugno",
            "decision_incidente",
        }
        # Quitar campos que regex ya lleno con alta confianza
        fields_needed = []
        for f in semantic_fields:
            if f in regex_results and regex_results[f].confidence >= 80:
                continue  # Regex ya lo tiene con confianza alta
            attr = Case.CSV_FIELD_MAP.get(f)
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

            # Llamar a IA
            ai_result = extract_with_ai(
                ia_doc_texts,
                case.folder_name or "",
                pdf_file_paths=pdf_file_paths[:4] if pdf_file_paths else None,
            )

            # Registrar tokens
            model_info = {}
            try:
                from backend.extraction.ai_extractor import PROVIDERS, get_active_provider
                prov, mod = get_active_provider()
                model_info = PROVIDERS.get(prov, {}).get("models", {}).get(mod, {})
            except Exception:
                pass

            inp_price = model_info.get("input_price", 0)
            out_price = model_info.get("output_price", 0)
            cost_in = ai_result.tokens_input * inp_price / 1_000_000
            cost_out = ai_result.tokens_output * out_price / 1_000_000

            db.add(TokenUsage(
                provider=ai_result.provider or "unknown",
                model=ai_result.model or "unknown",
                tokens_input=ai_result.tokens_input,
                tokens_output=ai_result.tokens_output,
                cost_input=f"{cost_in:.6f}",
                cost_output=f"{cost_out:.6f}",
                cost_total=f"{cost_in + cost_out:.6f}",
                case_id=case.id,
                fields_extracted=len(ai_result.fields),
                duration_ms=ai_result.duration_ms,
                error=ai_result.error,
                chunk_index=ai_result.chunks_used,
            ))

            if ai_result.error:
                logger.warning("IA fallo: %s (pero %d campos regex ya guardados)", ai_result.error, saved_regex)
                stats["ai_error"] = ai_result.error
            else:
                # Convertir AI fields a ExtractionResult para merge
                for fname, fresult in ai_result.fields.items():
                    ia_results[fname] = ExtractionResult(
                        value=fresult.value,
                        confidence=90 if fresult.confidence == "ALTA" else 70 if fresult.confidence == "MEDIA" else 50,
                        source=fresult.source, method="ia",
                        reasoning=f"IA ({ai_result.provider}/{ai_result.model})",
                    )

            stats["tokens_input"] = ai_result.tokens_input
            stats["tokens_output"] = ai_result.tokens_output
            stats["provider"] = ai_result.provider
            stats["model"] = ai_result.model
        else:
            logger.info("Fase 4: Todos los campos ya cubiertos por regex, IA no necesaria")

        # =================================================================
        # FASE 5: MERGE — resolver regex vs IA por campo
        # =================================================================
        logger.info("Fase 5: Merge %d regex + %d IA", len(regex_results), len(ia_results))

        all_fields = set(list(regex_results.keys()) + list(ia_results.keys()))
        final_fields = {}

        for fname in all_fields:
            regex_r = regex_results.get(fname)
            ai_r = ia_results.get(fname)
            resolved = resolve_field(fname, regex_r, ai_r)
            if resolved and resolved.value:
                final_fields[fname] = resolved.value

        # Guardar campos resueltos en Case
        ia_saved = 0
        for fname, value in final_fields.items():
            attr = Case.CSV_FIELD_MAP.get(fname)
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

        # Estado final
        if stats.get("ai_error") and saved_regex < 5:
            case.processing_status = "REVISION"
        else:
            case.processing_status = "COMPLETO"
            case.updated_at = datetime.utcnow()

        # Renombrar carpeta si aplica
        try:
            _rename_folder_if_needed(db, case, stats)
        except Exception:
            pass

        # Link a caso base
        try:
            _check_and_link_to_base_case(db, case, stats)
        except Exception:
            pass

        # Knowledge Base
        try:
            from backend.knowledge.indexer import index_case_fields
            index_case_fields(db, case.id, final_fields)
        except Exception:
            pass

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
