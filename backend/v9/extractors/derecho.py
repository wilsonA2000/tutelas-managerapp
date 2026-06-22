"""Dominio DERECHO del motor v9 — extraído de field_extractor.py (de-sobreingeniería F6).

Clasifica los derechos fundamentales invocados (DERECHO_VOCAB) por regex anclado a la
región de derechos + LLM de respaldo. field_extractor.py re-exporta los símbolos públicos
(DERECHO_VOCAB, _ground_speculative_derechos, extract_derecho_vulnerado_for_case) para el
contrato externo (chat.py, v9_test_db, tests, pipeline).
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

from sqlalchemy.orm import Session

from backend.database.models import Case, Document
from backend.v9.extractors._shared import _read_doc_text, _fold, _best_claim_text

logger = logging.getLogger("tutelas.v9.extractors.derecho")


DERECHO_VOCAB: tuple[str, ...] = (
    "EDUCACION",
    "SALUD",
    "PETICION",
    "DEBIDO_PROCESO",
    "VIDA",
    "SEGURIDAD_SOCIAL",
    "MINIMO_VITAL",
    "TRABAJO",
    "IGUALDAD",
    "INTIMIDAD",
    "HABEAS_DATA",
    "OTRO",
)
_DERECHO_PRIORITY = {tag: i for i, tag in enumerate(DERECHO_VOCAB)}
DERECHO_SIN_DETERMINAR = "SIN_DETERMINAR"

# Keyword (sobre texto sin tildes, minúsculas) → tag canónico. Multi-palabra
# primero para que "seguridad social" gane antes que "social" suelto, etc.
_DERECHO_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("seguridad social", "SEGURIDAD_SOCIAL"),
    ("minimo vital", "MINIMO_VITAL"),
    ("debido proceso", "DEBIDO_PROCESO"),
    ("habeas data", "HABEAS_DATA"),
    ("proteccion de datos", "HABEAS_DATA"),
    ("datos personales", "HABEAS_DATA"),
    ("transporte escolar", "EDUCACION"),
    ("educac", "EDUCACION"),            # educación / educacion / educativa / educativo
    ("ensenanza", "EDUCACION"),
    ("escolar", "EDUCACION"),
    ("salud", "SALUD"),
    ("peticion", "PETICION"),
    ("vida digna", "VIDA"),
    ("dignidad humana", "VIDA"),
    ("integridad personal", "VIDA"),
    ("integridad fisica", "VIDA"),
    (" vida", "VIDA"),                  # con espacio: evita "convivencia", etc.
    ("trabajo", "TRABAJO"),
    ("igualdad", "IGUALDAD"),
    ("no discriminacion", "IGUALDAD"),
    ("discriminacion", "IGUALDAD"),
    ("intimidad", "INTIMIDAD"),
    ("buen nombre", "INTIMIDAD"),
)

# Derechos "raros" que el LLM 4B tiende a ALUCINAR (sobre-etiqueta sistemática
# medida 2026-06-02: ~50% de los cambios de derecho del 4B agregaban estos sin
# respaldo). Solo se conservan si la demanda los EVIDENCIA textualmente; los "core"
# (EDUCACION/SALUD/VIDA/TRABAJO/PETICION/DEBIDO_PROCESO/IGUALDAD) pasan sin filtro.
# La evidencia REUSA `_DERECHO_KEYWORDS` (+ sinónimos inequívocos).
_SPECULATIVE_DERECHOS = frozenset({"INTIMIDAD", "HABEAS_DATA", "MINIMO_VITAL", "SEGURIDAD_SOCIAL"})
_SPEC_EVIDENCE: dict[str, tuple[str, ...]] = {
    tag: tuple(kw for kw, t in _DERECHO_KEYWORDS if t == tag)
    for tag in _SPECULATIVE_DERECHOS
}
_SPEC_EVIDENCE["SEGURIDAD_SOCIAL"] += ("pension", "pensional")
_SPEC_EVIDENCE["MINIMO_VITAL"] += ("subsistencia",)


def _ground_speculative_derechos(tags: list[str], text: str) -> list[str]:
    """Descarta los derechos especulativos que el LLM propuso pero que la demanda
    NO respalda textualmente (anti-alucinación del 4B). Determinista. Los tags core
    pasan intactos."""
    folded = _fold(text or "")
    out: list[str] = []
    for t in tags:
        if t in _SPECULATIVE_DERECHOS and not any(kw in folded for kw in _SPEC_EVIDENCE.get(t, ())):
            continue  # tag especulativo sin evidencia → descartar (alucinación)
        out.append(t)
    return out

# Marcadores que CIERRAN la enumeración de derechos: lo que sigue ya no son
# derechos del reclamo, sino quién los vulneró / a quién pertenecen / etc.
# Se busca sobre el texto ORIGINAL de la región (con tildes, case-insensitive).
_DERECHO_REGION_END = re.compile(
    r"(?i)\b(?:"
    r"los?\s+cuales?|las?\s+cuales?|"
    r"que\s+(?:considera|estima|cree|denomina|fueron|han\s+sido|estim[oó]|se\b|le\b)|"
    r"toda\s+vez|por\s+cuanto|presuntamente|supuestamente|en\s+raz[óo]n|debido\s+a|"
    r"como\s+consecuencia|con\s+ocasi[óo]n|a\s+causa|"
    r"por\s+(?:la|el|las|los)\s+(?:acci[óo]n|omisi[óo]n|negativa|falta|conducta|actuaci[óo]n|decisi[óo]n)|"
    r"por\s+parte\s+de|vulnerad[oa]s?\s+por|amenazad[oa]s?\s+por|"
    r"accionant|accionad|demandant|demandad|"
    r"de\s+(?:la|el|su|mi|sus|mis)\s+(?:menor|ni[ñn][oa]s?|hij[oa]s?|agenciad[oa]s?|representad[oa]s?|poderdant|prohijad[oa])|"
    r"contra\s+l[oa]s?\b|en\s+contra"
    r")\b"
)
# Nombres de entidades que contienen "educación" pero NO son el derecho: la
# Secretaría / Ministerio de Educación es la ACCIONADA, no el derecho vulnerado.
_DERECHO_ENTITY_NOISE = (
    "secretaria de educacion", "ministerio de educacion", "subsecretaria de educacion",
    "departamental de educacion", "departamento de educacion", "secretaria de educa",
    "direccion de educacion", "viceministerio de educacion",
)

# Ancla: el reclamo de la tutela se enuncia como "derechos fundamentales a la X,
# Y y Z" (a veces "constitucionales"). Capturamos ~160 chars de "región" tras el
# conector para escanear sólo ahí. El conector (a la / al / de) es opcional, pero
# si la región empieza con boilerplate jurisprudencial ("...cuando no se dispone
# de otro medio...", "...del actor", "...amenazados y vulnerados. En tal
# sentido...") la descartamos: ahí "derechos fundamentales" se usa en abstracto,
# no es la enumeración del caso.
_DERECHO_ANCHOR = re.compile(
    r"(?i)derechos?\s+(?:fundamental(?:es)?|constitucional(?:es)?(?:\s+y\s+legal(?:es)?)?)\s*"
    r"(?:(?:presuntamente\s+|supuestamente\s+)?(?:vulnerad[oa]s?|amenazad[oa]s?)?\s*)?"
    r"(?:a\s+l[oa]s?\s+|al\s+|a\s+las\s+|de\s+l[oa]s?\s+|de\s+|,\s*)?"
    r"(.{0,180})",
    re.DOTALL,
)

# Sólo escaneamos el encabezado del doc (parte resolutiva del auto / antecedentes
# de la sentencia / petitorio de la demanda). Más allá vienen las "CONSIDERACIONES"
# con jurisprudencia que menciona derechos en abstracto → ruido (mitigado además
# por `_DERECHO_REGION_STOPSTART` y `_DERECHO_REGION_END`).
_DERECHO_SCAN_CHARS = 8000
# Si la región (lo que sigue al conector) ARRANCA con una de estas frases, NO es
# la enumeración del reclamo sino texto considerativo / jurisprudencial.
_DERECHO_REGION_STOPSTART = re.compile(
    r"(?i)^\s*(?:"
    r"cuando\b|respecto\b|consagrad|previst|son\b|como\b|que\b|y\b|cuy[oa]s?\b|"
    r"seg[uú]n\b|tales?\b|los?\s+cuales?\b|las?\s+cuales?\b|del?\s+actor|"
    r"del?\s+accionante|del?\s+demandante|del?\s+funcionario|del?\s+servidor|"
    r"del?\s+peticionari|personas?\b|ciudadan|colombian|usuari|asociad[oa]s|"
    r"en\s+(?:tal|el\s+presente|este|aras|virtud)|"
    r"para\b|presunta|amenazad[oa]s?\b|vulnerad[oa]s?\s+(?:por|en\b|de\b|;|\.)|"
    r"invocad|no\s+se\s+dispone|frente\s+a|sin\s+que|al\s+ser\b|reconocid"
    r")"
)


# _fold → extractors/_shared.py (importado arriba)


def _tags_in_region(region: str) -> list[str]:
    """Devuelve los tags canónicos presentes en una 'región' de texto, dedup.

    Antes de buscar keywords: (1) trunca la región en el cierre de la enumeración
    (`_DERECHO_REGION_END`), (2) trunca en el primer fin de oración ('. ' + may.),
    (3) borra nombres de entidades que contienen 'educación' (la Secretaría es la
    accionada, no el derecho).
    """
    m = _DERECHO_REGION_END.search(region)
    if m:
        region = region[:m.start()]
    m = re.search(r"\.\s+[A-ZÁÉÍÓÚÑ]", region)
    if m:
        region = region[:m.start()]
    folded = _fold(region)
    for noise in _DERECHO_ENTITY_NOISE:
        folded = folded.replace(noise, " ")
    found: list[str] = []
    for kw, tag in _DERECHO_KEYWORDS:
        if kw in folded and tag not in found:
            found.append(tag)
    return found


def _extract_derechos_from_text(text: str) -> list[str]:
    """Escanea el ENCABEZADO del doc buscando enumeraciones de derechos tras el
    ancla y devuelve la lista de tags canónicos (dedup, orden de prioridad).

    Descarta las regiones que arrancan con boilerplate (`_DERECHO_REGION_STOPSTART`).
    No corta en la primera región: una enumeración real puede partirse en varias
    (p.ej. el auto repite el reclamo en su parte resolutiva), pero al limitar el
    escaneo a `_DERECHO_SCAN_CHARS` se evita la zona de "CONSIDERACIONES".
    """
    if not text:
        return []
    head = text[:_DERECHO_SCAN_CHARS]
    found: list[str] = []
    for m in _DERECHO_ANCHOR.finditer(head):
        region = m.group(1)
        if _DERECHO_REGION_STOPSTART.search(region):
            continue
        for tag in _tags_in_region(region):
            if tag not in found:
                found.append(tag)
    found.sort(key=lambda t: _DERECHO_PRIORITY.get(t, 999))
    return found


def _format_derechos(tags: list[str]) -> Optional[str]:
    if not tags:
        return None
    return " - ".join(tags)


# Doctypes donde el derecho invocado aparece con más fiabilidad (prioridad)
_DERECHO_DOC_PRIORITY = ["AUTO_ADMISORIO", "DEMANDA_TUTELA", "SENTENCIA_1RA", "SENTENCIA_2DA"]


def _llm_classify_derecho(text: str) -> Optional[str]:
    """Fallback LLM (Qwen3-4B local): clasifica el/los derecho(s) invocado(s)
    al vocabulario controlado. Devuelve "A - B" o None si falla / texto pobre.

    Respeta `V9_DISABLE_LLM=true`. Si llama-server no responde, devuelve None
    silenciosamente (NO rompe la extracción).
    """
    if os.getenv("V9_DISABLE_LLM", "false").lower() == "true":
        return None
    text = (text or "").strip()
    if len(text) < 150:
        return None
    try:
        from backend.extraction.ai_extractor import _call_local
    except ImportError as e:
        logger.warning("ai_extractor no importable: %s", e)
        return None

    vocab = ", ".join(t for t in DERECHO_VOCAB)
    prompt = (
        "/no_think\n"
        "Eres un clasificador jurídico. Lee el texto de una acción de tutela y di "
        "qué derecho(s) fundamental(es) se invocan como vulnerados.\n"
        f"Responde ÚNICAMENTE con uno o varios de estos tags, separados por ' - ': {vocab}.\n"
        "Usa 'OTRO' sólo si el derecho real no está en la lista. Si no puedes determinarlo, "
        "responde exactamente 'SIN_DETERMINAR'. No expliques nada más.\n\n"
        f"Texto:\n{text[:int(os.getenv('V9_LLM_FIELD_CAP', '150000'))]}"
    )
    msgs = [
        {"role": "system", "content": "Clasificas derechos fundamentales. Respondes sólo con los tags pedidos."},
        {"role": "user", "content": prompt},
    ]
    try:
        raw, _, _ = _call_local(msgs, "qwen3-4b-iuris", max_tokens=64)
    except Exception as e:
        logger.warning("LLM derecho_vulnerado falló: %s", str(e)[:200])
        return None
    if not raw:
        return None
    raw_fold = _fold(raw)
    # 1. ¿el modelo dijo explícitamente SIN_DETERMINAR? respétalo
    if re.search(r"\bsin[ _]determinar\b", raw_fold) and not re.search(
        r"\b(?:educac|salud|peticion|debido|vida|trabajo|igualdad|intimidad|habeas)\b", raw_fold
    ):
        return DERECHO_SIN_DETERMINAR
    # 2. Buscar tags del vocab por nombre (tolerando ' ' por '_') o por keyword del dominio
    tags: list[str] = []
    for tag in DERECHO_VOCAB:
        tag_pat = re.escape(tag).replace(r"\_", r"[ _]").lower()
        if re.search(rf"\b{tag_pat}\b", raw_fold) and tag not in tags:
            tags.append(tag)
    # 3. fallback: si el modelo respondió en prosa, mapear keywords del dominio
    if not tags:
        tags = _tags_in_region(" " + raw + " ")
    if not tags:
        return None
    # Grounding: descartar derechos especulativos que el LLM alucinó sin evidencia.
    tags = _ground_speculative_derechos(tags, text)
    if not tags:
        return None
    if "OTRO" in tags and len(tags) > 1:
        tags = [t for t in tags if t != "OTRO"]  # OTRO sólo si es lo único
    tags.sort(key=lambda t: _DERECHO_PRIORITY.get(t, 999))
    return " - ".join(tags)


# ============================================================
# Selección de doc fuente para campos SEMÁNTICOS (asunto / derecho)
# ============================================================
# El asunto y el derecho describen el RECLAMO ORIGINAL del accionante. Si se lee
# el doc equivocado —un auto de desacato, un informe de cumplimiento, o un PDF
# mal rotulado como DEMANDA_TUTELA que en realidad es un AutoNoSanciona— el
# clasificador (regex o LLM) describe la ETAPA PROCESAL en vez del reclamo.
# `_best_claim_text` elige el doc que mejor refleja el reclamo original.
# _CLAIM_DEM_MARK / _CLAIM_NOT_DEMANDA / _best_claim_text → extractors/_shared.py
# (compartidos por derecho/asunto/pipeline; importados+re-exportados arriba).


def extract_derecho_vulnerado_for_case(
    db: Session, case: Case, *, use_llm: bool = True
) -> tuple[Optional[str], str]:
    """Extrae derecho_vulnerado del case. Campo SEMÁNTICO → autoridad = LLM.

    Estrategia (2026-06, LLM-first):
      1. Si `use_llm` y el LLM local está disponible: lee la demanda real
         (`_best_claim_text`, que excluye autos/desacato/informes) y clasifica
         al vocabulario controlado. ESTA es la autoridad — el regex de keywords
         sobre-aplica EDUCACION (lo dispara el nombre del accionado
         "Secretaría de Educación" o una mención de paso) y no distingue el
         derecho del ESTUDIANTE del reclamo LABORAL del docente.
      2. FALLBACK regex (determinista; airgapped / `V9_DISABLE_LLM=true` / el LLM
         no concluyó): tags por DOCTYPE en orden de prioridad; el primero con
         señal gana.
      3. Si todo falla: ("SIN_DETERMINAR", "default").

    Returns: (valor, fuente)  — fuente ∈ {"llm", "regex", "default"}.
    """
    # 1. LLM-first (autoridad del campo semántico)
    if use_llm and os.getenv("V9_DISABLE_LLM", "false").lower() != "true":
        claim_text, _is_real = _best_claim_text(db, case)
        if claim_text and len(claim_text) >= 150:
            val = _llm_classify_derecho(claim_text)
            # "OTRO" pelado = el LLM no identificó un derecho del vocab → inconcluso;
            # preferir el regex (no regresar un EDUCACION correcto a OTRO).
            if val and val not in (DERECHO_SIN_DETERMINAR, "OTRO"):
                return val, "llm"

    # 2. FALLBACK regex por doctype, en orden de prioridad — el primero con señal gana
    docs_by_type: dict[str, list[Document]] = {}
    for d in db.query(Document).filter(Document.case_id == case.id).all():
        docs_by_type.setdefault(d.doc_type or "OTRO", []).append(d)

    ordered_types = _DERECHO_DOC_PRIORITY + [t for t in docs_by_type if t not in _DERECHO_DOC_PRIORITY]
    for dt in ordered_types:
        found: list[str] = []
        for d in docs_by_type.get(dt, []):
            text = d.extracted_text if d.extracted_text else _read_doc_text(d)
            if not text or len(text) < 200:
                continue
            for tag in _extract_derechos_from_text(text):
                if tag not in found:
                    found.append(tag)
        if found:
            found.sort(key=lambda t: _DERECHO_PRIORITY.get(t, 999))
            return _format_derechos(found), "regex"

    # 3. Default
    return DERECHO_SIN_DETERMINAR, "default"


