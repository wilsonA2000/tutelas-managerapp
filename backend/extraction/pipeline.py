"""Pipeline de extraccion: carpeta → texto → IA → DB."""

import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("tutelas.pipeline")

from sqlalchemy.orm import Session

from backend.database.models import Case, Document, Email, Extraction, AuditLog, TokenUsage
from backend.extraction.pdf_extractor import extract_pdf
from backend.extraction.docx_extractor import extract_docx
from backend.extraction.doc_extractor import extract_doc
from backend.extraction.ocr_extractor import extract_pdf_ocr, extract_image_ocr, is_tesseract_available
from backend.extraction.ai_extractor import extract_with_ai


def extract_document_text(doc: Document) -> tuple[str, str]:
    """Extraer texto de un documento segun su tipo de archivo. Retorna (texto, metodo)."""
    path = Path(doc.file_path)
    ext = path.suffix.lower()

    # Normalizer mejorado para PDFs e imagenes (DOCX excluido — preserva footer regex)
    try:
        from backend.core.settings import settings
        if settings.NORMALIZER_ENABLED and ext not in (".docx", ".doc"):
            from backend.extraction.document_normalizer import normalize_document
            result = normalize_document(doc.file_path)
            if result.text.strip():
                return result.text, result.method
    except Exception:
        pass  # Fallback silencioso a extractores legacy

    if ext == ".pdf":
        result = extract_pdf(doc.file_path)
        text = result.text
        method = result.method

        # Si tiene paginas escaneadas y tesseract esta disponible, intentar OCR
        if result.has_scanned_pages and is_tesseract_available():
            ocr_result = extract_pdf_ocr(doc.file_path)
            if ocr_result.text.strip():
                # Combinar texto normal con OCR de paginas escaneadas
                text += "\n\n[OCR COMPLEMENTARIO]\n" + ocr_result.text
                method = "pdfplumber+ocr"

        return text, method

    elif ext == ".docx":
        result = extract_docx(doc.file_path)
        return result.text, result.method

    elif ext == ".doc":
        result = extract_doc(doc.file_path)
        return result.text, result.method

    elif ext == ".md":
        try:
            text = Path(doc.file_path).read_text(encoding="utf-8", errors="replace")
            return text, "markdown"
        except Exception:
            return "", "md_error"

    elif ext in (".png", ".jpg", ".jpeg"):
        if is_tesseract_available():
            result = extract_image_ocr(doc.file_path)
            return result.text, "ocr"
        return "", "no_ocr"

    return "", "unsupported"


def classify_doc_type(filename: str) -> str:
    """Clasificar tipo de documento por nombre de archivo.
    Fuente unica de verdad para clasificacion de documentos."""
    fn = filename.lower()
    # DOCX clasificación detallada
    if fn.endswith(".docx") or (fn.endswith(".doc") and ".doc " not in fn):
        if any(k in fn for k in ("respuesta", "contestacion", "contestación")):
            if any(k in fn for k in ("incidente", "desacato")):
                return "DOCX_DESACATO"
            if "impugnacion" in fn or "impugnación" in fn:
                return "DOCX_IMPUGNACION"
            return "DOCX_RESPUESTA"
        if "cumplimiento" in fn:
            return "DOCX_CUMPLIMIENTO"
        if any(k in fn for k in ("forest", "con forest", "con  forest")):
            return "DOCX_RESPUESTA"  # "CON FOREST" = respuesta radicada
        if any(k in fn for k in ("solicitu", "insumo")):
            return "DOCX_SOLICITUD"
        if any(k in fn for k in ("memorial", "aclaratori")):
            return "DOCX_MEMORIAL"
        if any(k in fn for k in ("carta", "oficio")):
            return "DOCX_CARTA"
        return "DOCX_OTRO"
    # PDFs y otros
    if fn.startswith("email_") and fn.endswith(".md"):
        return "EMAIL_MD"
    if fn.startswith("gmail") or fn.startswith("rv_"):
        return "PDF_GMAIL"
    if any(k in fn for k in ("auto", "admite", "avoca", "admisorio")):
        return "PDF_AUTO_ADMISORIO"
    if any(k in fn for k in ("sentencia", "fallo")):
        return "PDF_SENTENCIA"
    if any(k in fn for k in ("impugn",)):
        return "PDF_IMPUGNACION"
    if any(k in fn for k in ("incidente", "desacato")):
        return "PDF_INCIDENTE"
    if fn.startswith("email"):
        return "EMAIL_DB"
    # Screenshots
    if fn.endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif")):
        return "SCREENSHOT"
    return "PDF_OTRO"


def process_folder(db: Session, case: Case) -> dict:
    """
    Procesar una carpeta completa: extraer texto de todos los docs y luego IA.

    Returns: dict con estadisticas del procesamiento.
    """
    stats = {
        "documents_extracted": 0,
        "documents_failed": 0,
        "ai_fields_extracted": 0,
        "ai_error": None,
    }

    # Limpiar alertas previas de documentos no correspondientes (se re-evalúan)
    db.query(AuditLog).filter(
        AuditLog.case_id == case.id,
        AuditLog.action == "DOC_NO_CORRESPONDE",
    ).update({"action": "DOC_NO_CORRESPONDE_RESUELTO"})

    # Actualizar estado
    case.processing_status = "EXTRAYENDO"
    db.commit()

    # Paso 1: Extraer texto de cada documento
    doc_texts = []
    lawyer_from_docx = ""

    # DOCX types que contienen abogado responsable (Proyectó/Elaboró)
    DOCX_WITH_LAWYER = {"DOCX_RESPUESTA", "DOCX_CONTESTACION", "DOCX_DESACATO",
                         "DOCX_IMPUGNACION", "DOCX_CUMPLIMIENTO"}
    DOCX_LAWYER_PRIORITY = {"DOCX_RESPUESTA": 1, "DOCX_CONTESTACION": 2,
                             "DOCX_CUMPLIMIENTO": 3, "DOCX_IMPUGNACION": 4, "DOCX_DESACATO": 5}

    # Paso 0.5: Extraer lawyer de TODOS los DOCX relevantes (priorizado por tipo)
    lawyer_candidates = []
    for doc in case.documents:
        ext = Path(doc.file_path).suffix.lower() if doc.file_path else ""
        if ext in (".docx", ".doc") and doc.file_path:
            doc_type = classify_doc_type(doc.filename)
            if doc_type in DOCX_WITH_LAWYER:
                from backend.extraction.docx_extractor import extract_docx
                try:
                    docx_result = extract_docx(doc.file_path)
                    if docx_result.lawyer_name:
                        lawyer_candidates.append({
                            "name": docx_result.lawyer_name,
                            "filename": doc.filename,
                            "type": doc_type,
                            "priority": DOCX_LAWYER_PRIORITY.get(doc_type, 9),
                        })
                except Exception:
                    pass

    # Elegir lawyer: priorizar por tipo, luego por accionante en filename
    if lawyer_candidates:
        import unicodedata
        def _n(s):
            return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn').upper()
        acc_norm = _n(case.accionante or "")
        acc_words = [w for w in acc_norm.split() if len(w) >= 4]

        # Primero los que mencionan al accionante en el filename
        for lc in sorted(lawyer_candidates, key=lambda x: x["priority"]):
            fn_norm = _n(lc["filename"])
            if any(w in fn_norm for w in acc_words[:3]):
                lawyer_from_docx = lc["name"]
                break
        # Si ninguno menciona al accionante, tomar el de mayor prioridad
        if not lawyer_from_docx:
            lawyer_from_docx = sorted(lawyer_candidates, key=lambda x: x["priority"])[0]["name"]

        if len(lawyer_candidates) > 1:
            db.add(AuditLog(
                case_id=case.id, field_name="MULTIPLE_LAWYERS",
                old_value="", action="INFO",
                new_value=f"{len(lawyer_candidates)} abogados detectados: " + ", ".join(f"{c['name']} ({c['filename'][:30]})" for c in lawyer_candidates),
                source="docx_multi_lawyer",
            ))

    # Paso 1: Procesar documentos (extraer texto, verificar pertenencia, clasificar)
    for doc in case.documents:
        if doc.extracted_text:
            # Ya tiene texto — verificar pertenencia antes de incluir
            v_status, v_detalle = verify_document_belongs(case, doc)
            doc.verificacion = v_status
            doc.verificacion_detalle = v_detalle
            if v_status in ("NO_PERTENECE", "SOSPECHOSO"):
                # Intentar reasignar automáticamente a la carpeta correcta
                moved = _auto_reassign_document(db, case, doc, v_detalle, stats)
                if moved:
                    stats["documents_failed"] += 1
                    continue  # Fue movido, no incluir en esta extracción
                # Si no se pudo mover, incluirlo pero con advertencia
                stats.setdefault("suspicious_docs", []).append(
                    {"filename": doc.filename, "status": v_status, "detail": v_detalle}
                )

            doc_type = classify_doc_type(doc.filename)
            doc_texts.append({"filename": doc.filename, "text": doc.extracted_text, "doc_type": doc_type})
            stats["documents_extracted"] += 1
            continue

        text, method = extract_document_text(doc)

        # Si es DOCX, extraer nombre del abogado del footer (fallback)
        if ext == ".docx" and not lawyer_from_docx:
            from backend.extraction.docx_extractor import extract_docx
            docx_result = extract_docx(doc.file_path)
            if docx_result.lawyer_name:
                lawyer_from_docx = docx_result.lawyer_name

        if text.strip():
            doc.extracted_text = text
            doc.extraction_method = method
            doc.extraction_date = datetime.utcnow()

            # Verificar pertenencia ANTES de incluir en extracción
            v_status, v_detalle = verify_document_belongs(case, doc)
            doc.verificacion = v_status
            doc.verificacion_detalle = v_detalle

            if v_status in ("NO_PERTENECE", "SOSPECHOSO"):
                moved = _auto_reassign_document(db, case, doc, v_detalle, stats)
                if moved:
                    stats["documents_failed"] += 1
                    continue
                stats.setdefault("suspicious_docs", []).append(
                    {"filename": doc.filename, "status": v_status, "detail": v_detalle}
                )

            doc_type = classify_doc_type(doc.filename)
            doc_texts.append({"filename": doc.filename, "text": text, "doc_type": doc_type})
            stats["documents_extracted"] += 1
        else:
            stats["documents_failed"] += 1

    db.commit()

    # Paso 1.5: Incluir emails del caso como fuente de datos
    # El subject y body de los emails contienen info valiosa: RADICADO_FOREST, juzgado, etc.
    case_emails = db.query(Email).filter(Email.case_id == case.id).all()
    for em in case_emails:
        email_text = ""
        if em.subject:
            email_text += f"ASUNTO: {em.subject}\n"
        if em.sender:
            email_text += f"DE: {em.sender}\n"
        if em.date_received:
            email_text += f"FECHA: {em.date_received.strftime('%d/%m/%Y %H:%M')}\n"
        if em.body_preview:
            email_text += f"\n{em.body_preview}"

        if email_text.strip():
            doc_texts.append({
                "filename": f"EMAIL: {(em.subject or 'sin asunto')[:60]}",
                "text": email_text,
                "doc_type": "EMAIL_DB",
            })

    # Paso 1.6: Verificacion de dos pasos — validar que los documentos correspondan al caso
    # NOTA: Solo informativo. Los documentos NO se excluyen de la extraccion porque
    # pueden ser anexos, documentos de 2da instancia, o resoluciones generales
    # que sí pertenecen al caso aunque no mencionen el radicado explícitamente.
    mismatched = _verify_documents_belong_to_case(case, doc_texts)
    if mismatched:
        stats["mismatched_docs"] = mismatched
        for mismatch in mismatched:
            db.add(AuditLog(
                case_id=case.id,
                field_name="VERIFICACION_DOCS",
                old_value=mismatch["filename"],
                new_value=mismatch["radicado_encontrado"],
                action="DOC_NO_CORRESPONDE",
                source=f"verificacion_2_pasos",
            ))

    # Paso 1.7: Recolectar paths de PDFs (se pasan al prompt texto para verify)
    pdf_file_paths = []
    for doc in case.documents:
        if doc.file_path and Path(doc.file_path).suffix.lower() == ".pdf" and Path(doc.file_path).exists():
            pdf_file_paths.append({
                "filename": doc.filename,
                "file_path": doc.file_path,
            })

    # Paso 1.8: Pre-extraer FOREST con regex desde múltiples fuentes
    from backend.agent.forest_extractor import extract_forest_from_sources
    forest_result = extract_forest_from_sources(doc_texts, case_emails)
    if forest_result:
        doc_texts.insert(0, {
            "filename": "DATO_CONOCIDO",
            "text": f"RADICADO_FOREST IDENTIFICADO: {forest_result.value} (fuente: {forest_result.source}). Usa este numero como RADICADO_FOREST.",
        })

    # Paso 1.9: Inyectar correcciones históricas como few-shot learning
    try:
        from backend.agent.memory import get_recent_corrections
        corrections = get_recent_corrections(db, case_id=case.id, limit=10)
        if corrections:
            correction_lines = ["CORRECCIONES HISTÓRICAS (aprende de estos errores anteriores, NO los repitas):"]
            for c in corrections:
                correction_lines.append(f"  Campo {c.field_name}: IA dijo '{c.ai_value}' → correcto es '{c.corrected_value}' (caso: {c.case_folder})")
            doc_texts.insert(0, {
                "filename": "CORRECCIONES_APRENDIDAS",
                "text": "\n".join(correction_lines),
                "doc_type": "SISTEMA",
            })
            stats["corrections_injected"] = len(corrections)
    except Exception:
        pass

    # Paso 1.95: Pre-extraccion regex (como el Agent) para inyectar datos de alta confianza
    try:
        from backend.agent.extractors.registry import pre_extract_all
        regex_results = pre_extract_all(doc_texts, case_emails)
        if regex_results:
            known_parts = ["DATOS PRE-EXTRAIDOS POR REGEX (alta confianza, usar como referencia):"]
            for field, result in regex_results.items():
                known_parts.append(f"  {field}: {result.value} (fuente: {result.source})")
            doc_texts.insert(0, {"filename": "DATOS_CONOCIDOS_REGEX", "text": "\n".join(known_parts)})
            stats["regex_pre_extracted"] = len(regex_results)
    except Exception:
        pass

    # Paso 2: Enviar a IA para extraccion de campos
    if doc_texts:
        ai_result = extract_with_ai(
            doc_texts,
            case.folder_name or "",
            pdf_file_paths=pdf_file_paths if pdf_file_paths else None,
        )

        # Paso 2.5: Validar campos extraidos (evitar alucinaciones)
        if ai_result.fields:
            _validate_extracted_fields(ai_result.fields, forest_result.value if forest_result else None)

        # Paso 2.6: Validación cruzada — radicado extraído vs carpeta
        if ai_result.fields:
            _cross_validate_radicado(case, ai_result.fields, db, stats)

        # Registrar uso de tokens (siempre, incluso si hay error)
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

        token_record = TokenUsage(
            provider=ai_result.provider or "deepseek",
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
        )
        db.add(token_record)

        if ai_result.error:
            stats["ai_error"] = ai_result.error
            case.processing_status = "REVISION"
        else:
            provider_label = f"{ai_result.provider}/{ai_result.model}"

            # Guardar cada campo extraido
            for field_name, field_result in ai_result.fields.items():
                if not field_result.value:
                    continue

                extraction = Extraction(
                    case_id=case.id,
                    field_name=field_name,
                    extracted_value=field_result.value,
                    confidence=field_result.confidence,
                    extraction_method=f"ai_{ai_result.provider}",
                    raw_context=field_result.source,
                    created_at=datetime.utcnow(),
                )
                db.add(extraction)

                attr = Case.CSV_FIELD_MAP.get(field_name)
                if attr:
                    old_value = getattr(case, attr) or ""
                    new_value = field_result.value

                    # Solo actualizar si:
                    # 1. Campo vacío → siempre llenar
                    # 2. Campo tiene valor pero nueva confianza ALTA y valor es diferente y más largo
                    #    (evita sobreescribir FOREST real con radicado corto)
                    should_update = False
                    if not old_value.strip():
                        should_update = True
                    elif field_result.confidence == "ALTA" and old_value.strip() != new_value.strip():
                        # No sobreescribir si el valor viejo parece más específico
                        # (ej: FOREST 20260054965 no debe ser reemplazado por 2026-00070)
                        if len(new_value) >= len(old_value):
                            should_update = True

                    if should_update:
                        setattr(case, attr, new_value)

                        if old_value != new_value:
                            db.add(AuditLog(
                                case_id=case.id,
                                field_name=field_name,
                                old_value=old_value,
                                new_value=new_value,
                                action="AI_EXTRAER",
                                source=f"{provider_label}/{field_result.confidence}",
                            ))

                        stats["ai_fields_extracted"] += 1

        stats["tokens_input"] = ai_result.tokens_input
        stats["tokens_output"] = ai_result.tokens_output
        stats["cost_usd"] = round(cost_in + cost_out, 6)
        stats["provider"] = ai_result.provider
        stats["model"] = ai_result.model

        if not ai_result.error:
            # Paso 3: Completar campos que la IA no lleno pero tenemos de otras fuentes
            # Abogado del footer del DOCX
            if lawyer_from_docx:  # Regex DOCX SIEMPRE gana para ABOGADO
                case.abogado_responsable = lawyer_from_docx
                db.add(AuditLog(
                    case_id=case.id,
                    field_name="ABOGADO_RESPONSABLE",
                    old_value="",
                    new_value=lawyer_from_docx,
                    action="AI_EXTRAER",
                    source="docx_footer",
                ))
                stats["ai_fields_extracted"] += 1

            # Si no tiene INCIDENTE, poner NO por defecto
            if not case.incidente:
                case.incidente = "NO"
            # Si tiene fallo pero no IMPUGNACION, poner NO
            if case.sentido_fallo_1st and not case.impugnacion:
                case.impugnacion = "NO"

            case.processing_status = "COMPLETO"
            case.updated_at = datetime.utcnow()

            # Paso 4: Renombrar carpeta si tiene accionante nuevo y la carpeta no lo tiene
            _rename_folder_if_needed(db, case, stats)

            # Paso 4.5: Post-IA — verificar si el radicado extraído pertenece a otro caso
            # (detecta incidentes de desacato que se crearon como caso nuevo)
            _check_and_link_to_base_case(db, case, stats)

    else:
        case.processing_status = "REVISION"
        stats["ai_error"] = "No se pudo extraer texto de ningun documento"

    # Paso 3.5: Validacion post-extraccion unificada
    try:
        from backend.extraction.post_validator import validate_extraction
        current_fields = {}
        for csv_col, attr in Case.CSV_FIELD_MAP.items():
            val = getattr(case, attr, None)
            if val:
                current_fields[attr] = str(val)
        validated, val_warnings = validate_extraction(case, current_fields)
        for field, value in validated.items():
            if hasattr(case, field):
                setattr(case, field, value if value else None)
        if val_warnings:
            stats["validation_warnings"] = val_warnings
    except Exception:
        pass

    # OBSERVACIONES fallback: si la IA no genero observaciones, crear uno basico
    if not case.observaciones and case.accionante:
        obs_parts = []
        if case.asunto:
            obs_parts.append(case.asunto)
        if case.sentido_fallo_1st:
            obs_parts.append(f"Fallo 1ra instancia: {case.sentido_fallo_1st}")
        if case.impugnacion == "SI":
            obs_parts.append("Fue impugnado")
        if case.incidente == "SI":
            obs_parts.append("Tiene incidente de desacato")
        if case.estado:
            obs_parts.append(f"Estado: {case.estado}")
        if obs_parts:
            case.observaciones = ". ".join(obs_parts) + "."

    # OVERRIDE FINAL: lawyer_from_docx SIEMPRE gana (regex es más confiable que IA para ABOGADO)
    if lawyer_from_docx:
        old_abogado = case.abogado_responsable or ""
        if old_abogado != lawyer_from_docx:
            case.abogado_responsable = lawyer_from_docx
            db.add(AuditLog(
                case_id=case.id, field_name="ABOGADO_RESPONSABLE",
                old_value=old_abogado, new_value=lawyer_from_docx,
                action="DOCX_OVERRIDE", source="docx_footer_final",
            ))

    db.commit()
    return stats


def _sanitize_folder_name(name: str) -> str:
    """Sanitizar nombre de carpeta para Windows/Linux."""
    import re
    # Quitar caracteres invalidos en Windows
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    # Normalizar espacios
    name = re.sub(r'\s+', ' ', name).strip()
    # Quitar puntos/espacios al final (Windows los rechaza)
    name = name.rstrip('. ')
    # Limitar longitud a 200 chars
    if len(name) > 200:
        name = name[:200].rstrip('. ')
    return name


def _rename_folder_if_needed(db, case: Case, stats: dict):
    """Renombrar carpeta física si la IA encontró accionante y la carpeta no lo tiene.
    F5 (v5.0): si rad23 del caso difiere del rad corto del folder, renombrar usando
    rad23 como fuente de verdad (corrige folders formados con FOREST por bug B1).
    """
    import re

    if not case.folder_path or not case.folder_name:
        return

    # Verificar si el folder_name actual ya tiene el accionante
    current_name = case.folder_name
    m = re.match(r"(20\d{2}[-\s]?\d+(?:[-\s]\d+)?)\s*(.*)", current_name)
    if not m:
        return

    rad_part = m.group(1).strip()
    name_part = m.group(2).strip()

    # F5: derivar rad_corto REAL desde radicado_23_digitos (fuente de verdad).
    rad_from_23 = ""
    if case.radicado_23_digitos:
        digits = re.sub(r"\D", "", case.radicado_23_digitos)
        rm23 = re.search(r"(20\d{2})(\d{5})\d{2}$", digits)
        if rm23:
            rad_from_23 = f"{rm23.group(1)}-{rm23.group(2)}"

    # Rad corto extraido del folder actual (para detectar disonancia con rad23)
    rm_folder = re.match(r"(20\d{2})[-\s]?0*(\d+)", rad_part)
    rad_from_folder = ""
    if rm_folder:
        rad_from_folder = f"{rm_folder.group(1)}-{rm_folder.group(2).zfill(5)}"

    # F5: disonancia rad23 vs folder → forzar rename aunque name_part parezca "real"
    force_rename = bool(rad_from_23 and rad_from_folder and rad_from_23 != rad_from_folder)

    # Si ya tiene nombre real Y no hay disonancia rad23/folder, respetar (no renombrar)
    if not force_rename and name_part and len(name_part) > 3 and "[PENDIENTE" not in name_part:
        JURIDICAL = {"remito", "oficio", "respuesta", "acción", "accion", "traslado",
                     "contestación", "notificación", "auto", "sentencia", "segunda",
                     "instancia", "adelantar", "control", "acciones", "evidenciar",
                     "afectada", "afectado", "solicita", "ordena", "cumplir"}
        words = set(re.findall(r"[a-záéíóúñ]+", name_part.lower()))
        non_jur = [w for w in words if w not in JURIDICAL and len(w) > 2]
        if len(non_jur) >= 2:
            return  # Ya tiene nombre real y rad coincide con rad23

    # Si no hay accionante, no podemos construir nombre nuevo (salvo que force_rename
    # tenga un rad23 correcto y name_part sirva). Si no hay accionante y tampoco
    # rad23, abortar.
    if not case.accionante and not force_rename:
        return

    # F5: usar rad23 como fuente preferida; fallback a rad_folder
    if rad_from_23:
        rad_part = rad_from_23
    elif rad_from_folder:
        rad_part = rad_from_folder

    # Limpiar accionante (si existe); si no, preservar name_part salvo que sea PENDIENTE
    if case.accionante:
        accionante = case.accionante.strip()
        accionante = re.sub(r'[\n\r]', ' ', accionante)
        accionante = re.sub(r'\s+', ' ', accionante)
    elif name_part and "[PENDIENTE" not in name_part:
        accionante = name_part
    else:
        accionante = "[PENDIENTE ACCIONANTE]"

    new_name = _sanitize_folder_name(f"{rad_part} {accionante}")

    if new_name == current_name:
        return

    old_path = Path(case.folder_path)
    from backend.config import BASE_DIR
    new_path = BASE_DIR / new_name

    if not old_path.exists():
        return

    try:
        old_path.rename(new_path)
        case.folder_name = new_name
        case.folder_path = str(new_path)

        # Actualizar paths de documentos
        for doc in case.documents:
            if doc.file_path and str(old_path) in doc.file_path:
                doc.file_path = doc.file_path.replace(str(old_path), str(new_path))

        stats["folder_renamed"] = new_name
    except FileExistsError:
        logger.warning("Rename abortado: ya existe '%s'", new_name)
    except Exception as e:
        logger.warning("Rename fallo: %s", str(e)[:80])


def reextract_document(db: Session, doc: Document) -> tuple[str, str]:
    """Re-extraer texto de un documento especifico."""
    text, method = extract_document_text(doc)
    doc.extracted_text = text
    doc.extraction_method = method
    doc.extraction_date = datetime.utcnow()
    db.commit()
    return text, method


def process_new_document(db: Session, case: Case, doc: Document) -> dict:
    """Procesar UN SOLO documento nuevo: extraer texto + enviar a IA + actualizar campos.

    Esta es la extracción INCREMENTAL: cuando llega un email con adjuntos,
    se procesa solo el documento nuevo y se actualizan los campos que aporta.
    Los campos existentes NO se sobreescriben a menos que la IA tenga mayor confianza.

    Returns: dict con estadísticas del procesamiento.
    """
    from backend.extraction.ai_extractor import extract_single_document

    stats = {
        "document": doc.filename,
        "text_extracted": False,
        "ai_fields_extracted": 0,
        "ai_error": None,
    }

    # Paso 1: Extraer texto del documento
    if not doc.extracted_text:
        text, method = extract_document_text(doc)
        if text.strip():
            doc.extracted_text = text
            doc.extraction_method = method
            doc.extraction_date = datetime.utcnow()
            stats["text_extracted"] = True
        else:
            stats["ai_error"] = "No se pudo extraer texto del documento"
            db.commit()
            return stats

    # Si es DOCX, extraer abogado del footer
    ext = Path(doc.file_path).suffix.lower()
    lawyer_from_docx = ""
    if ext == ".docx":
        from backend.extraction.docx_extractor import extract_docx
        docx_result = extract_docx(doc.file_path)
        if docx_result.lawyer_name:
            lawyer_from_docx = docx_result.lawyer_name

    db.commit()

    # Paso 2: Enviar a IA para extracción incremental
    ai_result = extract_single_document(
        filename=doc.filename,
        text=doc.extracted_text,
        folder_name=case.folder_name or "",
    )

    if ai_result.error:
        stats["ai_error"] = ai_result.error
        return stats

    # Paso 3: Actualizar campos del caso (solo si vacíos o IA tiene mayor confianza)
    for field_name, field_result in ai_result.fields.items():
        if not field_result.value:
            continue

        # Guardar en tabla extractions
        extraction = Extraction(
            case_id=case.id,
            document_id=doc.id,
            field_name=field_name,
            extracted_value=field_result.value,
            confidence=field_result.confidence,
            extraction_method="ai_incremental",
            raw_context=field_result.source,
            created_at=datetime.utcnow(),
        )
        db.add(extraction)

        # Actualizar campo en el caso
        attr = Case.CSV_FIELD_MAP.get(field_name)
        if attr:
            old_value = getattr(case, attr) or ""
            new_value = field_result.value

            # Solo actualizar si vacío O la nueva extracción tiene ALTA confianza
            if not old_value.strip() or field_result.confidence == "ALTA":
                setattr(case, attr, new_value)

                if old_value != new_value:
                    db.add(AuditLog(
                        case_id=case.id,
                        field_name=field_name,
                        old_value=old_value,
                        new_value=new_value,
                        action="AI_EXTRAER",
                        source=f"incremental/{doc.filename}/{field_result.confidence}",
                    ))
                    stats["ai_fields_extracted"] += 1

    # Paso 4: Abogado del footer DOCX (si la IA no lo capturó)
    if lawyer_from_docx:  # Regex DOCX SIEMPRE gana para ABOGADO
        case.abogado_responsable = lawyer_from_docx
        db.add(AuditLog(
            case_id=case.id,
            field_name="ABOGADO_RESPONSABLE",
            old_value="",
            new_value=lawyer_from_docx,
            action="AI_EXTRAER",
            source=f"docx_footer/{doc.filename}",
        ))
        stats["ai_fields_extracted"] += 1

    case.updated_at = datetime.utcnow()
    db.commit()

    return stats


def compute_file_hash(file_path: str) -> str:
    """Calcular hash MD5 de un archivo."""
    import hashlib
    try:
        h = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def detect_duplicate_documents(db) -> list[dict]:
    """Detectar documentos duplicados entre carpetas diferentes (mismo hash MD5)."""
    from collections import defaultdict

    # Calcular hashes faltantes
    docs_no_hash = db.query(Document).filter(
        Document.file_hash == "", Document.file_path.isnot(None),
    ).all()
    for doc in docs_no_hash:
        if doc.file_path and Path(doc.file_path).exists():
            doc.file_hash = compute_file_hash(doc.file_path)
    db.commit()

    # Agrupar por hash
    all_docs = db.query(Document).filter(Document.file_hash != "").all()
    hash_groups = defaultdict(list)
    for doc in all_docs:
        hash_groups[doc.file_hash].append(doc)

    # Encontrar duplicados (mismo hash en diferentes casos)
    duplicates = []
    for h, docs in hash_groups.items():
        case_ids = {d.case_id for d in docs}
        if len(case_ids) > 1:
            cases = {d.case_id: db.query(Case).filter(Case.id == d.case_id).first() for d in docs}
            duplicates.append({
                "hash": h,
                "files": [
                    {"doc_id": d.id, "filename": d.filename, "case_id": d.case_id,
                     "case_name": cases[d.case_id].folder_name if cases[d.case_id] else ""}
                    for d in docs
                ],
            })

    # Segundo paso: duplicados por contenido (texto similar, hash diferente)
    docs_with_text = db.query(Document).filter(
        Document.extracted_text.isnot(None),
        Document.extracted_text != "",
        Document.file_hash != "",
    ).all()

    # Agrupar por caso para comparar entre casos
    from itertools import combinations
    case_docs = defaultdict(list)
    for doc in docs_with_text:
        if doc.extracted_text and len(doc.extracted_text) > 200:
            case_docs[doc.case_id].append(doc)

    # Comparar docs entre diferentes casos usando trigram overlap
    seen_pairs = set()
    for (cid1, docs1), (cid2, docs2) in combinations(case_docs.items(), 2):
        if cid1 == cid2:
            continue
        for d1 in docs1[:10]:  # Limitar a 10 docs por caso
            t1 = (d1.extracted_text or "")[:5000].lower()
            if len(t1) < 200:
                continue
            trigrams1 = {t1[i:i+3] for i in range(len(t1) - 2)}
            for d2 in docs2[:10]:
                pair_key = tuple(sorted([d1.id, d2.id]))
                if pair_key in seen_pairs or d1.file_hash == d2.file_hash:
                    continue
                seen_pairs.add(pair_key)
                t2 = (d2.extracted_text or "")[:5000].lower()
                if len(t2) < 200:
                    continue
                trigrams2 = {t2[i:i+3] for i in range(len(t2) - 2)}
                overlap = len(trigrams1 & trigrams2) / max(len(trigrams1), len(trigrams2), 1)
                if overlap > 0.90:
                    c1 = db.query(Case).filter(Case.id == cid1).first()
                    c2 = db.query(Case).filter(Case.id == cid2).first()
                    duplicates.append({
                        "hash": f"content_sim_{overlap:.0%}",
                        "type": "content_similarity",
                        "files": [
                            {"doc_id": d1.id, "filename": d1.filename, "case_id": cid1,
                             "case_name": c1.folder_name if c1 else ""},
                            {"doc_id": d2.id, "filename": d2.filename, "case_id": cid2,
                             "case_name": c2.folder_name if c2 else ""},
                        ],
                    })

    return duplicates


def _create_case_for_orphan_doc(db, doc: Document, detalle: str, stats: dict):
    """Crear caso nuevo para documento huérfano que tiene radicado de caso inexistente.

    Returns: (folder_name, Case) o (None, None) si no se pudo crear.
    """
    import re
    from backend.config import BASE_DIR

    text = (doc.extracted_text or "")[:10000]

    # 1. Extraer radicado corto del detalle o del texto
    rad_match = re.search(r'(20\d{2})[-\s]?0*(\d{2,5})', detalle)
    if not rad_match:
        rad_match = re.search(r'(?:RAD|Rad|RADICADO)\.?\s*:?\s*#?\s*(?:No\.?\s*)?(20\d{2})[-\s]?0*(\d{2,5})', text)
    if not rad_match:
        return None, None

    year = rad_match.group(1)
    seq = rad_match.group(2).zfill(5)

    # 2. Extraer accionante del texto
    accionante = ""
    acc_match = re.search(r'(?i)accionante[:\s]+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{5,50})', text)
    if acc_match:
        accionante = acc_match.group(1).strip().upper()[:60]

    # Si no hay accionante en texto, intentar desde el filename
    if not accionante:
        fn_parts = re.findall(r'[A-ZÁÉÍÓÚÑ]{4,}', doc.filename.upper())
        skip = {"RESPUESTA", "FOREST", "TUTELA", "FALLO", "AUTO", "SENTENCIA", "GMAIL",
                "EMAIL", "OFICIO", "URGENTE", "ADMISORIO", "CONTESTACION", "MERGED",
                "ILOVEPDF", "COMPRESSED", "ANEXOS", "ESCRITO", "PRUEBA", "RADICADO"}
        name_parts = [w for w in fn_parts if w not in skip]
        if len(name_parts) >= 2:
            accionante = " ".join(name_parts[:4])

    if not accionante:
        accionante = "[PENDIENTE IDENTIFICACION]"

    # 3. Construir folder_name
    folder_name = f"{year}-{seq} {accionante}"

    # Verificar que no exista ya
    existing = db.query(Case).filter(Case.folder_name == folder_name).first()
    if existing:
        return folder_name, existing

    # 4. Crear carpeta en disco
    folder_path = BASE_DIR / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)

    # 5. Crear caso en DB
    new_case = Case(
        folder_name=folder_name,
        folder_path=str(folder_path),
        accionante=accionante if accionante != "[PENDIENTE IDENTIFICACION]" else None,
        estado="ACTIVO",
        processing_status="PENDIENTE",
    )
    db.add(new_case)
    db.commit()
    db.refresh(new_case)

    # Audit log
    db.add(AuditLog(
        case_id=new_case.id,
        field_name="CASO_CREADO_AUTO",
        old_value="",
        new_value=f"Creado automáticamente desde doc '{doc.filename}' del caso {doc.case_id}",
        action="AUTO_CREATE_CASE",
        source=detalle[:200],
    ))
    db.commit()

    stats.setdefault("cases_created", []).append({
        "folder_name": folder_name,
        "case_id": new_case.id,
        "from_doc": doc.filename,
        "reason": detalle,
    })

    logger.info(f"Caso nuevo creado: {folder_name} (ID {new_case.id}) desde doc '{doc.filename}'")
    return folder_name, new_case


def _auto_reassign_document(db, source_case: Case, doc: Document, detalle: str, stats: dict) -> bool:
    """Reasignar automáticamente un documento a la carpeta correcta.

    Multi-criterio para encontrar el caso correcto:
    1. Radicado 23 dígitos completo en el texto del documento
    2. Radicado corto + accionante mencionado en el texto
    3. Radicado corto solo (si hay un único caso con ese radicado)
    4. Si no existe caso destino → CREAR caso nuevo automáticamente

    Returns: True si se movió exitosamente, False si no se pudo.
    """
    import re
    import shutil
    import unicodedata
    from backend.config import BASE_DIR

    text = (doc.extracted_text or "")[:10000].upper()
    if not text:
        return False

    def _norm(s):
        return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn').upper()

    # 1. Buscar radicado 23 dígitos en el texto del documento
    rad23_in_doc = re.findall(r'(68[\d]{17,21})', re.sub(r'[\s\-\.]', '', text))
    source_rad23 = re.sub(r'[\s\-\.]', '', source_case.radicado_23_digitos or '')

    target_case = None

    for rad23 in rad23_in_doc:
        if len(rad23) >= 20 and rad23 != source_rad23:
            # Buscar caso con este radicado 23
            all_cases = db.query(Case).filter(Case.id != source_case.id).all()
            for c in all_cases:
                c_rad = re.sub(r'[\s\-\.]', '', c.radicado_23_digitos or '')
                if c_rad and len(c_rad) >= 15 and c_rad[-12:] == rad23[-12:]:
                    target_case = c
                    break
            if target_case:
                break

    # 2. Si no encontró por rad23, buscar por radicado corto + accionante
    if not target_case:
        m = re.search(r'(?:Radicado|RAD|Rad\.?\s*(?:No\.?)?)\s*:?\s*(20\d{2})[-\s]?0*(\d{2,5})', detalle)
        if m:
            target_year = m.group(1)
            target_seq = m.group(2).lstrip('0') or '0'
            candidates = db.query(Case).filter(
                Case.folder_name.contains(f"{target_year}-{target_seq.zfill(5)}"),
                Case.id != source_case.id,
            ).all()
            if not candidates:
                candidates = db.query(Case).filter(
                    Case.folder_name.contains(f"{target_year}-{target_seq}"),
                    Case.id != source_case.id,
                ).all()

            if len(candidates) == 1:
                target_case = candidates[0]
            elif len(candidates) > 1:
                # Múltiples casos con mismo radicado corto — usar accionante para desambiguar
                text_norm = _norm(text)
                for c in candidates:
                    if not c.accionante:
                        continue
                    acc_words = [w for w in _norm(c.accionante).split() if len(w) >= 4]
                    matches = sum(1 for w in acc_words[:4] if w in text_norm)
                    # Threshold adaptivo: 1 match si nombre corto (<=2 palabras), 2 si largo
                    threshold = 1 if len(acc_words) <= 2 else 2
                    if matches >= threshold:
                        target_case = c
                        break

                # Si ningún accionante matchea, buscar en el nombre del archivo
                if not target_case:
                    fn_norm = _norm(doc.filename)
                    for c in candidates:
                        if not c.accionante:
                            continue
                        acc_words = [w for w in _norm(c.accionante).split() if len(w) >= 4]
                        if any(w in fn_norm for w in acc_words[:3]):
                            target_case = c
                            break

    if not target_case:
        # No existe caso destino en DB → crear caso nuevo automáticamente
        folder_name, new_case = _create_case_for_orphan_doc(db, doc, detalle, stats)
        if new_case:
            target_case = new_case
        else:
            return False  # No se pudo determinar radicado ni crear caso

    target_folder = BASE_DIR / target_case.folder_name

    if not target_folder.exists():
        logger.warning(f"Carpeta destino no existe: {target_folder}")
        return False

    # Mover archivo físico (con manejo de duplicados y transacción atómica)
    source_path = Path(doc.file_path) if doc.file_path else None
    if not source_path or not source_path.exists():
        return False

    # Manejar filename duplicado: agregar sufijo si ya existe
    dest_path = target_folder / doc.filename
    counter = 1
    while dest_path.exists():
        stem = Path(doc.filename).stem
        suffix = Path(doc.filename).suffix
        dest_path = target_folder / f"{stem}_{counter}{suffix}"
        counter += 1

    # Transacción atómica: mover archivo + actualizar DB
    try:
        shutil.move(str(source_path), str(dest_path))
        doc.case_id = target_case.id
        doc.file_path = str(dest_path)
        doc.verificacion = "REASIGNADO"
        doc.verificacion_detalle = f"Movido de {source_case.folder_name} a {target_case.folder_name}"
        db.commit()
    except Exception as e:
        db.rollback()
        # Revertir movimiento de archivo si falló la DB
        if dest_path.exists() and not source_path.exists():
            try:
                shutil.move(str(dest_path), str(source_path))
            except Exception:
                pass
        logger.error(f"Error moviendo {source_path} → {dest_path}: {e}")
        return False

    # Audit log
    db.add(AuditLog(
        case_id=source_case.id,
        field_name="DOCUMENTO_REASIGNADO",
        old_value=f"{source_case.folder_name}/{doc.filename}",
        new_value=f"{target_case.folder_name}/{doc.filename}",
        action="AUTO_REASSIGN",
        source=f"verify_document_belongs: {detalle}",
    ))

    db.commit()

    stats.setdefault("reassigned_docs", []).append({
        "filename": doc.filename,
        "from_case": source_case.folder_name,
        "to_case": target_case.folder_name,
        "reason": detalle,
    })

    logger.info(f"Doc reasignado: {doc.filename} → {target_case.folder_name} (razon: {detalle})")
    return True


def verify_document_belongs(case: Case, doc: Document) -> tuple[str, str]:
    """Verificar si un documento pertenece al caso.

    v6.0: delega a Bayesian assignment si `USE_COGNITIVE_PIPELINE=true`.
    Mantiene la implementación legacy (5 criterios rígidos) para compatibilidad
    cuando el feature flag está apagado.

    Returns: (status, detalle)
        status: 'OK' / 'SOSPECHOSO' / 'NO_PERTENECE' / 'REVISAR'
        detalle: explicación del resultado
    """
    # v6.0: feature flag → inferencia Bayesiana
    try:
        from backend.core.settings import settings
        if getattr(settings, "USE_COGNITIVE_PIPELINE", False):
            return _verify_bayesian(case, doc)
    except Exception:
        pass  # fallback a legacy si algo falla en el import/setting
    # Legacy (v5.5):
    return _verify_legacy(case, doc)


def _verify_bayesian(case: Case, doc: Document) -> tuple[str, str]:
    """Adapter v6.0: construye IR del doc y aplica Bayesian assignment."""
    from backend.cognition.bayesian_assignment import infer_assignment
    from backend.extraction.ir_builder import _build_pdf_ir, _build_docx_ir
    from pathlib import Path as _P
    path = _P(doc.file_path or "")
    ext = path.suffix.lower()
    # Construir IR mínimo (solo para verificar, sin reconstruir todo)
    if ext == ".pdf" and path.exists():
        ir = _build_pdf_ir(str(path), doc.doc_type or "PDF_OTRO")
    elif ext in (".docx", ".doc") and path.exists():
        ir = _build_docx_ir(str(path), doc.doc_type or "DOCX_OTRO")
    else:
        # Sin acceso a archivo: crear IR mínimo a partir de extracted_text
        from backend.extraction.ir_models import DocumentIR, DocumentZone
        txt = doc.extracted_text or ""
        ir = DocumentIR(
            filename=doc.filename, doc_type=doc.doc_type or "OTRO", priority=9,
            zones=[DocumentZone(zone_type="BODY", text=txt)] if txt else [],
            full_text=txt,
        )
    verdict = infer_assignment(case, ir, doc=doc)
    detalle_parts = []
    if verdict.reasons_for:
        detalle_parts.append("+: " + "; ".join(verdict.reasons_for[:3]))
    if verdict.reasons_against:
        detalle_parts.append("-: " + "; ".join(verdict.reasons_against[:3]))
    detalle_parts.append(f"post={verdict.posterior:.3f}")
    return verdict.verdict, " | ".join(detalle_parts)


def _verify_legacy(case: Case, doc: Document) -> tuple[str, str]:
    """Implementación v5.5: 5 criterios rígidos sobre primeros 10K chars."""
    import re
    import unicodedata

    filename = doc.filename or ""
    text = doc.extracted_text or ""

    # Emails .md siempre pertenecen (clasificados por Gmail)
    if filename.startswith("Email_") and filename.endswith(".md"):
        return "OK", "Email clasificado por Gmail"

    # Sin texto = verificar si es PDF encriptado
    if len(text) < 100:
        if doc.file_path and doc.file_path.lower().endswith(".pdf"):
            try:
                import fitz
                pdf = fitz.open(doc.file_path)
                if pdf.is_encrypted:
                    pdf.close()
                    return "REVISAR", "PDF encriptado - no se puede verificar pertenencia"
                pdf.close()
            except Exception:
                pass
        return "OK", "Documento sin texto suficiente"

    def _norm(s):
        return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn').upper()

    # Extraer datos del caso
    folder = case.folder_name or ""
    m = re.match(r'(20\d{2})[-\s]?0*(\d+)', folder)
    if not m:
        return "OK", "Carpeta sin radicado"

    case_year = m.group(1)
    case_seq = m.group(2).lstrip('0') or '0'
    case_seq_padded = case_seq.zfill(5)

    # Radicado 23 dígitos del caso (normalizado sin separadores)
    case_rad23 = re.sub(r'[\s\-\.]', '', case.radicado_23_digitos or '')

    # Apellidos del accionante
    accionante = (case.accionante or "").upper()
    skip_words = {"AGENTE", "OFICIOSO", "MENOR", "REPRESENTANTE", "LEGAL", "MUNICIPAL",
                  "PERSONERO", "PERSONERA", "PERSONERIA", "ACCION", "TUTELA", "CONTRA",
                  "HIJO", "HIJA", "SEÑOR", "SEÑORA", "COMO", "REPRESENTATE", "REPRESENTACION",
                  "NOMBRE"}
    acc_words = [w for w in re.findall(r'[A-ZÁÉÍÓÚÑ]{4,}', _norm(accionante)) if w not in skip_words]

    text_upper = _norm(text[:10000])
    text_clean = re.sub(r'[\s\-\.]', '', text[:8000])

    # === CRITERIO 1: RADICADO 23 DIGITOS (definitivo) ===
    # Buscar TODOS los radicados 23d en el texto del documento
    rads_23_in_doc = re.findall(r'(68[\d]{17,21})', text_clean)

    if case_rad23 and len(case_rad23) >= 15 and rads_23_in_doc:
        # Verificar si el radicado 23d del caso está en el documento
        case_suffix = case_rad23[-17:]  # últimos 17 dígitos (incluye municipio + año + secuencia)
        doc_has_case_rad = any(case_suffix in r for r in rads_23_in_doc)

        # Verificar si el documento tiene un radicado 23d DIFERENTE
        other_rads_23 = [r for r in rads_23_in_doc if case_suffix not in r]

        if doc_has_case_rad:
            return "OK", "Radicado 23 dígitos del caso confirmado en documento"
        elif other_rads_23:
            # Tiene radicado 23d de OTRO caso → NO PERTENECE (alta confianza)
            return "NO_PERTENECE", f"Radicado 23d {other_rads_23[0][:20]}... NO coincide con caso {case_rad23[:20]}..."

    # === CRITERIO 2: ACCIONANTE en nombre del archivo ===
    # Archivos como "RESPUESTA FOREST B.L.A.R.docx" → las iniciales del accionante
    if acc_words and len(acc_words) >= 2:
        fn_upper = _norm(filename)
        fn_matches = sum(1 for w in acc_words[:3] if w in fn_upper)
        if fn_matches >= 1:
            return "OK", f"Accionante en nombre de archivo ({fn_matches} coincidencias)"

    # === CRITERIO 3: ACCIONANTE en el texto del documento ===
    if acc_words and len(acc_words) >= 2:
        matches = sum(1 for w in acc_words[:4] if w in text_upper)
        if matches >= 2:
            return "OK", f"Accionante mencionado en texto ({matches} apellidos)"

    # === CRITERIO 4: RADICADO CORTO en nombre de archivo ===
    if case_seq in filename or case_seq_padded in filename:
        return "OK", f"Radicado {case_seq} en nombre archivo"

    # === CRITERIO 5: RADICADO CORTO en texto ===
    rad_pattern = rf'{case_year}[-\s]?0*{case_seq}(?:\D|$)'
    if re.search(rad_pattern, text[:5000]):
        if not rads_23_in_doc:
            # Radicado corto sin confirmación 23d — ambiguo
            if case_rad23:
                return "REVISAR", f"Solo radicado corto {case_year}-{case_seq} (sin confirmacion 23d)"
            return "OK", f"Radicado {case_year}-{case_seq} en texto"

    # === Si llegamos aquí, NO encontramos referencia directa al caso ===
    # Buscar si tiene radicados cortos de OTRO caso

    otros_rads = re.findall(r'(20\d{2})[-\s]?0*(\d{2,5})\b', text[:5000])
    otros_reales = []
    for yr, sq in otros_rads:
        sq_clean = sq.lstrip('0') or '0'
        if sq_clean == case_seq and yr == case_year:
            continue
        if yr == "2012" and sq in ("35", "352", "3526"):
            continue
        if len(sq_clean) <= 2:
            continue
        yr_int = int(yr)
        if yr_int < 2019 or yr_int > 2030:
            continue
        if len(sq) > 5:
            continue
        sq_int = int(sq_clean)
        if len(sq_clean) >= 3 and sq_int > 600:
            continue
        otros_reales.append(f"{yr}-{sq}")

    if otros_reales:
        rad_encontrado = otros_reales[0]
        return "NO_PERTENECE", f"Radicado {rad_encontrado} encontrado, no coincide con {case_year}-{case_seq_padded}"

    # === CRITERIO 6: NOMBRE DE OTRO ACCIONANTE en filename ===
    # Si el archivo dice "RESPUESTA FOREST RAUL FABRA.docx" y el caso es de BELSY,
    # verificar si "RAUL FABRA" es accionante de OTRO caso en la DB
    fn_norm = _norm(filename)
    if acc_words and len(acc_words) >= 2:
        # Verificar que el accionante del caso NO está en el filename
        acc_in_fn = sum(1 for w in acc_words[:3] if w in fn_norm)
        if acc_in_fn == 0 and len(fn_norm) > 10:
            # El filename no menciona al accionante → podría ser de otro caso
            # Extraer palabras del filename que podrían ser nombres
            fn_words = set(re.findall(r'[A-Z]{4,}', fn_norm))
            fn_words -= {"RESPUESTA", "FOREST", "TUTELA", "FALLO", "AUTO", "SENTENCIA",
                         "GMAIL", "EMAIL", "OFICIO", "NOTIFICA", "URGENTE", "ADMISORIO",
                         "CONTESTACION", "IMPUGNACION", "INCIDENTE", "DESACATO",
                         "EDUCACION", "SANTANDER", "GOBERNACION", "SECRETARIA", "MERGED",
                         "ILOVEPDF", "COMPRESSED", "ANEXOS", "ESCRITO", "PRUEBA"}
            if len(fn_words) >= 2:
                return "SOSPECHOSO", f"Filename '{filename}' no menciona al accionante {accionante[:30]}"

    return "OK", "Sin radicados conflictivos"


def verify_all_documents(db: "Session") -> dict:
    """Auditoría retroactiva: verificar TODOS los documentos de todos los casos."""
    cases = db.query(Case).filter(
        Case.folder_name.isnot(None), Case.folder_name != "None", Case.folder_name != "",
    ).all()

    stats = {"total": 0, "ok": 0, "sospechoso": 0, "no_pertenece": 0}

    for case in cases:
        for doc in case.documents:
            if not doc.extracted_text or len(doc.extracted_text) < 100:
                continue
            stats["total"] += 1
            status, detalle = verify_document_belongs(case, doc)
            doc.verificacion = status
            doc.verificacion_detalle = detalle
            stats[status.lower()] = stats.get(status.lower(), 0) + 1

    db.commit()
    return stats


def _cross_validate_radicado(case: Case, fields: dict, db, stats: dict):
    """Validación cruzada: comparar radicado extraído por IA vs radicado de la carpeta.
    Si no coinciden, registrar alerta de posible contaminación de datos."""
    import re

    folder = case.folder_name or ""
    m = re.match(r'(20\d{2})[-\s]?0*(\d+)', folder)
    if not m:
        return

    case_year = m.group(1)
    case_seq = m.group(2).lstrip('0') or '0'

    # Radicado extraído por la IA
    rad_field = fields.get("RADICADO_23_DIGITOS")
    if not rad_field or not rad_field.value:
        return

    rad_extracted = rad_field.value
    # Extraer secuencia del radicado extraído
    digits = re.sub(r'[^0-9]', '', rad_extracted)
    if len(digits) < 10:
        return

    # Buscar el año y secuencia en el radicado extraído
    rad_m = re.search(r'(20\d{2})[\-\s]?0*(\d{2,5})(?:\D|$)', rad_extracted.replace('-', '').replace(' ', ''))
    if not rad_m:
        return

    ext_seq = rad_m.group(2).lstrip('0') or '0'

    if ext_seq != case_seq:
        # El radicado extraído NO coincide con la carpeta
        stats["cross_validation_alert"] = f"Radicado extraído {rad_extracted} no coincide con carpeta {case_year}-{case_seq.zfill(5)}"
        db.add(AuditLog(
            case_id=case.id,
            field_name="CROSS_VALIDATION",
            old_value=f"{case_year}-{case_seq.zfill(5)}",
            new_value=rad_extracted,
            action="ALERTA_RADICADO_CRUZADO",
            source="validacion_cruzada_post_ia",
        ))


def _check_and_link_to_base_case(db, case: Case, stats: dict):
    """Post-IA: Si la extracción encontró un radicado 23 dígitos que pertenece a otro caso,
    marcar este caso como INCIDENTE vinculado al caso base.
    Esto detecta incidentes de desacato que se crearon como caso nuevo."""
    import re

    if not case.radicado_23_digitos or case.tipo_actuacion == "INCIDENTE":
        return  # Ya es incidente o no tiene radicado

    norm_new = re.sub(r"[^0-9]", "", case.radicado_23_digitos or "")
    if len(norm_new) < 15:
        return

    # Buscar si otro caso (distinto) tiene el mismo radicado base (primeros 15 dígitos)
    other_cases = db.query(Case).filter(
        Case.id != case.id,
        Case.radicado_23_digitos.isnot(None),
        Case.radicado_23_digitos != "",
        Case.tipo_actuacion == "TUTELA",
    ).all()

    for other in other_cases:
        norm_other = re.sub(r"[^0-9]", "", other.radicado_23_digitos or "")
        if len(norm_other) >= 15 and norm_new[:15] == norm_other[:15] and case.id != other.id:
            # Encontró tutela base — marcar este como INCIDENTE
            case.tipo_actuacion = "INCIDENTE"
            db.add(AuditLog(
                case_id=case.id,
                field_name="tipo_actuacion",
                old_value="TUTELA",
                new_value="INCIDENTE",
                action="AUTO_RECLASIFICAR",
                source=f"radicado_compartido_con_id_{other.id}",
            ))
            stats["reclasificado_incidente"] = True
            return


def _verify_documents_belong_to_case(case: Case, doc_texts: list[dict]) -> list[dict]:
    """Verificar que documentos pertenecen al caso. Delega a verify_document_belongs().

    Returns: lista de documentos que NO corresponden al caso (vacía si todo OK).
    """
    import re

    folder = case.folder_name or ""
    m = re.match(r'(20\d{2})[-\s]?0*(\d+)', folder)
    if not m:
        return []

    case_year = m.group(1)
    case_seq_padded = m.group(2).lstrip('0').zfill(5)

    mismatched = []
    for doc_info in doc_texts:
        filename = doc_info["filename"]
        text = doc_info.get("text", "")

        # No verificar emails, datos conocidos, ni archivos .md de emails
        if filename.startswith("EMAIL:") or filename == "DATO_CONOCIDO":
            continue
        if filename.startswith("Email_") and filename.endswith(".md"):
            continue
        if not text or len(text) < 200:
            continue

        # Crear Document ligero para reusar verify_document_belongs
        mock_doc = Document(filename=filename, extracted_text=text)
        status, detalle = verify_document_belongs(case, mock_doc)

        if status == "NO_PERTENECE":
            # Extraer radicado encontrado para el reporte
            otros = re.findall(r'(20\d{2})[-\s]?0*(\d{2,5})\b', text[:5000])
            found_rad = f"{otros[0][0]}-{otros[0][1]}" if otros else "desconocido"
            mismatched.append({
                "filename": filename,
                "radicado_encontrado": found_rad,
                "radicado_caso": f"{case_year}-{case_seq_padded}",
            })

    return mismatched


def _validate_extracted_fields(fields: dict, forest_from_emails: str | None):
    """Validar campos extraidos por IA para evitar alucinaciones."""
    import re

    from backend.agent.forest_extractor import FOREST_BLACKLIST

    # Validar RADICADO_FOREST
    forest = fields.get("RADICADO_FOREST")
    if forest:
        val = forest.value.strip()
        # No debe estar en la blacklist
        if val in FOREST_BLACKLIST:
            fields.pop("RADICADO_FOREST", None)
        # No debe tener guiones
        elif "-" in val:
            fields.pop("RADICADO_FOREST", None)
        # No debe ser muy corto (<7 digitos)
        elif len(re.sub(r'\D', '', val)) < 7:
            fields.pop("RADICADO_FOREST", None)
        # Si tenemos FOREST de emails, priorizar ese
        elif forest_from_emails and val != forest_from_emails:
            from backend.extraction.ai_extractor import AIFieldResult
            fields["RADICADO_FOREST"] = AIFieldResult(
                value=forest_from_emails, confidence="ALTA", source="email_regex"
            )

    # Validar FOREST_IMPUGNACION
    forest_imp = fields.get("FOREST_IMPUGNACION")
    if forest_imp:
        val = forest_imp.value.strip()
        if val in FOREST_BLACKLIST:
            fields.pop("FOREST_IMPUGNACION", None)
        elif "-" in val or len(re.sub(r'\D', '', val)) < 7:
            fields.pop("FOREST_IMPUGNACION", None)

    # Validar SENTIDO_FALLO_1ST
    fallo1 = fields.get("SENTIDO_FALLO_1ST")
    if fallo1:
        valid = {"CONCEDE", "NIEGA", "IMPROCEDENTE", "CONCEDE PARCIALMENTE"}
        if fallo1.value.strip().upper() not in valid:
            fields.pop("SENTIDO_FALLO_1ST", None)

    # Validar SENTIDO_FALLO_2ND
    fallo2 = fields.get("SENTIDO_FALLO_2ND")
    if fallo2:
        valid = {"CONFIRMA", "REVOCA", "MODIFICA"}
        if fallo2.value.strip().upper() not in valid:
            fields.pop("SENTIDO_FALLO_2ND", None)

    # Validar ABOGADO_RESPONSABLE: verificar fuente + lista de abogados
    abogado = fields.get("ABOGADO_RESPONSABLE")
    if abogado and abogado.value:
        # CAPA 3: Verificar que viene de un DOCX de respuesta, NO de un PDF
        abogado_source = (abogado.source or "").lower()
        source_is_docx = any(k in abogado_source for k in (".docx", "respuesta", "forest", "docx_footer"))
        if not source_is_docx and lawyer_from_docx:
            # La IA lo sacó de un PDF → override con el regex del DOCX
            from backend.extraction.ai_extractor import AIFieldResult as _AFR
            fields["ABOGADO_RESPONSABLE"] = _AFR(
                value=lawyer_from_docx, confidence="ALTA", source="docx_footer_regex_override"
            )
            abogado = fields["ABOGADO_RESPONSABLE"]
        elif not source_is_docx and not lawyer_from_docx:
            # La IA lo sacó de un PDF y no hay DOCX → descartar
            fields.pop("ABOGADO_RESPONSABLE", None)
            abogado = None

    if abogado and abogado.value:
        import json
        try:
            abogados_path = Path(__file__).resolve().parent.parent / "data" / "abogados_sed.json"
            with open(abogados_path) as f:
                abogados_validos = json.load(f)
            val_upper = abogado.value.strip().upper()
            # Verificar si algún abogado válido coincide (2+ apellidos)
            import unicodedata
            def norm(s):
                return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn').upper()
            val_norm = norm(val_upper)
            match_found = False
            for av in abogados_validos:
                av_norm = norm(av)
                # Comparar por 2+ palabras coincidentes
                av_words = set(av_norm.split())
                val_words = set(val_norm.split())
                common = av_words & val_words
                if len(common) >= 2:
                    # Reemplazar con el nombre canónico
                    from backend.extraction.ai_extractor import AIFieldResult
                    fields["ABOGADO_RESPONSABLE"] = AIFieldResult(
                        value=av, confidence="ALTA", source="validado_lista_abogados"
                    )
                    match_found = True
                    break
            if not match_found:
                # El nombre no está en la lista — probablemente es de otra entidad
                fields.pop("ABOGADO_RESPONSABLE", None)
        except Exception:
            pass  # Si no hay archivo de abogados, no validar

    # Validar fechas (DD/MM/YYYY)
    date_fields = ["FECHA_INGRESO", "FECHA_RESPUESTA", "FECHA_FALLO_1ST", "FECHA_FALLO_2ND",
                    "FECHA_APERTURA_INCIDENTE", "FECHA_APERTURA_INCIDENTE_2", "FECHA_APERTURA_INCIDENTE_3"]
    for df in date_fields:
        field = fields.get(df)
        if field and field.value:
            val = field.value.strip()
            if not re.match(r'^\d{2}/\d{2}/\d{4}$', val):
                fields.pop(df, None)
