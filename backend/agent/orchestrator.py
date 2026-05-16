"""Agent Orchestrator: integra todas las fases de extracción inteligente.

Loop principal del agente:
0. CLASIFICAR → Verificar que cada documento pertenece a esta carpeta (mover los que no)
1. RECOPILAR → ContextAssembler reúne TODO el contexto
2. PRE-EXTRAER → RegexExtractors corren en todas las fuentes
3. RAZONAR → Llamada a IA con contexto completo
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


def _call_ai_classify(prompt: str, max_retries: int = 3) -> dict:
    """Clasificar documentos vía LLM local (LOCAL_ONLY).

    Antes usaba Smart Router (DeepSeek/Haiku) — refactorizado a llama-server
    local Qwen3 para mantener LOCAL_ONLY=true. Si LLM local falla, devuelve {}
    y el orchestrator asume todos los docs OK (filename-based fallback).
    """
    try:
        from backend.extraction.ai_extractor import _call_local, _LOCAL_MODEL
        # /no_think evita que Qwen3 gaste tokens en <think> y devuelva vacío
        messages = [
            {"role": "user", "content": "/no_think\n" + prompt + "\n\nResponde SOLO JSON válido."},
        ]
        for attempt in range(max_retries):
            try:
                raw, _, _ = _call_local(messages, _LOCAL_MODEL, max_tokens=1024)
                if "```" in raw:
                    raw = re.sub(r"```(?:json)?\s*", "", raw).strip()
                    raw = re.sub(r"\s*```$", "", raw).strip()
                json_match = re.search(r'\{[\s\S]*\}', raw)
                if json_match:
                    return json.loads(json_match.group())
                return json.loads(raw) if raw.strip() else {}
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"AI classify attempt {attempt+1} fail: {str(e)[:100]}")
                    time.sleep(2)
                else:
                    logger.error(f"AI classify final error: {str(e)[:200]}")
                    return {}
    except Exception as e:
        logger.error(f"AI classify init error: {str(e)[:200]}")
    return {}


def classify_and_clean_folder(db: Session, case, base_dir: str) -> dict:
    """Fase 0: Clasificar documentos y mover los que no pertenecen.

    Returns dict con stats de clasificación.
    """
    from backend.database.models import Document
    from backend.extraction.doc_ops import extract_document_text
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

    # Llamar a IA (Smart Router) para clasificar
    docs_combined = "\n\n".join(docs_text_parts)
    prompt = CLASSIFY_PROMPT.format(
        folder_name=case.folder_name,
        docs_text=docs_combined[:15000],
    )
    ai_result = _call_ai_classify(prompt)

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

    # Actualizar accionante/radicado si IA los identificó mejor
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

    # 3. RAZONAR: llamar a IA (Smart Router) con contexto completo
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
            logger.warning(f"CONTAMINACION DETECTADA: rad23 '{_rad23}' no coincide con carpeta '{folder_name}'. Limpiando campos contaminados.")
            final_fields.pop("radicado_23_digitos", None)
            # Limpiar TODOS los campos que podrian estar contaminados (no solo radicado)
            _contam_fields = ("fecha_ingreso", "juzgado", "accionante", "accionados",
                              "ciudad", "derecho_vulnerado", "vinculados", "asunto", "pretensiones")
            for _suspect in _contam_fields:
                if _suspect in final_fields and _suspect not in regex_results:
                    logger.warning(f"Campo '{_suspect}' removido por contaminacion cruzada")
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
    """Llamar al LLM como COMPILADOR (contrato SYSTEM_PROMPT_COMPILER.md).

    El LLM recibe JSON con campos_extraidos + campos_huecos + evidencia_textual
    (≤1500 chars filtrados por marcadores documentados) y devuelve solo los
    huecos. Reemplaza el patrón legacy de mandar texto plano completo.
    """
    try:
        from backend.extraction.ai_extractor import (
            _call_local, _load_system_prompt, _parse_ai_json,
        )
        from backend.extraction.compiler_io import (
            build_compiler_payload, apply_post_validators,
        )

        # Documentos: docs reales + emails como docs sintéticos para evidencia
        documents: list[dict] = []
        for doc in sorted(context.documents, key=lambda d: d.priority):
            documents.append({
                "filename": doc.filename,
                "text": (doc.content or "")[:8000],
                "doc_type": getattr(doc, "doc_type", "OTRO"),
            })
        for em in context.emails:
            documents.append({
                "filename": f"email_{em.email_id}",
                "text": (
                    f"Subject: {em.subject}\nFrom: {em.sender}\n"
                    f"Date: {em.date}\n\n{em.body}"
                )[:8000],
                "doc_type": "EMAIL_MD",
            })

        # Inyectar correcciones históricas como hint en metadata
        metadata_extra: dict = {}
        if context.corrections:
            metadata_extra["correcciones_historicas"] = [
                {"campo": c.field_name, "ia": c.ai_value, "correcto": c.corrected_value}
                for c in context.corrections[:10]
            ]

        payload = build_compiler_payload(
            known_fields=known_fields,
            documents=documents,
            folder_name=context.folder_name,
            metadata_extra=metadata_extra,
        )

        if not payload["campos_huecos"]:
            logger.info(
                "AI compiler: 0 huecos para %s, skip LLM", context.folder_name
            )
            return {}

        # /no_think obligatorio: Qwen3 base sin esto gasta todos los tokens
        # en <think> y devuelve content vacío (CLAUDE.md v8.3 finding).
        user_msg = "/no_think\n" + json.dumps(payload, ensure_ascii=False)
        messages = [
            {"role": "system", "content": _load_system_prompt()},
            {"role": "user", "content": user_msg},
        ]

        logger.info(
            "AI compiler: %d huecos, %d chars evidencia, folder=%s",
            len(payload["campos_huecos"]),
            len(payload["evidencia_textual"]),
            context.folder_name,
        )

        raw, in_tok, out_tok = _call_local(messages, max_tokens=2048)
        logger.info("AI compiler raw response (in=%d, out=%d): %r", in_tok, out_tok, raw[:600])
        parsed = _parse_ai_json(raw) if raw.strip() else {}

        # Solo aceptar campos que estaban en huecos (defensa anti-contaminación)
        holes_set = {h.lower() for h in payload["campos_huecos"]}
        results: dict[str, ExtractionResult] = {}
        for field_name, field_result in parsed.items():
            if field_name.lower() not in holes_set:
                continue
            results[field_name.lower()] = ExtractionResult(
                value=field_result.value,
                confidence={"ALTA": 85, "MEDIA": 60, "BAJA": 35}.get(
                    field_result.confidence, 50
                ),
                source=field_result.source or "compiler",
                method="ai_compiler",
                reasoning=f"Llenado por LLM compilador (hueco) desde {field_result.source or 'evidencia'}",
            )

        # Post-validators determinísticos (reglas .md corpus SED)
        inferred = apply_post_validators(
            {k: v.value for k, v in results.items()}, known_fields
        )
        for fname, val in inferred.items():
            results[fname] = ExtractionResult(
                value=val,
                confidence=80,
                source="post_validator_rule",
                method="deterministic",
                reasoning=f"Inferido por regla del .md corpus SED",
            )

        logger.info(
            "AI compiler: %d/%d huecos llenados (in_tok=%d, out_tok=%d) +%d inferidos",
            len(results) - len(inferred), len(payload["campos_huecos"]),
            in_tok, out_tok, len(inferred),
        )
        return results

    except Exception as e:
        logger.error(f"AI extraction failed: {e}")
        return {}
