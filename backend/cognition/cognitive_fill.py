"""Cognitive fill: intenta rellenar los ~8 campos semánticos SIN IA externa.

Ejecuta el pipeline cognitivo (zones → actors → cie10 → decision → narrative)
y produce un dict `cognitive_results` con los campos que logró llenar con
razonable confianza. Los que queden vacíos/bajos son los que realmente
necesitan IA externa.

Uso típico en unified.py:
    cog = cognitive_fill(case, all_text, existing_regex_results)
    # fusionar en regex_results antes de decidir si llamar IA
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from backend.agent.extractors.base import ExtractionResult
from backend.cognition.zone_classifier import classify_zones
from backend.cognition.entity_extractor import extract_actors
from backend.cognition.decision_extractor import (
    extract_decision,
    extract_responsable_desacato, extract_decision_incidente,
    extract_forest_impugnacion,
)
from backend.cognition.folder_renamer import clean_accionante, is_likely_real_name
from backend.cognition.narrative_builder import (
    build_asunto, build_pretensiones, build_observaciones, build_derecho_vulnerado,
)

_logger = logging.getLogger("tutelas.cognition")


SEMANTIC_FIELDS_COGNITIVE = {
    "accionante", "accionados", "vinculados",
    "derecho_vulnerado", "asunto", "pretensiones",
    "observaciones", "sentido_fallo_1st", "fecha_fallo_1st",
    "sentido_fallo_2nd", "fecha_fallo_2nd",
    "impugnacion", "quien_impugno",
}


def _to_result(value: str, confidence: int, source: str) -> ExtractionResult:
    return ExtractionResult(
        value=value,
        confidence=confidence,
        source=source,
        method="cognition",
        reasoning=f"Cognición local ({source})",
    )


def _accionante_collides_with_juzgado(name: str, juzgado: str) -> bool:
    """True si el 'accionante' candidato es en realidad un juzgado."""
    if not name:
        return False
    n = name.upper().strip()
    # Palabras-tipo institución judicial en el nombre (siempre rechazo)
    if "JUZGADO" in n or "TRIBUNAL" in n or "CORTE" in n or "MAGISTRADO" in n:
        return True
    # Solapamiento substancial con el campo juzgado ya conocido
    j = (juzgado or "").upper().strip()
    if len(j) >= 10 and (j in n or n in j):
        return True
    return False


# Patrones explícitos que preceden al accionante en encabezados de fallos/tutelas.
# Acepta nombres en MAYÚSCULA TOTAL ("CARMEN BELEN") y Title Case ("Lina Rocío").
# Captura 2-6 palabras tipo nombre.
_NAME_TOKEN = r"[A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ'’.\-]*"
_ACCIONANTE_HEADER_RE = re.compile(
    r"\b(?:Accionante|Demandante|Tutelante|Actor)\s*[:\-]?\s*"
    rf"((?:{_NAME_TOKEN}\s+){{1,5}}{_NAME_TOKEN})",
    re.UNICODE,
)

# FIX 8.4 — patrones narrativos: capturar accionante en prosa cuando no hay
# header explícito. Ej: "acción de tutela promovida por la señora MARTHA ANDREA QUITIAN PINEDA".
# Nota: usar inline (?i:...) en partes case-insensitive para NO afectar
# _NAME_TOKEN (que exige mayúscula inicial estricta).
_NARRATIVE_PATTERNS = [
    re.compile(
        r"(?i:promovida|presentada|interpuesta|instaurada|incoada)\s+(?i:por)\s+"
        r"(?i:la?\s+(?:señora|señor|señor\(a\)|sr|sra)\.?\s+)?"
        rf"((?:{_NAME_TOKEN}\s+){{1,5}}{_NAME_TOKEN})",
        re.UNICODE,
    ),
    re.compile(
        rf"\bYo,?\s+((?:{_NAME_TOKEN}\s+){{1,5}}{_NAME_TOKEN}),?\s+"
        r"(?:identificad[oa]|mayor\s+de\s+edad|en\s+calidad)",
        re.UNICODE,
    ),
    re.compile(
        r"\b(?i:el|la)\s+(?i:accionante)\s+(?i:es\s+)?"
        rf"((?:{_NAME_TOKEN}\s+){{1,5}}{_NAME_TOKEN})",
        re.UNICODE,
    ),
]


def _pick_accionante_from_text(full_text: str, juzgado: str = "") -> str:
    """Fallback FIX 6: extraer accionante cuando actor_extractor falla.

    Estrategia (en orden):
    1. Regex sobre patrones explícitos "Accionante:|Demandante:|Tutelante:|Actor:"
       (más confiable que NER porque captura nombre completo).
    2. spaCy PERSON ranked por aparición temprana + frecuencia.

    Descartando juzgados/tribunales en ambas fases.
    """
    head = full_text[:16000]

    # Paso 1: regex header explícito
    for m in _ACCIONANTE_HEADER_RE.finditer(head):
        candidate = clean_accionante(m.group(1))
        if not candidate or not is_likely_real_name(candidate):
            continue
        if _accionante_collides_with_juzgado(candidate, juzgado):
            continue
        return candidate

    # Paso 1.5: patrones narrativos (FIX 8.4)
    for pat in _NARRATIVE_PATTERNS:
        for m in pat.finditer(head):
            candidate = clean_accionante(m.group(1))
            if not candidate or not is_likely_real_name(candidate):
                continue
            if _accionante_collides_with_juzgado(candidate, juzgado):
                continue
            return candidate

    # Paso 2: NER fallback
    try:
        from backend.cognition.ner_spacy import extract_persons
    except Exception:
        return ""
    persons = extract_persons(head, min_length=8)
    if not persons:
        return ""
    seen: dict[str, dict] = {}
    for p in persons:
        candidate = clean_accionante(p.text)
        if not candidate or not is_likely_real_name(candidate):
            continue
        if _accionante_collides_with_juzgado(candidate, juzgado):
            continue
        rec = seen.setdefault(candidate, {"count": 0, "first_pos": p.start})
        rec["count"] += 1
        rec["first_pos"] = min(rec["first_pos"], p.start)

    if not seen:
        return ""
    ranked = sorted(seen.items(), key=lambda it: (-it[1]["count"], it[1]["first_pos"] * 2))
    return ranked[0][0]


# alias para compat con tests existentes
_pick_accionante_from_ner = _pick_accionante_from_text


# ============================================================
# Guards deterministas (v8.3) — evitan que cognitive_fill llene
# campos contradictorios con la etapa procesal real del expediente.
# Caso típico que motivó esto: docs solo contienen Auto Avoca + escrito
# tutela con jurisprudencia citada largamente — el extractor confundía
# citaciones de la Corte Constitucional como juzgado_2nd, "CONFIRMA"
# de jurisprudencia como sentido_fallo_2nd, etc.
# ============================================================

# Patrones de filename / texto cabecera por etapa procesal
_STAGE_KW_FALLO_1ST = (
    "FALLOPRIMERA", "FALLO PRIMERA", "FALLO 1RA", "FALLO 1ERA",
    "SENTENCIAPRIMERA", "SENTENCIA PRIMERA", "SENTENCIA1RA",
    "PRIMERAINSTANCIA", "PRIMERA INSTANCIA",
)
_STAGE_KW_FALLO_2ND = (
    "FALLO2DA", "FALLO 2DA", "FALLO SEGUNDA", "SENTENCIA2DA", "SENTENCIA 2DA",
    "SEGUNDAINSTANCIA", "SEGUNDA INSTANCIA", "CONFIRMAFALLO", "REVOCAFALLO",
)
_STAGE_KW_IMPUGN = (
    "IMPUGNAC", "IMPUGNA", "CONCEDEIMPUGN", "CONCEDE IMPUGN",
)
_STAGE_KW_INCIDENTE = (
    "INCIDENTE", "DESACATO", "SANCION", "SANCIONA",
)
_STAGE_KW_INICIAL_ONLY = (
    "AUTOADMITE", "AUTO ADMITE", "AUTOAVOCA", "AUTO AVOCA",
    "AVOCATUTELA", "AVOCA TUTELA", "AVOCACONOC", "AVOCA CONOC",
    "TUTELACON", "TUTELA CON", "ESCRITOTUTELA", "ESCRITO TUTELA",
    "DEMANDATUTELA", "DEMANDA TUTELA",
)


def _detect_stage_flags(documents: list[dict] | None) -> dict:
    """Detecta etapa procesal a partir de filenames + doc_types.

    Returns flags estrictos:
      has_fallo_1st, has_impugnacion, has_fallo_2nd, has_incidente,
      is_inicial_only (todos los docs son auto admisorio / tutela escrito).
    """
    flags = {
        "has_fallo_1st": False, "has_impugnacion": False,
        "has_fallo_2nd": False, "has_incidente": False,
        "is_inicial_only": True,
    }
    if not documents:
        flags["is_inicial_only"] = False  # sin docs no podemos afirmar nada
        return flags

    has_any_non_inicial = False
    for d in documents:
        fn_up = (d.get("filename") or "").upper().replace("_", " ").replace("-", " ")
        doc_type = (d.get("doc_type") or "").upper()

        is_fallo_2nd = any(kw in fn_up for kw in _STAGE_KW_FALLO_2ND)
        is_fallo_1st = (
            any(kw in fn_up for kw in _STAGE_KW_FALLO_1ST)
            or (doc_type == "PDF_SENTENCIA" and not is_fallo_2nd)
        )
        is_impugn = any(kw in fn_up for kw in _STAGE_KW_IMPUGN)
        is_incid = any(kw in fn_up for kw in _STAGE_KW_INCIDENTE) or doc_type == "INCIDENTE"

        if is_fallo_2nd:
            flags["has_fallo_2nd"] = True
            has_any_non_inicial = True
        if is_fallo_1st:
            flags["has_fallo_1st"] = True
            has_any_non_inicial = True
        if is_impugn:
            flags["has_impugnacion"] = True
            has_any_non_inicial = True
        if is_incid:
            flags["has_incidente"] = True
            has_any_non_inicial = True

    flags["is_inicial_only"] = not has_any_non_inicial
    return flags


# Patrones de citación de jurisprudencia (señal de "marco teórico")
_JURISPRUDENCE_PATTERNS = [
    re.compile(r"\bAuto\s+\d{1,4}\s+de\s+20?\d{2}\b", re.IGNORECASE),
    re.compile(r"\bSentencia\s+[TCSU]+-?\d+\b", re.IGNORECASE),
    re.compile(r"\bM\.\s*P\.\s*[A-ZÁÉÍÓÚÑ]"),  # "M.P. Carlos..."
    re.compile(r"\bCfr\.\s*", re.IGNORECASE),
    re.compile(r"\bnegrillas?\s+fuera\s+del\s+texto\b", re.IGNORECASE),
]


def _heavy_jurisprudence_citations(text: str, threshold: int = 5) -> int:
    """Cuenta citaciones de jurisprudencia. >=threshold = doc cita marco teórico."""
    if not text:
        return 0
    sample = text[:10000]
    count = 0
    for pat in _JURISPRUDENCE_PATTERNS:
        count += len(pat.findall(sample))
    return count


_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def _date_to_tuple(d: str) -> tuple | None:
    """Convierte 'DD/MM/YYYY' → (y, m, d) tuple comparable. None si inválida."""
    if not d:
        return None
    m = _DATE_RE.match(d.strip())
    if not m:
        return None
    return (int(m.group(3)), int(m.group(2)), int(m.group(1)))


def _is_after_or_equal(candidate: str, reference: str) -> bool:
    """True si candidate >= reference. Ambas DD/MM/YYYY. Si alguna inválida → True (no rechaza)."""
    a = _date_to_tuple(candidate)
    b = _date_to_tuple(reference)
    if not a or not b:
        return True
    return a >= b


# Códigos de juzgado en rad23 que SÍ pueden tener "Corte Suprema/Constitucional" como 2nd
_HIGH_COURT_RAD_SEGMENTS = {"4006", "4007"}  # Tribunales superiores


def _is_high_court_2nd_legitimate(juzgado_2nd: str, rad23: str) -> bool:
    """True si 'Corte Suprema/Constitucional' es legítimo como juzgado_2nd
    (caso de tutelas en grado de revisión / casación). Por defecto NO."""
    if not juzgado_2nd:
        return True
    j_up = juzgado_2nd.upper()
    if "CORTE SUPREMA" not in j_up and "CORTE CONSTITUCIONAL" not in j_up:
        return True  # no es alta corte → no aplica este check
    digits = re.sub(r"\D", "", rad23 or "")
    if len(digits) < 12:
        return False
    seg_5_9 = digits[5:9]
    return seg_5_9 in _HIGH_COURT_RAD_SEGMENTS


def cognitive_fill(
    case_meta: dict[str, Any],
    full_text: str,
    existing: dict[str, ExtractionResult] | None = None,
    documents: list[dict] | None = None,
) -> dict[str, ExtractionResult]:
    """Aplica el pipeline cognitivo al texto completo del caso.

    Args:
        case_meta: dict con fields ya extraídos por regex/DB
                   (fecha_ingreso, radicado_23_digitos, radicado_forest,
                    abogado_responsable, incidente, etc.)
        full_text: concatenación de textos de documentos del caso.
        existing: resultados regex previos (para no sobrescribir si
                  confianza > 80).

    Returns:
        dict campo_lowercase → ExtractionResult (solo los que llenó).
    """
    if not full_text:
        return {}
    existing = existing or {}

    zones = classify_zones(full_text)
    actors = extract_actors(full_text, zones)
    decision = extract_decision(full_text, zones)

    # v8.3 — Detección de etapa procesal por filenames + doc_types.
    # Bloquea extracción de campos que NO pueden existir en la etapa actual
    # (ej: caso solo con AUTO_AVOCA no puede tener fallo, ni 2da, ni impugnación).
    stage = _detect_stage_flags(documents)
    fecha_ingreso_ref = case_meta.get("fecha_ingreso", "") or ""
    rad23_ref = case_meta.get("radicado_23_digitos", "") or ""
    # Conteo de citas de jurisprudencia para gating de pretensiones/observaciones
    jurisprudence_count = _heavy_jurisprudence_citations(full_text)
    heavy_jurisprudence = jurisprudence_count >= 5

    out: dict[str, ExtractionResult] = {}

    def _maybe_set(field: str, value: str, confidence: int, source: str):
        if not value:
            return
        # Respetar regex con alta confianza
        prev = existing.get(field)
        if prev and prev.confidence >= 80:
            return
        out[field] = _to_result(value, confidence, source)

    # Accionante (FIX 6 — validación + fallback NER):
    # 1. Tomar el del actor_extractor, sanitizar con clean_accionante,
    #    descartar si parece juzgado o no es nombre real.
    # 2. Si falla, usar spaCy NER PERSON ranked por posición/frecuencia.
    juzgado_known = case_meta.get("juzgado", "")
    accionante_candidate = ""
    if actors.accionantes:
        raw = actors.accionantes[0].name
        cleaned = clean_accionante(raw)
        if (cleaned and is_likely_real_name(cleaned)
                and not _accionante_collides_with_juzgado(cleaned, juzgado_known)):
            accionante_candidate = cleaned

    if not accionante_candidate:
        text_pick = _pick_accionante_from_text(full_text, juzgado_known)
        if text_pick:
            accionante_candidate = text_pick
            _logger.info("cognitive_fill case=%s accionante via text fallback: %r",
                         case_meta.get("id"), text_pick)

    if accionante_candidate:
        _maybe_set("accionante", accionante_candidate, 75,
                   "cognition/actor_extractor" if (actors.accionantes and accionante_candidate == clean_accionante(actors.accionantes[0].name))
                   else "cognition/text_fallback")

    # Accionados (lista separada por " - ")
    if actors.accionados:
        val = " - ".join(a.name for a in actors.accionados[:5])
        _maybe_set("accionados", val, 70, "cognition/actor_extractor")

    # Vinculados
    if actors.vinculados:
        val = " - ".join(a.name for a in actors.vinculados[:6])
        _maybe_set("vinculados", val, 70, "cognition/actor_extractor")

    # Derechos vulnerados (combinando existing)
    existing_dv = existing.get("derecho_vulnerado")
    prev_dv = existing_dv.value if existing_dv else ""
    dv = build_derecho_vulnerado(full_text, prev_dv)
    if dv:
        _maybe_set("derecho_vulnerado", dv, 78, "cognition/cie10_keyword")

    # Decisión primera instancia — gating por etapa procesal (v8.3)
    if decision.sentido and stage["has_fallo_1st"]:
        _maybe_set("sentido_fallo_1st", decision.sentido, 80, "cognition/decision_extractor")
    elif decision.sentido and not stage["has_fallo_1st"]:
        _logger.info("cognitive_fill case=%s STAGE_GUARD: sentido_fallo_1st rechazado (etapa solo inicial, no hay doc de fallo)", case_meta.get("id"))

    if decision.fecha and stage["has_fallo_1st"]:
        # Validar fecha_fallo >= fecha_ingreso (no se puede fallar antes de ingresar)
        if _is_after_or_equal(decision.fecha, fecha_ingreso_ref):
            _maybe_set("fecha_fallo_1st", decision.fecha, 80, "cognition/decision_extractor")
        else:
            _logger.info("cognitive_fill case=%s STAGE_GUARD: fecha_fallo_1st=%s rechazada (< fecha_ingreso=%s)",
                         case_meta.get("id"), decision.fecha, fecha_ingreso_ref)

    # Segunda instancia — solo si hay doc de fallo 2nd O de impugnación que ya fue resuelta
    if decision.segunda_instancia and stage["has_fallo_2nd"]:
        _maybe_set("sentido_fallo_2nd", decision.segunda_instancia, 75, "cognition/decision_extractor")
    elif decision.segunda_instancia:
        _logger.info("cognitive_fill case=%s STAGE_GUARD: sentido_fallo_2nd rechazado (no hay doc fallo 2da)", case_meta.get("id"))

    if decision.fecha_segunda and stage["has_fallo_2nd"]:
        if _is_after_or_equal(decision.fecha_segunda, fecha_ingreso_ref):
            _maybe_set("fecha_fallo_2nd", decision.fecha_segunda, 75, "cognition/decision_extractor")
        else:
            _logger.info("cognitive_fill case=%s STAGE_GUARD: fecha_fallo_2nd=%s rechazada (< fecha_ingreso)",
                         case_meta.get("id"), decision.fecha_segunda)

    # Impugnación — solo si hay doc de impugnación O de fallo 2nd
    if decision.impugnacion and (stage["has_impugnacion"] or stage["has_fallo_2nd"]):
        _maybe_set("impugnacion", decision.impugnacion, 75, "cognition/decision_extractor")
    elif stage["is_inicial_only"]:
        # Solo docs iniciales (auto avoca + escrito) → forzar impugnacion=NO
        _maybe_set("impugnacion", "NO", 70, "cognition/stage_inicial_only")
    elif decision.impugnacion:
        _logger.info("cognitive_fill case=%s STAGE_GUARD: impugnacion=%s rechazada (sin doc de impugnación ni fallo 2nd)",
                     case_meta.get("id"), decision.impugnacion)

    if decision.quien_impugno and (stage["has_impugnacion"] or stage["has_fallo_2nd"]):
        _maybe_set("quien_impugno", decision.quien_impugno, 70, "cognition/decision_extractor")

    # v9.4.5: extractores específicos campos <50% cobertura
    # Iterar documentos: cada uno puede aportar un dato distinto
    for d in documents or []:
        dtext = d.get("text", "") or d.get("full_text", "")
        if not dtext:
            continue
        fname = d.get("filename", "")
        # FOREST de impugnación: solo en docs de 2da instancia
        forest_2nd = extract_forest_impugnacion(dtext, fname)
        if forest_2nd:
            _maybe_set("forest_impugnacion", forest_2nd, 80,
                       "cognition/decision_extractor")
        # Responsable desacato: solo en docs de incidente
        if "incident" in fname.lower() or "desacato" in fname.lower() or \
                d.get("doc_type") == "INCIDENTE":
            resp = extract_responsable_desacato(dtext)
            if resp:
                _maybe_set("responsable_desacato", resp, 70,
                           "cognition/decision_extractor")
            decis = extract_decision_incidente(dtext)
            if decis:
                _maybe_set("decision_incidente", decis, 70,
                           "cognition/decision_extractor")

    # Campos narrativos (asunto / pretensiones / observaciones)
    # v8.3: si el caso ya tiene derecho_vulnerado en DB, usarlo para coherencia
    # narrativa. Evita que la observación diga "alegó educación" cuando la DB
    # tiene "PETICION y SEGURIDAD SOCIAL".
    persisted_dv = (case_meta.get("derecho_vulnerado") or "").strip()
    dv_for_narrative = persisted_dv or dv or prev_dv
    asunto = build_asunto(actors, dv_for_narrative, full_text)
    pret = build_pretensiones(actors, dv_for_narrative, full_text, asunto)

    _maybe_set("asunto", asunto, 65, "cognition/narrative_builder")
    # Guard v8.3: si el texto del expediente cita ≥5 jurisprudencias
    # (Auto NNN de YYYY, Sentencia T-/SU-, M.P., Cfr.), las pretensiones
    # extraídas suelen ser fragmentos de marco teórico citado por el juez,
    # no peticiones reales del accionante. Mejor dejar vacío que llenar mal.
    if pret and heavy_jurisprudence:
        _logger.info("cognitive_fill case=%s STAGE_GUARD: pretensiones rechazadas (texto con %d citas de jurisprudencia, probable contaminación)",
                     case_meta.get("id"), jurisprudence_count)
    else:
        _maybe_set("pretensiones", pret, 65, "cognition/narrative_builder")

    obs_meta = {
        "fecha_ingreso": case_meta.get("fecha_ingreso", ""),
        "radicado_23_digitos": case_meta.get("radicado_23_digitos", ""),
        "radicado_forest": case_meta.get("radicado_forest", ""),
        "abogado_responsable": case_meta.get("abogado_responsable", ""),
        "incidente": case_meta.get("incidente", ""),
    }

    # v8.3 Guard: filtrar `decision` según etapa procesal antes de narrar.
    # Sin esto, build_observaciones repite "Mediante fallo... CONCEDE... 2da
    # instancia CONFIRMA..." aunque los gates anteriores hayan rechazado
    # persistir esos campos.
    import dataclasses as _dc
    decision_filtered = _dc.replace(
        decision,
        sentido=decision.sentido if stage["has_fallo_1st"] else "",
        fecha=decision.fecha if (stage["has_fallo_1st"] and _is_after_or_equal(decision.fecha, fecha_ingreso_ref)) else "",
        segunda_instancia=decision.segunda_instancia if stage["has_fallo_2nd"] else "",
        fecha_segunda=decision.fecha_segunda if (stage["has_fallo_2nd"] and _is_after_or_equal(decision.fecha_segunda, fecha_ingreso_ref)) else "",
        impugnacion=decision.impugnacion if (stage["has_impugnacion"] or stage["has_fallo_2nd"]) else ("NO" if stage["is_inicial_only"] else ""),
        quien_impugno=decision.quien_impugno if (stage["has_impugnacion"] or stage["has_fallo_2nd"]) else "",
    )
    obs = build_observaciones(actors, dv_for_narrative, decision_filtered, obs_meta,
                              events=None, documents=documents)
    _maybe_set("observaciones", obs, 60, "cognition/narrative_builder")

    _logger.info(
        "cognitive_fill case=%s filled=%d fields: %s",
        case_meta.get("id"), len(out), sorted(out.keys()),
    )
    return out
