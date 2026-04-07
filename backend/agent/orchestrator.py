"""Agent Orchestrator: integra todas las fases de extracción inteligente.

Loop principal del agente:
0. CLASIFICAR → Verificar que cada documento pertenece a esta carpeta (mover los que no)
1. RECOPILAR → ContextAssembler reúne TODO el contexto
2. PRE-EXTRAER → RegexExtractors corren en todas las fuentes
3. RAZONAR → Llamada a Gemini con contexto completo
4. VALIDAR → PostValidators verifican cada campo
5. DECIDIR → ConflictResolver fusiona regex + IA
6. APRENDER → Almacenar para futuras extracciones
"""

import json
import logging
import os
import re
import shutil
import time
from pathlib import Path

from sqlalchemy.orm import Session

from backend.agent.context import ContextAssembler, CaseContext
from backend.agent.extractors.registry import pre_extract_all, resolve_field
from backend.agent.extractors.base import ExtractionResult
from backend.agent.reasoning import ReasoningChain, Evidence, save_reasoning
from backend.agent.validators.field_validators import validate_field, validate_cross_fields
from backend.knowledge.indexer import index_case_fields

logger = logging.getLogger("tutelas.agent")


# ---------------------------------------------------------------------------
# Fase 0: Clasificación de documentos (integrado del smart_extractor)
# ---------------------------------------------------------------------------

CLASSIFY_PROMPT = """Eres un verificador de expedientes judiciales colombianos.

Te doy la CARPETA (nombre) y TODOS los documentos que contiene con su texto.
Tu trabajo: determinar si CADA documento pertenece a esta carpeta o no.

CARPETA: {folder_name}

DOCUMENTOS:
{docs_text}

Para CADA documento, responde en JSON:
{{
  "carpeta_radicado": "",
  "carpeta_accionante": "",
  "documentos": [
    {{
      "filename": "",
      "pertenece": true/false,
      "radicado": "",
      "accionante": "",
      "razon": ""
    }}
  ]
}}

REGLAS:
- Un documento PERTENECE si menciona el MISMO radicado o accionante que la mayoría
- Un documento NO PERTENECE si tiene un radicado DIFERENTE y un accionante DIFERENTE
- Emails (.md) siempre pertenecen si fueron clasificados para esta carpeta
- Anexos genéricos (certificados, resoluciones) sin radicado → pertenecen por defecto
- El radicado de 23 dígitos es el definitivo. Si 2 documentos tienen radicados diferentes, son de casos DIFERENTES
- NUNCA inventes datos. Si no puedes determinar, pon pertenece=true

Responde SOLO JSON válido."""


def _call_gemini_classify(prompt: str, max_retries: int = 3) -> dict:
    """Llamar a Gemini para clasificación de documentos."""
    try:
        from google import genai
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY", ""))

        for attempt in range(max_retries):
            try:
                r = client.models.generate_content(
                    model="gemini-2.5-flash", contents=prompt,
                    config=genai.types.GenerateContentConfig(
                        response_mime_type="application/json", temperature=0.1,
                    ),
                )
                text = r.text.strip()
                if "```" in text:
                    text = re.sub(r"```(?:json)?\s*", "", text).strip()
                    text = re.sub(r"\s*```$", "", text).strip()
                return json.loads(text)
            except Exception as e:
                if "429" in str(e):
                    wait = 15 * (attempt + 1)
                    logger.warning(f"Rate limit clasificación, esperando {wait}s...")
                    time.sleep(wait)
                else:
                    logger.error(f"Gemini classify error: {e}")
                    return {}
    except Exception as e:
        logger.error(f"Gemini classify init error: {e}")
    return {}


def classify_and_clean_folder(db: Session, case, base_dir: str) -> dict:
    """Fase 0: Clasificar documentos y mover los que no pertenecen.

    Returns dict con stats de clasificación.
    """
    from backend.database.models import Document
    from backend.extraction.pipeline import extract_document_text
    from backend.config import BASE_DIR

    pendiente_dir = Path(base_dir) / "PENDIENTE DE UBICACION"
    result = {
        "docs_total": 0,
        "docs_ok": 0,
        "docs_movidos": 0,
        "docs_movidos_list": [],
        "classification_error": None,
    }

    if not case.folder_path or not Path(case.folder_path).exists():
        result["classification_error"] = "Carpeta no existe en disco"
        return result

    # Leer texto de todos los documentos
    docs_text_parts = []
    doc_map = {}

    for doc in case.documents:
        if not doc.file_path or not Path(doc.file_path).exists():
            continue
        if not doc.extracted_text:
            text, method = extract_document_text(doc)
            if text.strip():
                doc.extracted_text = text
                doc.extraction_method = method
                from datetime import datetime
                doc.extraction_date = datetime.utcnow()

        text = (doc.extracted_text or "")[:1500]
        if text.strip():
            docs_text_parts.append(f"### {doc.filename}\n{text}")
            doc_map[doc.filename] = doc

    result["docs_total"] = len(docs_text_parts)

    if not docs_text_parts:
        result["classification_error"] = "Sin documentos con texto"
        return result

    db.commit()

    # Llamar a Gemini para clasificar
    docs_combined = "\n\n".join(docs_text_parts)
    prompt = CLASSIFY_PROMPT.format(
        folder_name=case.folder_name,
        docs_text=docs_combined[:15000],
    )
    ai_result = _call_gemini_classify(prompt)

    if not ai_result or "documentos" not in ai_result:
        result["classification_error"] = "IA no respondió correctamente, se asume todos OK"
        result["docs_ok"] = result["docs_total"]
        return result

    # Procesar resultado
    pendiente_dir.mkdir(parents=True, exist_ok=True)

    for doc_info in ai_result.get("documentos", []):
        filename = doc_info.get("filename", "")
        pertenece = doc_info.get("pertenece", True)
        doc = doc_map.get(filename)
        if not doc:
            continue

        if pertenece:
            result["docs_ok"] += 1
            doc.verificacion = "OK"
            doc.verificacion_detalle = doc_info.get("razon", "Verificado por IA")
        else:
            src = Path(doc.file_path)
            if src.exists():
                dst = pendiente_dir / filename
                counter = 1
                while dst.exists():
                    dst = pendiente_dir / f"{src.stem}_{counter}{src.suffix}"
                    counter += 1
                try:
                    shutil.move(str(src), str(dst))
                    doc.file_path = str(dst)
                    doc.verificacion = "NO_PERTENECE"
                    doc.verificacion_detalle = (
                        f"IA: {doc_info.get('razon', '')}. "
                        f"Rad: {doc_info.get('radicado', '')}, "
                        f"Acc: {doc_info.get('accionante', '')}"
                    )
                    db.delete(doc)
                    result["docs_movidos"] += 1
                    result["docs_movidos_list"].append(filename)
                    logger.info(f"Movido {filename} de {case.folder_name} → PENDIENTE DE UBICACION")
                except Exception as e:
                    logger.error(f"Error moviendo {filename}: {e}")

    # Actualizar accionante/radicado si Gemini los identificó mejor
    ai_acc = ai_result.get("carpeta_accionante", "")
    ai_rad = ai_result.get("carpeta_radicado", "")
    if ai_acc and not (case.accionante or "").strip():
        case.accionante = ai_acc
    if ai_rad and not (case.radicado_23_digitos or "").strip():
        case.radicado_23_digitos = ai_rad

    db.commit()
    return result


# ---------------------------------------------------------------------------
# Extracción principal del agente
# ---------------------------------------------------------------------------

def smart_extract_case(db: Session, case_id: int, base_dir: str, classify_docs: bool = False) -> dict:
    """Extracción inteligente de un caso usando el agente completo.

    Args:
        classify_docs: Si True, ejecuta Fase 0 (clasificación de documentos)
                       antes de extraer. Mueve docs que no pertenecen.

    Returns dict with:
        - fields: dict[str, str] - campos extraídos
        - reasoning: list[dict] - cadena de razonamiento
        - warnings: list[str] - advertencias de validación
        - confidence_avg: float - confianza promedio
        - classification: dict - stats de clasificación (si classify_docs=True)
    """
    from backend.database.models import Case

    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise ValueError(f"Caso {case_id} no encontrado")

    classification_result = None

    # Fase 0: Clasificar documentos (opcional)
    if classify_docs:
        logger.info(f"Fase 0: Clasificando documentos de caso {case_id}")
        classification_result = classify_and_clean_folder(db, case, base_dir)
        if classification_result["docs_movidos"] > 0:
            logger.info(
                f"Clasificación: {classification_result['docs_movidos']} docs movidos, "
                f"{classification_result['docs_ok']} OK"
            )
        # Refresh case after possible document moves
        db.refresh(case)

    # 1. RECOPILAR: ensamblar contexto completo
    assembler = ContextAssembler(db, base_dir)
    context = assembler.assemble(case_id)

    # 2. PRE-EXTRAER: regex en todas las fuentes
    doc_texts = [{"filename": d.filename, "text": d.content, "priority": d.priority}
                  for d in context.documents]

    from backend.database.models import Email
    case_emails = db.query(Email).filter(Email.case_id == case_id).all()
    regex_results = pre_extract_all(doc_texts, case_emails)

    logger.info(f"Pre-extracted {len(regex_results)} fields with regex for case {case_id}")

    # 3. RAZONAR: llamar a Gemini con contexto completo
    ai_results = _call_ai_extraction(context, regex_results)

    # 4. DECIDIR: fusionar regex + IA por campo
    final_fields = {}
    reasoning_chains = []

    all_field_names = set(list(regex_results.keys()) + list(ai_results.keys()))
    for field_name in all_field_names:
        regex_r = regex_results.get(field_name)
        ai_r = ai_results.get(field_name)
        resolved = resolve_field(field_name, regex_r, ai_r)

        if resolved and resolved.value:
            # 5. VALIDAR
            is_valid, reason = validate_field(field_name.upper(), resolved.value)
            if not is_valid:
                logger.warning(f"Validation failed for {field_name}: {reason}")
                resolved.confidence = max(0, resolved.confidence - 30)
                resolved.reasoning += f" [VALIDACIÓN: {reason}]"

            final_fields[field_name] = resolved.value

            # Build reasoning chain
            evidence = []
            if regex_r:
                evidence.append(Evidence(source=regex_r.source, text_snippet=regex_r.value, relevance=0.9))
            if ai_r:
                evidence.append(Evidence(source=ai_r.source, text_snippet=ai_r.value, relevance=0.8))

            reasoning_chains.append(ReasoningChain(
                field_name=field_name,
                value=resolved.value,
                confidence=resolved.confidence,
                method=resolved.method,
                evidence=evidence,
                reasoning=resolved.reasoning,
            ))

    # Normalizar formato de campos extraidos
    import re as _re
    for _fn, _fv in list(final_fields.items()):
        if not _fv:
            continue
        # RADICADO_23D: formatear con guiones si viene sin ellos
        if _fn == "radicado_23_digitos" and "-" not in _fv:
            _clean = _re.sub(r'[\s\.]', '', _fv)
            if len(_clean) >= 23 and _clean.isdigit():
                final_fields[_fn] = f"{_clean[:2]}-{_clean[2:5]}-{_clean[5:7]}-{_clean[7:9]}-{_clean[9:12]}-{_clean[12:16]}-{_clean[16:21]}-{_clean[21:23]}"
        # JUZGADO: corregir typos comunes
        if _fn == "juzgado" and _fv:
            final_fields[_fn] = _fv.replace("CONFUNCIONES", "Con Funciones").replace("confunciones", "con funciones")

    # Anti-contaminacion: validar radicado vs carpeta
    folder_name = case.folder_name or ""
    _rad_m = _re.match(r'(20\d{2})[-\s]?0*(\d+)', folder_name)
    if _rad_m:
        _case_seq = _rad_m.group(2).lstrip('0')
        _rad23 = final_fields.get("radicado_23_digitos", "")
        if _rad23 and _case_seq not in _re.sub(r'[\s\-\.]', '', _rad23):
            logger.warning(f"CONTAMINACION DETECTADA: rad23 '{_rad23}' no coincide con carpeta '{folder_name}'. Eliminando campo.")
            final_fields.pop("radicado_23_digitos", None)
            # Tambien limpiar campos que podrian estar contaminados
            for _suspect in ("fecha_ingreso", "juzgado"):
                if _suspect in final_fields and _suspect not in regex_results:
                    logger.warning(f"Campo sospechoso '{_suspect}' removido por posible contaminacion")
                    final_fields.pop(_suspect, None)

    # Validacion post-extraccion unificada (compartida con Pipeline)
    try:
        from backend.extraction.post_validator import validate_extraction
        validated, post_warnings = validate_extraction(case, final_fields)
        for _vf, _vv in validated.items():
            if _vv:
                final_fields[_vf] = _vv
            else:
                final_fields.pop(_vf, None)
    except Exception as _ve:
        post_warnings = [f"Post-validation error: {_ve}"]

    # Cross-field validation
    upper_fields = {k.upper(): v for k, v in final_fields.items()}
    warnings = validate_cross_fields(upper_fields)
    warnings.extend(post_warnings)

    # Save reasoning to DB
    save_reasoning(db, case_id, reasoning_chains)

    # Update Knowledge Base
    index_case_fields(db, case_id, final_fields)

    # Calculate average confidence
    confidences = [r.confidence for r in reasoning_chains]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0

    logger.info(
        f"Smart extraction complete for case {case_id}: "
        f"{len(final_fields)} fields, avg confidence {avg_confidence:.0f}%, "
        f"{len(warnings)} warnings"
    )

    result = {
        "fields": final_fields,
        "reasoning": [r.to_spanish() for r in reasoning_chains],
        "warnings": warnings,
        "confidence_avg": round(avg_confidence, 1),
        "fields_count": len(final_fields),
    }

    if classification_result:
        result["classification"] = classification_result

    return result


def _call_ai_extraction(context: CaseContext, known_fields: dict) -> dict[str, ExtractionResult]:
    """Llamar a Gemini/IA con el contexto completo del caso."""
    try:
        from backend.extraction.ai_extractor import extract_with_ai, SYSTEM_PROMPT

        # Build doc_texts for the existing AI extractor
        doc_texts = []

        # Restriccion anti-contaminacion: el caso actual
        doc_texts.append({"filename": "RESTRICCION_CASO", "text": f"RESTRICCION CRITICA: Este caso es '{context.folder_name}'. TODOS los campos extraidos DEBEN corresponder a este caso. Si encuentras datos de otro caso/radicado diferente, IGNORA esos datos."})

        # Inject known data first
        if known_fields:
            known_parts = ["DATOS YA EXTRAÍDOS POR REGEX (usar como referencia, NO sobreescribir si son correctos):"]
            for field, result in known_fields.items():
                known_parts.append(f"  {field}: {result.value} (confianza: {result.confidence}%, fuente: {result.source})")
            doc_texts.append({"filename": "DATOS_CONOCIDOS", "text": "\n".join(known_parts)})

        # Add corrections as few-shot
        if context.corrections:
            correction_parts = ["CORRECCIONES HISTÓRICAS (aprende de estos errores anteriores):"]
            for c in context.corrections:
                correction_parts.append(f"  Campo {c.field_name}: IA dijo '{c.ai_value}' pero correcto es '{c.corrected_value}'")
            doc_texts.append({"filename": "CORRECCIONES", "text": "\n".join(correction_parts)})

        # Add documents
        for doc in sorted(context.documents, key=lambda d: d.priority):
            doc_texts.append({"filename": doc.filename, "text": doc.content[:30000]})

        # Add emails
        for em in context.emails:
            email_text = f"Subject: {em.subject}\nFrom: {em.sender}\nDate: {em.date}\n\n{em.body}"
            doc_texts.append({"filename": f"email_{em.email_id}", "text": email_text})

        if not doc_texts:
            return {}

        # Call AI
        ai_result = extract_with_ai(doc_texts, folder_name=context.folder_name)

        # Convert to ExtractionResult dict
        results = {}
        for field_name, field_result in ai_result.fields.items():
            results[field_name.lower()] = ExtractionResult(
                value=field_result.value,
                confidence={"ALTA": 85, "MEDIA": 60, "BAJA": 35}.get(field_result.confidence, 50),
                source=field_result.source,
                method="ai",
                reasoning=f"Extraído por IA desde {field_result.source}",
            )
        return results

    except Exception as e:
        logger.error(f"AI extraction failed: {e}")
        return {}
