"""Fase 6.5: IA local complementaria — llena campos vacíos aplicables.

Después de la cognición determinista (capas 0-6), evalúa qué campos del
protocolo siguen vacíos y son APLICABLES (impugnacion=SI → quien_impugno
aplica, etc.). Construye prompt enfocado SOLO a esos campos y los pide al
LLM local (Qwen3-4B + LoRA-CoT v2).

Reduce REVISION drásticamente al cerrar los huecos que disparan entropy alta.
NUNCA pisa valores ya extraídos por determinista — solo llena vacíos.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger("tutelas.complementary_ai")


# Campos objetivo de complemento IA (los que disparan REVISION cuando están vacíos)
TARGET_FIELDS = (
    "abogado_responsable", "vinculados", "fecha_respuesta",
    "quien_impugno", "forest_impugnacion", "juzgado_2nd",
    "sentido_fallo_2nd", "fecha_fallo_2nd",
    "fecha_apertura_incidente", "responsable_desacato", "decision_incidente",
    "incidente_2", "fecha_apertura_incidente_2",
    "responsable_desacato_2", "decision_incidente_2",
    "incidente_3", "fecha_apertura_incidente_3",
    "responsable_desacato_3", "decision_incidente_3",
)


def _field_applicable(case, field: str) -> bool:
    """Decide si el campo aplica al case dado (mismo criterio que entropy.py)."""
    imp = (getattr(case, "impugnacion", "") or "").upper()
    inc = (getattr(case, "incidente", "") or "").upper()

    if field in ("quien_impugno", "forest_impugnacion", "juzgado_2nd",
                 "sentido_fallo_2nd", "fecha_fallo_2nd"):
        return imp.startswith("S")
    if field in ("fecha_apertura_incidente", "responsable_desacato", "decision_incidente"):
        return inc.startswith("S")
    if field in ("incidente_2", "fecha_apertura_incidente_2",
                 "responsable_desacato_2", "decision_incidente_2"):
        return bool(getattr(case, "decision_incidente", None))
    if field in ("incidente_3", "fecha_apertura_incidente_3",
                 "responsable_desacato_3", "decision_incidente_3"):
        return bool(getattr(case, "decision_incidente_2", None))
    return True


def _identify_missing_fields(case) -> list[str]:
    missing = []
    for f in TARGET_FIELDS:
        val = getattr(case, f, None)
        if val and str(val).strip():
            continue
        if _field_applicable(case, f):
            missing.append(f)
    return missing


def _build_prompt(case, full_text: str, missing_fields: list[str]) -> tuple[str, str]:
    """system + user prompt enfocados solo en campos faltantes."""
    case_summary = "\n".join([
        f"- accionante: {case.accionante or '?'}",
        f"- accionados: {(case.accionados or '?')[:200]}",
        f"- juzgado: {case.juzgado or '?'}",
        f"- ciudad: {case.ciudad or '?'}",
        f"- impugnacion: {case.impugnacion or '?'}",
        f"- incidente: {case.incidente or '?'}",
        f"- sentido_fallo_1st: {case.sentido_fallo_1st or '?'}",
        f"- decision_incidente: {case.decision_incidente or '?'}",
    ])

    truncated = full_text[:8000] if len(full_text) > 8000 else full_text

    # v8.1: marcar campos que requieren transcripción literal
    from backend.cognition.document_authority import is_literal_field
    literal_fields_in_request = [f for f in missing_fields if is_literal_field(f)]
    literal_note = ""
    if literal_fields_in_request:
        literal_note = (
            f"\n8. TRANSCRIPCIÓN LITERAL: los campos {literal_fields_in_request} "
            "se transcriben TAL CUAL aparecen en el escrito de tutela (o en el auto que "
            "avoca / fallo si reproducen las pretensiones en su parte motiva). "
            "NO parafrasees, NO resumas, NO traduzcas — copia el texto exacto."
        )

    system = (
        "Eres un asistente jurídico especializado en derecho colombiano y procesos de tutela "
        "del departamento de Santander. Extraes información estructurada de expedientes con precisión "
        "quirúrgica. Solo devuelves JSON válido.\n\n"
        "JERARQUÍA DE FUERZA PROBATORIA DE DOCUMENTOS (de mayor a menor peso):\n"
        "  Nivel 1 — JUDICIAL: auto que avoca, auto admisorio, sentencia/fallo, autos de pruebas, "
        "requerimientos. Lo dicho por el juez prevalece.\n"
        "  Nivel 2 — ADMINISTRATIVO: respuestas de la Secretaría de Educación a la tutela, "
        "resoluciones, informes técnicos, insumos institucionales adjuntos como pruebas.\n"
        "  Nivel 3 — PARTE ACCIONANTE: escrito de tutela y sus anexos (fuente primaria de "
        "pretensiones, accionante real, derecho vulnerado).\n"
        "  Nivel 4 — APELACIÓN/INCIDENTE: escritos de impugnación, escritos de incidente de "
        "desacato, autos de incidente, autos de sanción. Tienen fuerza propia para sus campos "
        "específicos (juzgado_2nd, decision_incidente, responsable_desacato).\n"
        "  Nivel 5 — OTRO: gmails de notificación, comunicaciones administrativas — solo trazabilidad.\n\n"
        "REGLAS CRÍTICAS:\n"
        "1. Si un campo NO está claramente en el texto, devuelves null. NUNCA inventes ni asumas.\n"
        "2. ACCIONANTE ≠ FIRMANTE: el firmante de un oficio (alcalde, personero, secretario) "
        "es REPRESENTANTE de la entidad accionada, NO el accionante. El accionante está en el "
        "encabezado del escrito de tutela bajo 'ACCIONANTE:' o en frase 'interpuesta por X contra Y'.\n"
        "3. NUNCA asumas MINISTERIO_PUBLICO/PROCURADURÍA salvo que aparezca explícitamente.\n"
        "4. Jurisdicción esperada: Santander (cód. DANE 68). Cases de otros departamentos "
        "(Tunja=15, Valledupar=20, Norte de Santander=54, Bogotá=11) deben marcarse como tales.\n"
        "5. Rad23: 22-23 dígitos con formato 68-XXX-XX-XX-XXX-AAAA-NNNNN-NN. NO confundir con "
        "rad_corto AAAA-NNNNN — rad_corto se reusa entre municipios distintos.\n"
        "6. Fechas: DD/MM/YYYY. Fallos: exactamente AMPARA / NIEGA / DECLARA HECHO SUPERADO / IMPROCEDENTE.\n"
        "7. Si el doc cita un rad23 que NO coincide con el rad23 del caso, NO uses ese doc para "
        "extraer datos — pertenece a otro expediente."
        + literal_note
    )
    user = (
        f"CONTEXTO YA CONOCIDO DEL CASO:\n{case_summary}\n\n"
        f"DOCUMENTOS DEL CASO (extracto):\n{truncated}\n\n"
        f"Extrae SOLO los siguientes campos faltantes:\n"
        f"{', '.join(missing_fields)}\n\n"
        f"REGLAS:\n"
        f"- Si un campo NO está en el texto, devuelve null (NO inventes).\n"
        f"- Fechas en formato DD/MM/YYYY.\n"
        f"- Fallos: usa exactamente \"AMPARA\", \"NIEGA\", \"DECLARA HECHO SUPERADO\" o \"IMPROCEDENTE\".\n"
        f"- responsable_desacato: nombre o cargo del sancionado por desacato.\n"
        f"- forest_impugnacion: número de radicado FOREST de la impugnación (formato 7 dígitos).\n"
        f"- juzgado_2nd: nombre completo del juzgado de segunda instancia.\n"
        f"\nResponde SOLO con JSON. Ejemplo:\n"
        f'{{"quien_impugno": "MUNICIPIO X", "juzgado_2nd": null, "decision_incidente": "AMPARA"}}'
    )
    return system, user


def _build_authority_weighted_text(db, case, max_chars: int = 8000) -> str:
    """v8.1: arma full_text priorizando docs de mayor autoridad.

    Concatena texto de documentos del case en orden de autoridad probatoria:
    JUDICIAL > ADMINISTRATIVO > PARTE_ACCIONANTE > APELACION > OTRO.
    Trunca cuando alcanza max_chars.
    """
    try:
        from backend.database.models import Document
        from backend.cognition.document_authority import get_authority, AuthorityLevel
    except Exception:
        return ""

    docs = db.query(Document).filter(
        Document.case_id == case.id,
        Document.verificacion == "OK",
    ).all()
    if not docs:
        return ""

    # Ordenar por autoridad ascendente (1 = JUDICIAL primero)
    docs_sorted = sorted(docs, key=lambda d: int(get_authority(d.doc_type or "")))

    parts: list[str] = []
    used = 0
    for d in docs_sorted:
        if used >= max_chars:
            break
        text = (d.extracted_text or "").strip()
        if not text:
            continue
        auth = get_authority(d.doc_type or "")
        header = f"\n=== [{auth.name}] {d.filename or '?'} (doc_type={d.doc_type}) ===\n"
        slice_size = min(len(text), max_chars - used - len(header))
        parts.append(header + text[:slice_size])
        used += len(header) + slice_size
    return "".join(parts)


def fill_missing_fields_with_ia(db, case, full_text: str) -> dict:
    """Fase 6.5: invoca LLM local para llenar campos faltantes aplicables.

    No-op si LLM_LOCAL_PRIMARY != true o no hay campos faltantes/texto.
    Retorna dict con stats: {missing, filled, tokens}.

    v8.1: si `db` está disponible, reordena el texto por autoridad de docs
    (JUDICIAL primero) antes de pasarlo al LLM.
    """
    if os.getenv("LLM_LOCAL_PRIMARY", "").lower() != "true":
        return {"skipped": "LLM_LOCAL_PRIMARY not enabled"}

    missing = _identify_missing_fields(case)
    if not missing:
        return {"missing": 0, "filled": 0}

    # v8.1: priorizar texto por autoridad documental
    if db is not None:
        weighted = _build_authority_weighted_text(db, case, max_chars=8000)
        if weighted:
            full_text = weighted

    if not full_text or len(full_text.strip()) < 200:
        return {"missing": len(missing), "filled": 0, "reason": "text_insufficient"}

    system, user = _build_prompt(case, full_text, missing)

    try:
        from backend.extraction.ai_extractor import _call_local
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        raw, in_tok, out_tok = _call_local(messages, "qwen3-4b-iuris", max_tokens=800)
    except Exception as e:
        logger.warning("Fase 6.5 case=%d LLM call failed: %s", case.id, str(e)[:100])
        return {"missing": len(missing), "filled": 0, "error": str(e)[:100]}

    # Filtrar <think> y extraer JSON
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        logger.debug("Fase 6.5 case=%d sin JSON en respuesta", case.id)
        return {"missing": len(missing), "filled": 0, "reason": "no_json"}

    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        logger.debug("Fase 6.5 case=%d JSON inválido: %s", case.id, str(e)[:80])
        return {"missing": len(missing), "filled": 0, "reason": "json_parse_error"}

    filled = 0
    for f in missing:
        v = data.get(f)
        if v is None:
            continue
        if isinstance(v, str):
            v = v.strip()
            if not v or v.lower() in ("null", "none", "n/a", "no aplica",
                                       "no especificado", "no se especifica"):
                continue
        if not getattr(case, f, None):  # double-check: NO pisar
            setattr(case, f, str(v)[:500])
            filled += 1

    if filled:
        db.commit()
        logger.info("V6 Fase 6.5 case=%d IA llenó %d/%d campos faltantes",
                    case.id, filled, len(missing))

    return {"missing": len(missing), "filled": filled,
            "tokens": (in_tok or 0) + (out_tok or 0)}


# ============================================================
# v8.1: NUEVO USO DEL LoRA — validador post-extracción
# ============================================================

VALIDATOR_SYSTEM_PROMPT = (
    "Eres un abogado revisor de extracciones automáticas de tutelas. "
    "Recibes campos ya extraídos por regex y un fragmento del expediente. "
    "Tu tarea NO es extraer — es VALIDAR. Marca cada campo como:\n"
    "  • OK: el valor es coherente con el texto\n"
    "  • SOSPECHOSO: posible error (firmante confundido con accionante, "
    "rad23 de otro caso, juzgado/accionante incoherentes con el texto)\n"
    "  • CONTRADICTORIO: el texto dice claramente algo distinto\n"
    "Devuelves SOLO JSON: {\"campo\": \"OK|SOSPECHOSO|CONTRADICTORIO\", \"razon\": \"...\"}"
)


def validate_case_extraction(case, full_text: str, timeout_s: float = 25.0) -> dict:
    """v8.1: pide al LoRA que VALIDE (no extraiga) los campos del case.

    Útil para detectar los bugs identificados en auditoría 2026-05-06:
    firmante≠accionante y mezcla de cases.

    Blindajes contra bloqueo del LLM:
    - Texto truncado a 4000 chars (no 5000) para reducir contexto
    - max_tokens 300 (no 400)
    - Timeout duro: 25s default
    - Fallback heurístico determinista si LLM falla/timeout
    """
    fallback_validation = _heuristic_validation(case, full_text)

    if os.getenv("LLM_LOCAL_PRIMARY", "").lower() != "true":
        return {"skipped": "LLM not enabled", "heuristic": fallback_validation}
    if not full_text or len(full_text.strip()) < 200:
        return {"skipped": "text_insufficient", "heuristic": fallback_validation}

    fields_to_validate = {
        "accionante": case.accionante,
        "rad23": case.radicado_23_digitos,
        "juzgado": case.juzgado,
        "sentido_fallo_1st": case.sentido_fallo_1st,
    }
    user = (
        f"FRAGMENTO DEL EXPEDIENTE:\n{full_text[:4000]}\n\n"
        f"CAMPOS A VALIDAR:\n"
        + "\n".join(f"  {k}: {v}" for k, v in fields_to_validate.items())
        + "\n\nValida cada uno. JSON con clave por campo."
    )
    try:
        from backend.extraction.ai_extractor import _call_local
        from backend.services.llm_mutex import is_up, ensure_llm_up
        # Verificar que LLM está up antes de invocar (anti-bloqueo)
        if not is_up(timeout=2.0):
            if not ensure_llm_up(wait_s=int(timeout_s)):
                logger.warning("LLM no up tras %ss — fallback heurístico", timeout_s)
                return {"llm_unavailable": True, "heuristic": fallback_validation}
        messages = [
            {"role": "system", "content": VALIDATOR_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
        raw, in_tok, out_tok = _call_local(messages, "qwen3-4b-iuris", max_tokens=300)
        return {"raw": raw, "tokens_in": in_tok, "tokens_out": out_tok,
                "heuristic": fallback_validation}
    except TimeoutError:
        logger.warning("validate_case_extraction case=%d timeout %s s — fallback heurístico",
                       getattr(case, "id", "?"), timeout_s)
        return {"timeout": True, "heuristic": fallback_validation}
    except Exception as e:
        logger.warning("validate_case_extraction case=%d error: %s",
                       getattr(case, "id", "?"), str(e)[:80])
        return {"error": str(e)[:120], "heuristic": fallback_validation}


def _strip_accents(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn")


def _heuristic_validation(case, full_text: str) -> dict:
    """Validación determinista (sin LLM): siempre disponible como fallback.

    Aplica las reglas de auditoría 2026-05-06 sin invocar el modelo.
    """
    out = {}
    text_norm = _strip_accents((full_text or "").lower())
    # 1. Accionante: si nombre del case aparece después de "Atentamente," → SOSPECHOSO
    acc = _strip_accents((getattr(case, "accionante", "") or "").strip().lower())
    if acc:
        sospechoso = False
        for sig in ("atentamente", "cordialmente", "cordial saludo"):
            idx = text_norm.find(sig)
            while idx != -1 and idx < len(text_norm) - 50:
                tail = text_norm[idx:idx+400]
                if acc[:15] in tail:
                    if re.search(r"\b(alcaldes[ao]|personer[oa]|secretari[oa]|director[a]?|rector[a]?|gobernador[a]?)\b", tail):
                        out["accionante"] = {"verdict": "SOSPECHOSO",
                                             "razon": "Nombre aparece como firmante con rol institucional (representante, no accionante)"}
                        sospechoso = True
                        break
                idx = text_norm.find(sig, idx+1)
            if sospechoso:
                break
        if not sospechoso:
            out["accionante"] = {"verdict": "OK", "razon": "Sin señales de firmante↔accionante"}

    # 2. Rad23: detecta TANTO con guiones (\d{2}-\d{3}-...) como sin guiones (\d{18,23})
    # Códigos DANE válidos de departamentos colombianos (2 dígitos iniciales del rad23)
    # Filtra falsos positivos como timestamps, IDs internos, etc.
    DANE_DEPT_CODES = {"05","08","11","13","15","17","18","19","20","23","25","27",
                       "41","44","47","50","52","54","63","66","68","70","73","76",
                       "81","85","86","88","91","94","95","97","99"}

    def _has_valid_year(n: str) -> bool:
        # Rad23 contiene año 4 dígitos (2018-2030) en posición ~14 desde el inicio
        for m in re.finditer(r"(20[12]\d)", n):
            yr = int(m.group(1))
            if 2018 <= yr <= 2030:
                return True
        return False

    case_rad = re.sub(r"[^0-9]", "", getattr(case, "radicado_23_digitos", "") or "")
    if case_rad and len(case_rad) >= 18:
        rads_in_text = set()
        # Patrón con guiones/puntos: 22-23 dígitos en grupos
        for m in re.finditer(r"\b\d{2}[-\.\s]?\d{3}[-\.\s]?\d{2,4}[-\.\s]?\d{2,4}[-\.\s]?\d{3}[-\.\s]?\d{4}[-\.\s]?\d{4,5}[-\.\s]?\d{2}\b",
                              full_text or ""):
            n = re.sub(r"[^0-9]", "", m.group(0))
            if (18 <= len(n) <= 23 and n[:2] in DANE_DEPT_CODES
                    and _has_valid_year(n) and n[:20] != case_rad[:20]):
                rads_in_text.add(n[:20])
        # Patrón sin separadores: requiere DANE + año válido + 20-23 dígitos (no 18-19)
        for m in re.finditer(r"\b\d{20,23}\b", full_text or ""):
            n = m.group(0)
            if (n[:2] in DANE_DEPT_CODES and _has_valid_year(n)
                    and n[:20] != case_rad[:20]):
                rads_in_text.add(n[:20])
        if len(rads_in_text) >= 2:
            out["rad23"] = {"verdict": "SOSPECHOSO",
                            "razon": f"{len(rads_in_text)} rad23 ajenos detectados — posible mezcla de cases"}
        elif len(rads_in_text) == 1:
            out["rad23"] = {"verdict": "SOSPECHOSO",
                            "razon": f"rad23 ajeno detectado: {next(iter(rads_in_text))}... (posible doc de otro case)"}
        else:
            out["rad23"] = {"verdict": "OK", "razon": "Solo rad23 propio en texto"}

    return out
