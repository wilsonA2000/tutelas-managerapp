"""Capa 4.6 v9.0 — Enriquecimiento semántico con Qwen 7B local.

Cuando la cadena regex → kNN consensus deja un campo vacío, este módulo
invoca a Qwen para extraer el valor desde el texto del caso.

Targets con prompts específicos:
  - responsable_desacato  : nombre del responsable del incidente
  - decision_incidente    : síntesis de decisión judicial sobre el incidente
  - quien_impugno         : ACCIONANTE | ACCIONADO | MINISTERIO_PUBLICO
  - juzgado_2nd           : nombre del juzgado/tribunal segunda instancia
  - categoria_tematica    : clasificación temática corta

Diseño:
  - Llama directo a vLLM puerto 8120 (Qwen) sin tools (extracción pura)
  - response_format JSON para parseo confiable
  - Acepta `null` como valor válido (no inventar)
  - Persiste en DB sólo si el valor es no-null y diferente al actual
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

from backend.cognition.agent.lifecycle import lifecycle
from backend.cognition.legal_schema import (
    derivar_juzgado_segunda, clasificar_sed_tematica,
)

logger = logging.getLogger("tutelas.cognition.semantic_enricher")

QWEN_URL = "http://localhost:8120/v1/chat/completions"
QWEN_MODEL = "qwen2.5-7b-instruct-awq"

def _resolve_db_path() -> str:
    try:
        from backend.core.settings import settings
        return str(settings.db_path)
    except Exception:
        return "data/tutelas.db"

DB_PATH = _resolve_db_path()

# Targets soportados ────────────────────────────────────────────────
# Cada target especifica:
#   - mode: la operación cognitiva (cómo razonar)
#   - source_documents: dónde encontrar el dato (qué documento)
#   - description: cómo extraer/formatear

# Modos cognitivos (formaliza ingeniería inversa de razonamiento jurídico)
MODE_VERBATIM = "VERBATIM"      # transcribir literal sin parafrasear
MODE_PARAPHRASE = "PARAPHRASE"  # resumir captando esencia
MODE_CLASSIFY = "CLASSIFY"      # elegir UNA opción del enum
MODE_REASON = "REASON"          # razonar y emitir 1 frase concreta


@dataclass
class EnrichTarget:
    column: str
    description: str
    output_schema: str
    mode: str = MODE_REASON                      # operación cognitiva
    source_documents: tuple[str, ...] = ()       # documentos donde buscar
    enum_values: list[str] | None = None
    only_if_field: str | None = None
    only_if_value: str | None = None
    max_length: int = 200


TARGETS: dict[str, EnrichTarget] = {
    "responsable_desacato": EnrichTarget(
        column="responsable_desacato",
        mode=MODE_REASON,
        source_documents=("escrito_incidente_desacato", "auto_apertura_incidente"),
        description=(
            "Nombre completo del FUNCIONARIO PÚBLICO responsable del desacato. "
            "Suele ser alcalde, secretario, gerente o jefe de oficina (NO 'PARTE "
            "INCIDENTADA' ni roles genéricos). Buscar específicamente en el escrito "
            "de incidente de desacato y el auto que lo avoca. "
            "Si no aparece nombre claro, responde null."
        ),
        output_schema='{"value": "string|null", "evidence": "fragmento corto"}',
        only_if_field="incidente", only_if_value="SI",
        max_length=120,
    ),
    "decision_incidente": EnrichTarget(
        column="decision_incidente",
        mode=MODE_REASON,
        source_documents=("decision_judicial_incidente", "auto_sancion"),
        description=(
            "Síntesis (máximo 1 frase) de la decisión del juez sobre el incidente. "
            "Ejemplos válidos: 'Sanciona con 5 días de arresto', 'Archiva por "
            "cumplimiento', 'Requiere informe adicional', 'Compulsa copias'. "
            "Si la decisión no aparece, responde null. NO inventes."
        ),
        output_schema='{"value": "string|null", "evidence": "fragmento corto"}',
        only_if_field="incidente", only_if_value="SI",
        max_length=300,
    ),
    "quien_impugno": EnrichTarget(
        column="quien_impugno",
        mode=MODE_CLASSIFY,
        source_documents=("auto_concede_impugnacion", "escrito_impugnacion"),
        description=(
            "Quién presentó la impugnación contra el fallo de 1ra instancia. "
            "Buscar en el AUTO QUE CONCEDE LA IMPUGNACIÓN (el juez identifica al "
            "impugnante allí) o en el escrito mismo de impugnación. "
            "NO buscar en otros documentos."
        ),
        output_schema=(
            '{"value": "ACCIONANTE|ACCIONADO|MINISTERIO_PUBLICO|null", '
            '"evidence": "fragmento corto"}'
        ),
        enum_values=["ACCIONANTE", "ACCIONADO", "MINISTERIO_PUBLICO"],
        only_if_field="impugnacion", only_if_value="SI",
        max_length=30,
    ),
    "juzgado_2nd": EnrichTarget(
        column="juzgado_2nd",
        mode=MODE_REASON,
        source_documents=("auto_concede_impugnacion", "sentencia_segunda_instancia"),
        description=(
            "Nombre del juzgado o tribunal que decidió la 2da instancia. Aplica "
            "factor funcional Decreto 1983/2017: si 1ra fue Juez Municipal → sube "
            "al Juez del Circuito al que pertenece el municipio; si 1ra fue del "
            "Circuito → sube al Tribunal (Superior u Contencioso Administrativo). "
            "Para Santander revisa el mapa judicial: 4 circuitos en distrito "
            "Bucaramanga (Bucaramanga, Barrancabermeja, Málaga, San Vicente) y 6 "
            "en San Gil (San Gil, Charalá, Puente Nacional, Socorro, Vélez, "
            "Cimitarra). Si no aparece, responde null."
        ),
        output_schema='{"value": "string|null", "evidence": "fragmento corto"}',
        only_if_field="impugnacion", only_if_value="SI",
        max_length=200,
    ),
    "categoria_tematica": EnrichTarget(
        column="categoria_tematica",
        mode=MODE_CLASSIFY,
        source_documents=("asunto", "pretensiones", "escrito_tutela.hechos"),
        description=(
            "Clasificación temática corta. Selecciona UN literal del catálogo: "
            "TRASLADO, NOMBRAMIENTO, DERECHO_PETICION, TUTOR_SOMBRA, "
            "INCLUSION_DISCAPACIDAD, PENSION, CESANTIAS, SALUD_DOCENTE, "
            "ACOSO_LABORAL, COBERTURA_EDUCATIVA, RESTRUCTURACION, MATRICULA, "
            "TRANSPORTE_ESCOLAR, ALIMENTACION_PAE, CALIDAD_EDUCATIVA, FSE, "
            "CNSC_CONCURSO, SALARIO, HISTORIA_LABORAL, INSPECCION, OTRO. "
            "Si no encaja, responde null."
        ),
        output_schema='{"value": "string|null", "evidence": "fragmento corto"}',
        max_length=50,
    ),
    # FASE 4 v9.4 — Ciudad de vulneración (nuevo target cognitivo)
    "ciudad_vulneracion": EnrichTarget(
        column="ciudad",
        mode=MODE_REASON,
        source_documents=("escrito_tutela.hechos", "auto_admisorio"),
        description=(
            "Municipio de SANTANDER donde se vulneró el derecho fundamental. "
            "NO es la ciudad del juzgado. Buscar en la sección HECHOS del escrito "
            "de tutela (lugar donde vive el accionante, donde labora si es docente, "
            "donde está la institución educativa, donde ocurrió el hecho). "
            "Solo aceptar municipios reales de Santander. Si la ciudad ya está "
            "rellena con el nombre del juzgado por error, este campo NO debe pisar "
            "salvo que se confirme el municipio real de los hechos."
        ),
        output_schema='{"value": "string|null", "evidence": "fragmento corto"}',
        max_length=80,
    ),
    # FASE 3 v9.4 — Pretensiones VERBATIM (transcripción literal)
    "pretensiones_verbatim": EnrichTarget(
        column="pretensiones",
        mode=MODE_VERBATIM,
        source_documents=("escrito_tutela.pretensiones",),
        description=(
            "TRANSCRIBE LITERALMENTE las pretensiones del escrito de tutela. "
            "NO RESUMAS. NO PARAFRASEES. Copia exactamente como aparecen, "
            "incluyendo numeración (PRIMERA, SEGUNDA, ...) o (1., 2., 3., ...). "
            "Las pretensiones suelen estar en una sección titulada 'PRETENSIONES' "
            "o 'PETICIONES'. La PRIMERA siempre es 'Tutelar/Amparar el derecho "
            "fundamental a...'; las siguientes son acciones específicas. "
            "Si no encuentras la sección clara, responde null (NO inventes)."
        ),
        output_schema='{"value": "string|null", "evidence": "fragmento corto"}',
        max_length=4000,
    ),
}


@dataclass
class EnrichmentResult:
    case_id: int
    targets_attempted: list[str]
    fields_filled: dict[str, str]                  # column -> nuevo valor
    fields_skipped: dict[str, str]                 # column -> razón
    qwen_calls: int = 0
    total_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    error: str | None = None


# ─── Helpers ────────────────────────────────────────────────────────

def _build_text(case: sqlite3.Row) -> str:
    """Texto narrativo de entrada al LLM (campos extraídos)."""
    parts = []
    for k in ("asunto", "pretensiones", "accionados", "derecho_vulnerado",
              "decision_incidente", "observaciones"):
        v = case[k] if k in case.keys() else None
        if v:
            parts.append(f"[{k.upper()}] {v}")
    return "\n\n".join(parts)[:6000]


# Instrucciones operacionales por modo cognitivo
MODE_INSTRUCTIONS = {
    MODE_VERBATIM: (
        "OPERACIÓN: TRANSCRIPCIÓN LITERAL. Copia EXACTAMENTE como aparece en el "
        "texto fuente. NO RESUMAS. NO PARAFRASEES. NO RECORTES. Preserva números, "
        "puntuación y saltos de línea. Si no encuentras la sección clara, "
        "responde null."
    ),
    MODE_PARAPHRASE: (
        "OPERACIÓN: PARÁFRASIS CORTA. Resume la esencia en máximo {max_length} "
        "caracteres con verbo + objeto + acción. Captura la pretensión jurídica "
        "central."
    ),
    MODE_CLASSIFY: (
        "OPERACIÓN: CLASIFICACIÓN ENUM. Selecciona EXACTAMENTE UN literal del "
        "catálogo provisto. NO inventes valores nuevos. Si ninguno encaja, "
        "responde null."
    ),
    MODE_REASON: (
        "OPERACIÓN: RAZONAMIENTO BREVE. Razona sobre el texto y emite UNA frase "
        "concreta basada en evidencia presente. Si la evidencia no es clara, "
        "responde null. NO inventes datos no presentes."
    ),
}


def _build_prompt(target: EnrichTarget, case_text: str, case: sqlite3.Row) -> str:
    extras = []
    if target.only_if_field:
        extras.append(f"Estado relevante: {target.only_if_field}={case[target.only_if_field]!r}")
    extras_str = "\n".join(extras) + ("\n" if extras else "")

    mode_instr = MODE_INSTRUCTIONS.get(target.mode, MODE_INSTRUCTIONS[MODE_REASON])
    mode_instr = mode_instr.format(max_length=target.max_length)

    sources_str = (
        "FUENTES PRIORITARIAS (donde buscar): "
        + ", ".join(target.source_documents)
        if target.source_documents else
        "FUENTES: cualquier documento del expediente."
    )

    return (
        f"Tarea: extraer un dato de un expediente de tutela colombiano.\n\n"
        f"CAMPO A EXTRAER: {target.column}\n"
        f"MODO: {target.mode}\n"
        f"{mode_instr}\n\n"
        f"{sources_str}\n\n"
        f"DESCRIPCIÓN ESPECÍFICA: {target.description}\n"
        f"FORMATO DE SALIDA (JSON): {target.output_schema}\n\n"
        f"TEXTO DEL CASO:\n{extras_str}\n{case_text}\n\n"
        f"Devuelve SOLO el JSON con el valor extraído (o null). No expliques."
    )


def _call_qwen_json(prompt: str, max_tokens: int = 256) -> tuple[dict | None, dict]:
    """Llama Qwen con response_format JSON. Retorna (parsed, usage)."""
    payload = {
        "model": QWEN_MODEL,
        "messages": [
            {"role": "system",
             "content": "Eres un extractor jurídico. Devuelves SOLO JSON válido."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    r = requests.post(QWEN_URL, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    usage = data.get("usage", {})
    text = data["choices"][0]["message"].get("content", "").strip()
    try:
        return json.loads(text), usage
    except Exception as e:
        logger.warning("JSON parse falló: %s — text=%r", e, text[:200])
        return None, usage


# ─── Reglas deterministas (sin Qwen, sin tokens) ────────────────────

def apply_deterministic_rules(case: sqlite3.Row) -> dict[str, str]:
    """Aplica reglas jurídicas deterministas que no requieren IA.

    Devuelve dict {columna: valor_derivado} solo para columnas que se pueden
    rellenar deterministamente y que actualmente están vacías.

    Reglas:
      - juzgado_2nd: derivado del mapa judicial Santander (lugar de los hechos
        + nivel del juzgado de 1ra) — solo si hubo impugnación.
      - direccion / grupo / categoria_tematica: clasificación SED por
        keyword matching del asunto + pretensiones.
    """
    out: dict[str, str] = {}

    keys = set(case.keys())

    # 1) Derivación juzgado_2nd
    if "juzgado_2nd" in keys and not case["juzgado_2nd"]:
        impugnacion = case["impugnacion"] if "impugnacion" in keys else None
        # Solo derivar si hay impugnación SI o si ya existe juzgado_1st
        if impugnacion == "SI":
            jz1 = case["juzgado"] if "juzgado" in keys else None
            accionados = case["accionados"] if "accionados" in keys else None
            ciudad = case["ciudad"] if "ciudad" in keys else None
            try:
                deriv = derivar_juzgado_segunda(jz1, accionados, ciudad)
                if deriv and deriv.juzgado_2nd and "(no determinable)" not in deriv.juzgado_2nd:
                    out["juzgado_2nd"] = deriv.juzgado_2nd[:200]
            except Exception:
                logger.exception("derivar_juzgado_segunda falló para caso %s",
                                  case["id"] if "id" in keys else "?")

    # 2) Clasificación SED temática (L1, L2, L3, categoria_tematica)
    asunto = case["asunto"] if "asunto" in keys else ""
    pret = case["pretensiones"] if "pretensiones" in keys else ""
    blob = " ".join(filter(None, [asunto, pret]))[:2000]
    if blob:
        l1, l2, l3, cat = clasificar_sed_tematica(blob)
        if "direccion" in keys and not case["direccion"] and l1:
            out["direccion"] = l1
        if "grupo" in keys and not case["grupo"] and l2:
            out["grupo"] = l2
        if "equipo" in keys and not case["equipo"] and l3:
            out["equipo"] = l3
        if "categoria_tematica" in keys and not case["categoria_tematica"] and cat:
            out["categoria_tematica"] = cat

    return out


def enrich_deterministic_only(case_id: int) -> EnrichmentResult:
    """Enriquecimiento solo con reglas deterministas, sin invocar Qwen.

    Mucho más rápido (~5ms/caso) y sin requerir GPU LLM. Útil para batch
    sobre 213 casos completos en pocos segundos.
    """
    t_start = time.time()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    case = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not case:
        conn.close()
        return EnrichmentResult(
            case_id=case_id, targets_attempted=[],
            fields_filled={}, fields_skipped={},
            error=f"Caso {case_id} no existe",
            total_ms=(time.time() - t_start) * 1000,
        )

    rules_filled = apply_deterministic_rules(case)
    if rules_filled:
        sets = ", ".join(f"{c} = ?" for c in rules_filled.keys())
        params = list(rules_filled.values()) + [case_id]
        conn.execute(
            f"UPDATE cases SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            params,
        )
        conn.commit()
    conn.close()

    return EnrichmentResult(
        case_id=case_id,
        targets_attempted=list(rules_filled.keys()),
        fields_filled=rules_filled,
        fields_skipped={},
        qwen_calls=0,
        total_ms=round((time.time() - t_start) * 1000, 1),
    )


# ─── API principal ──────────────────────────────────────────────────

def enrich_case(case_id: int, targets: list[str] | None = None,
                overwrite: bool = False) -> EnrichmentResult:
    """Enriquece un caso llamando Qwen para campos vacíos.

    Args:
      case_id: id en tabla cases
      targets: lista de columnas a enriquecer (default: todas TARGETS)
      overwrite: si True, sobreescribe valores existentes
    """
    t_start = time.time()

    # Garantizar Qwen arriba
    s = lifecycle.refresh_status()
    if not s.qwen_up:
        logger.info("Qwen down — wake_chat()")
        s = lifecycle.wake_chat()
        if not s.qwen_up:
            return EnrichmentResult(
                case_id=case_id, targets_attempted=[],
                fields_filled={}, fields_skipped={},
                error="Qwen no disponible",
                total_ms=(time.time() - t_start) * 1000,
            )
    lifecycle.mark_chat_activity()

    # Cargar caso
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    case = conn.execute(
        "SELECT * FROM cases WHERE id = ?", (case_id,)
    ).fetchone()
    if not case:
        conn.close()
        return EnrichmentResult(
            case_id=case_id, targets_attempted=[],
            fields_filled={}, fields_skipped={},
            error=f"Caso {case_id} no existe",
            total_ms=(time.time() - t_start) * 1000,
        )

    target_names = targets or list(TARGETS.keys())
    case_text = _build_text(case)
    if len(case_text) < 30:
        conn.close()
        return EnrichmentResult(
            case_id=case_id, targets_attempted=[],
            fields_filled={}, fields_skipped={t: "texto insuficiente" for t in target_names},
            total_ms=(time.time() - t_start) * 1000,
        )

    # ── Pre-paso determinista (sin tokens Qwen) ──
    rules_filled = apply_deterministic_rules(case) if not overwrite else {}
    if rules_filled:
        sets = ", ".join(f"{c} = ?" for c in rules_filled.keys())
        params = list(rules_filled.values()) + [case_id]
        conn.execute(
            f"UPDATE cases SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            params,
        )
        conn.commit()
        # Refrescar la fila para que Qwen no intente rellenar lo que ya pusimos
        case = conn.execute(
            "SELECT * FROM cases WHERE id = ?", (case_id,)
        ).fetchone()

    filled: dict[str, str] = dict(rules_filled)
    skipped: dict[str, str] = {}
    qwen_calls = tokens_in = tokens_out = 0

    for tname in target_names:
        tgt = TARGETS.get(tname)
        if not tgt:
            skipped[tname] = "target desconocido"
            continue

        current = case[tgt.column] if tgt.column in case.keys() else None
        if current and not overwrite:
            skipped[tname] = "ya tiene valor"
            continue

        if tgt.only_if_field:
            cond = case[tgt.only_if_field] if tgt.only_if_field in case.keys() else None
            if cond != tgt.only_if_value:
                skipped[tname] = f"no aplica ({tgt.only_if_field}={cond!r})"
                continue

        prompt = _build_prompt(tgt, case_text, case)
        try:
            parsed, usage = _call_qwen_json(prompt, max_tokens=256)
            qwen_calls += 1
            tokens_in += usage.get("prompt_tokens", 0)
            tokens_out += usage.get("completion_tokens", 0)
        except Exception as e:
            logger.warning("Qwen call %s falló: %s", tname, e)
            skipped[tname] = f"error qwen: {e}"
            continue

        if not parsed:
            skipped[tname] = "JSON inválido"
            continue

        value = parsed.get("value")
        # Qwen puede devolver None (json null), "" (vacío), o el literal "null"/"none"
        if value is None:
            skipped[tname] = "Qwen respondió null"
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped or stripped.lower() in {"null", "none", "n/a", "no aplica"}:
                skipped[tname] = "Qwen respondió null/vacío"
                continue
            value = stripped

        value_str = str(value).strip()[:tgt.max_length]
        if tgt.enum_values and value_str.upper() not in tgt.enum_values:
            skipped[tname] = f"valor fuera de enum: {value_str!r}"
            continue
        if tgt.enum_values:
            value_str = value_str.upper()

        filled[tgt.column] = value_str

    if filled:
        sets = ", ".join(f"{c} = ?" for c in filled.keys())
        params = list(filled.values()) + [case_id]
        conn.execute(
            f"UPDATE cases SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            params,
        )
        conn.commit()

    conn.close()
    lifecycle.mark_chat_activity()

    return EnrichmentResult(
        case_id=case_id,
        targets_attempted=target_names,
        fields_filled=filled,
        fields_skipped=skipped,
        qwen_calls=qwen_calls,
        total_ms=round((time.time() - t_start) * 1000, 1),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
