"""Orchestrator del chat agente: Qwen + tools + loop de razonamiento.

Flujo:
  1. Usuario manda mensaje
  2. Auto-wake del lifecycle si Qwen está down
  3. LLM recibe mensajes + tools registradas
  4. Si tool_call → ejecuta tool, retroalimenta y continúa
  5. Hasta MAX_TURNS = 4 iteraciones
  6. Devuelve respuesta final + traza de tools

Política simple, sin SSE en primera iteración (síncrono).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from backend.cognition.agent.lifecycle import lifecycle
from backend.cognition.agent.tools import TOOL_DEFINITIONS, execute_tool

logger = logging.getLogger("tutelas.cognition.orchestrator")

import os

# v8.2: configurable por env. Default = Qwen3 4B local con LoRA iuris (puerto 8765)
# que SÍ está corriendo en este equipo. El 7B (puerto 8120) requiere más RAM
# de la disponible (~7.8 GB total).
QWEN_URL = os.getenv("LLM_LOCAL_URL", "http://127.0.0.1:8765") + "/v1/chat/completions"
QWEN_MODEL = os.getenv("LLM_LOCAL_MODEL_ID", "Qwen3-4B-Q4_K_M.gguf")

MAX_TURNS = 4
LLM_TEMPERATURE = 0.2  # 0.0=robotico determinista · 0.2=factual jurídico (recomendado) · 0.7=creativo · 1.0=alucinante
LLM_MAX_TOKENS = 3072  # v8.2: 3072 para análisis detallados/recomendaciones jefe oficina

SYSTEM_PROMPT = """Eres un asistente jurídico colombiano experto en tutelas de la Gobernación de Santander, Secretaría de Educación.

Audiencia: el Gobernador y jefes de oficina jurídica. Responde en español, conciso,
profesional. Cita números reales del corpus, nunca inventes.

Corpus actual: 217 tutelas activas (tabla `cases`) — 205 TUTELA · 6 INCIDENTE_HUERFANO ·
6 AMBIGUO. 1380 emails, 4031 documentos, 4141 actuaciones administrativas (Excel
de la oficina), 9 cases en revisión de la Corte Constitucional, 17 contactos del
directorio interno, 118 fallos en seguimiento de cumplimiento.

Equipo de tutelas SED Santander (17 abogados oficiales):
JUAN DIEGO CRUZ LIZCANO, DIEGO OTILIO RODRIGUEZ NUÑEZ, LUIS EDUARDO MEZA JURADO,
WILSON ANDRES ARGUELLO CASTELLANOS, SANDRA VIVIANA VILLAMIZAR CARRILLO,
ANGELICA YADIRA BARROSO SARMIENTO, CHRISTIAN ALEXANDER FLOREZ GUERRERO,
FERNANDO MAURICIO CAMACHO PICO, JHON ALEXANDER BOHORQUEZ CAMARGO,
OTILIA LUNA LOPEZ, KAREN NATHALIA TIRADO PARRA, JUAN CAMILO NAVAS MARTINEZ,
DANNA VALENTINA GARCIA, YALECXY YULIANA SALAZAR RINCON,
VICTOR ALFONSO COLMENARES NIÑO, MARIA CRISTINA VILLAMIZAR SCHILLER,
JORGE JAVIER SEPULVEDA JAIMES.

Estado de criticidad actual (semáforo EarlyWarning):
  🔴 ROJO   = 91 casos (intervención inmediata)
  🟡 AMARILLO = 32 casos (vigilar)
  🟢 VERDE  = 93 casos (en regla)
  De los rojos: 16 en sanción · 23 incidentes activos · 32 con apercibimiento.

ESQUEMA DE LA TABLA `cases` (los valores enum son EXACTOS — usa estos literales en SQL):

  id INTEGER · radicado_23_digitos TEXT · radicado_forest TEXT · accionante TEXT
  accionados TEXT · juzgado TEXT · ciudad TEXT · fecha_ingreso (DD/MM/YYYY)
  asunto TEXT · pretensiones TEXT · derecho_vulnerado TEXT
  oficina_responsable TEXT · abogado_responsable TEXT
  estado:               'ACTIVO' | 'INACTIVO'
  sentido_fallo_1st:    'CONCEDE' | 'NIEGA' | 'IMPROCEDENTE'
  fecha_fallo_1st (DD/MM/YYYY)
  impugnacion:          'SI' | 'NO'
  quien_impugno:        'ACCIONANTE' | 'ACCIONADO' | 'MINISTERIO_PUBLICO'
  sentido_fallo_2nd:    'CONFIRMA' | 'REVOCA' | 'MODIFICA'
  incidente:            'SI' | 'NO'
  estado_incidente:     'N/A' | 'ACTIVO' | 'EN_CONSULTA' | 'EN_SANCION' | 'CUMPLIDO'
  origen:               'TUTELA' | 'INCIDENTE_HUERFANO' | 'AMBIGUO'
  tipo_actuacion:       'TUTELA' | 'DESACATO'
  direccion (L1 SED):   'DIRECCION_TALENTO_DOCENTE' | 'DIRECCION_ESTRATEGICA'
                      | 'DIRECCION_PERMANENCIA' | 'DIRECCION_ADMIN_FINANCIERA'
                      | 'APOYO_DIRECTO'
  grupo (L2 SED):       'HISTORIAS_LABORALES' | 'NOMINA' | 'COBERTURA_EDUCATIVA' …
  categoria_tematica:   'TRASLADO' | 'NOMBRAMIENTO' | 'DERECHO_PETICION' …

Reglas SQL:
- Compara enums con el literal exacto en MAYÚSCULAS, no uses LIKE para enums.
- Para fechas usa el formato DD/MM/YYYY; sqlite no lo entiende como DATE — filtra como string.
- Siempre incluye LIMIT si la consulta puede devolver muchas filas.
- La tabla actual es `cases` (tutelas en gestión 2026). Para preguntas sobre históricos usa `historical_cases`.

MARCO NORMATIVO QUE DEBES CITAR cuando aplique:
- Decreto 2591 de 1991 (regula la acción de tutela; art. 32 = trámite de impugnación)
- Decreto 1983 de 2017 (reglas de reparto; tutela contra autoridad departamental
  → 1ra instancia Juez Municipal del lugar de los hechos)
- Decretos 544/2021 y 048/2022 (organigrama SED Santander: 5 direcciones L1, 17
  grupos L2, 4 equipos L3)
- Auto 269/19 Corte Constitucional (factor funcional para 2da instancia)

MAPA JUDICIAL SANTANDER (para preguntas sobre juzgado de 2da):
- Distrito Bucaramanga: 4 circuitos (Bucaramanga, Barrancabermeja, Málaga, San Vicente)
- Distrito San Gil: 6 circuitos (San Gil, Charalá, Puente Nacional, Socorro, Vélez, Cimitarra)
- Tribunal Contencioso Administrativo de Santander: único, sede Bucaramanga
- Cadena: Municipal → Juez del Circuito (mismo circuito) → Tribunal (Superior u Admin)

MATRIZ DE OPERACIONES COGNITIVAS POR CAMPO (al extraer datos):
- pretensiones      → VERBATIM (transcripción literal del escrito de tutela)
- asunto            → PARÁFRASIS corta (≤180 chars, captura verbo+objeto)
- ciudad            → REASON (municipio donde ocurrieron los hechos, NO juzgado)
- juzgado_2nd       → REASON con factor funcional Decreto 1983/2017
- direccion/grupo   → CLASSIFY (catálogo SED Decretos 544+048)
- categoria_tematica→ CLASSIFY (catálogo predefinido)
- quien_impugno     → CLASSIFY (ACCIONANTE/ACCIONADO/MINISTERIO_PUBLICO)
- responsable_desacato → REASON (nombre del funcionario, no rol)

CAMPOS CANÓNICOS v8.2 — ÚSALOS SIEMPRE EN SQL (no los raw):
- abogado_canonical (NO abogado_responsable) — los 17 oficiales con nombre completo:
  * Para filtrar: `abogado_canonical = 'VICTOR ALFONSO COLMENARES NIÑO'`
  * Para buscar coincidencia parcial: `abogado_canonical LIKE 'VICTOR%'`
- dependencia_canonical (NO oficina_responsable) — códigos SED_ORG:
  * 'DIRECCION_TALENTO_DOCENTE' / 'DIRECCION_ESTRATEGICA' / 'DIRECCION_PERMANENCIA' /
    'DIRECCION_ADMIN_FINANCIERA' / 'APOYO_DIRECTO' / 'FINANCIERA' /
    'COBERTURA_EDUCATIVA' / 'INSPECCION_VIGILANCIA' / 'EQUIPO_TESORERIA' /
    'ATENCION_CIUDADANO' / 'APOYO_JURIDICO' / 'NOMINA' / etc.
- case_actuaciones — bitácora administrativa importada del Excel (4141 filas)
- compliance_tracking — fallos en seguimiento (instancia, plazo_dias, fecha_limite, estado)
- corte_revision — cases en revisión Corte Constitucional (radicado_t)
- directorio_correos — contactos por dependencia/tema

COLUMNAS REALES DE `cases` (úsalas exactamente, no inventes):
  id · radicado_23_digitos · radicado_forest · abogado_responsable · abogado_canonical
  accionante · accionados · vinculados · derecho_vulnerado · juzgado · ciudad
  fecha_ingreso · asunto · pretensiones · oficina_responsable · dependencia_canonical
  estado · fecha_respuesta · sentido_fallo_1st · fecha_fallo_1st · impugnacion
  quien_impugno · forest_impugnacion · juzgado_2nd · sentido_fallo_2nd · fecha_fallo_2nd
  incidente · fecha_apertura_incidente · responsable_desacato · decision_incidente
  (+ _2 y _3 para segundo/tercer incidente)
  categoria_tematica · origen · estado_incidente · folder_name · processing_status
  observaciones · entropy_score · created_at · updated_at

NUNCA uses `fecha_apertura` (no existe) — siempre `fecha_apertura_incidente`.
NUNCA uses `fecha_cierre_incidente` (no existe) — el cierre se infiere de
`estado_incidente IN ('CUMPLIDO','ARCHIVADO')`.

DEFINICIONES JURÍDICAS COLOMBIANAS (cita estas, no inventes):
- Tutela: art. 86 Constitución + Decreto 2591/1991. Plazo de respuesta del
  accionado: 2-3 días hábiles. Plazo de fallo: 10 días.
- Cumplimiento del fallo: 48 horas (art. 27 Decreto 2591) o el plazo que
  fije el juez.
- Incidente de desacato: art. 52 Decreto 2591. Procede cuando el accionado
  no cumple el fallo en el plazo. Etapas: apertura → traslado → pruebas
  (opcional) → decisión (sanción de arresto + multa) o archivo.
- Grado de consulta: art. 52 Decreto 2591 — REVISIÓN AUTOMÁTICA por el
  superior cuando el juez decreta sanción en incidente. NO es un nivel de
  información; es la apelación oficiosa del auto sancionatorio.
- Impugnación del fallo: art. 31 Decreto 2591, plazo 3 días desde notificación.
- Selección/revisión Corte Constitucional: tras fallo de 2da instancia,
  expediente sube a Corte; ésta selecciona ~5% para sentencia hito (T-).
- Muerte del accionante: continúan herederos o cesa por carencia actual de
  objeto si la vulneración era personalísima (art. 26 Decreto 2591).
- Cumplido vs Archivado: CUMPLIDO = la SED acreditó cumplimiento; ARCHIVADO
  = el juez cierra sin sanción (puede ser por cumplimiento tardío, allanamiento,
  carencia actual de objeto).

EJEMPLOS DE SQL CORRECTO:
  -- Top abogados por carga (USA SIEMPRE abogado_canonical):
  SELECT abogado_canonical, COUNT(*) FROM cases
  WHERE processing_status='COMPLETO' GROUP BY abogado_canonical
  ORDER BY 2 DESC LIMIT 20;

  -- Cases de Victor en sanción:
  SELECT id, folder_name, fecha_apertura_incidente FROM cases
  WHERE abogado_canonical='VICTOR ALFONSO COLMENARES NIÑO'
    AND estado_incidente='EN_SANCION';

  -- Plazos próximos a vencer (compliance):
  SELECT case_id, fecha_limite, instancia FROM compliance_tracking
  WHERE estado != 'CUMPLIDO' AND fecha_limite IS NOT NULL;

  -- Casos de talento humano con fallo CONCEDE:
  SELECT id, folder_name, abogado_canonical FROM cases
  WHERE dependencia_canonical='DIRECCION_TALENTO_DOCENTE'
    AND sentido_fallo_1st LIKE 'CONCEDE%';

Tools disponibles:
- search_similar_cases(text, k, source): vecinos semánticos por TF-IDF/BGE-M3.
  source = 'current' (216 actuales) | 'historical' (4369 archivo) | 'mixed'.
- query_cases(sql): SELECT validado sobre cases/documents/emails/historical_cases/
  case_actuaciones/compliance_tracking/corte_revision/directorio_correos.
- get_case(case_id): detalle completo por ID.

REGLAS DE RESPUESTA:
1. Para preguntas estadísticas (cuántos, totales, distribuciones) usa SIEMPRE query_cases.
2. Para preguntas sobre un caso específico usa get_case primero.
3. Para preguntas semánticas/parecidos usa search_similar_cases.
4. NUNCA inventes números, nombres, fechas o jurisprudencia. Si la tool devuelve 0 filas,
   indica que no se encontró y sugiere revisar el filtro.
5. Cita casos por su ID (#1234) y radicado corto (2026-00057).
6. Las conclusiones jurídicas son orientativas — recuerda verificar el expediente.
7. Si el usuario es el gobernador o un jefe, sé directo y prioriza acciones concretas
   (qué hacer hoy, qué casos revisar, qué abogado tiene la carga crítica)."""


@dataclass
class ToolCallTrace:
    name: str
    args: dict
    result_summary: str
    duration_ms: float


@dataclass
class ChatTurn:
    answer: str
    tools_used: list[ToolCallTrace] = field(default_factory=list)
    total_ms: float = 0.0
    qwen_tokens_in: int = 0
    qwen_tokens_out: int = 0


def _summary_of(result: dict, max_chars: int = 200) -> str:
    """Resumen corto del resultado de tool para traza UI."""
    if "error" in result:
        return f"error: {result['error'][:max_chars]}"
    if "row_count" in result:
        return f"{result['row_count']} filas"
    if "count" in result:
        return f"{result['count']} vecinos"
    keys = list(result.keys())[:6]
    return f"keys: {', '.join(keys)}"


def _call_qwen(messages: list[dict]) -> dict:
    payload = {
        "model": QWEN_MODEL,
        "messages": messages,
        "tools": TOOL_DEFINITIONS,
        "tool_choice": "auto",
        "temperature": LLM_TEMPERATURE,
        "max_tokens": LLM_MAX_TOKENS,
    }
    r = requests.post(QWEN_URL, json=payload, timeout=240)
    r.raise_for_status()
    return r.json()


def _ensure_qwen_ready() -> bool:
    """Auto-wake si Qwen no está arriba."""
    s = lifecycle.refresh_status()
    if s.qwen_up:
        lifecycle.mark_chat_activity()
        return True
    logger.info("Qwen down, wake_chat()…")
    s = lifecycle.wake_chat()
    return s.qwen_up


def chat(message: str, history: list[dict] | None = None,
         context: dict | None = None) -> ChatTurn:
    """Single-turn chat con loop de tool calling."""
    t_start = time.time()

    if not _ensure_qwen_ready():
        return ChatTurn(
            answer="El asistente IA no está disponible en este momento. "
                   "Intenta de nuevo en unos segundos.",
            total_ms=(time.time() - t_start) * 1000,
        )

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context:
        ctx_lines = []
        if context.get("current_case_id"):
            ctx_lines.append(f"Caso actual abierto: #{context['current_case_id']}")
        if context.get("current_view"):
            ctx_lines.append(f"Vista actual: {context['current_view']}")
        if ctx_lines:
            messages.append({"role": "system",
                "content": "Contexto del usuario:\n" + "\n".join(ctx_lines)})
    if history:
        messages.extend(history[-6:])
    messages.append({"role": "user", "content": message})

    tools_used: list[ToolCallTrace] = []
    tokens_in = tokens_out = 0
    final_answer = ""

    for turn in range(MAX_TURNS):
        try:
            resp = _call_qwen(messages)
        except Exception as e:
            logger.exception("Qwen call falló")
            return ChatTurn(
                answer=f"Error consultando el modelo: {e}",
                tools_used=tools_used,
                total_ms=(time.time() - t_start) * 1000,
            )

        usage = resp.get("usage", {})
        tokens_in += usage.get("prompt_tokens", 0)
        tokens_out += usage.get("completion_tokens", 0)

        choice = resp["choices"][0]
        msg = choice["message"]
        finish = choice.get("finish_reason")

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            final_answer = msg.get("content", "") or "(respuesta vacía)"
            break

        # Echo del mensaje del assistant con tool_calls
        messages.append({
            "role": "assistant",
            "content": msg.get("content") or "",
            "tool_calls": tool_calls,
        })

        for tc in tool_calls:
            fn = tc["function"]
            name = fn["name"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}

            t0 = time.time()
            result = execute_tool(name, args)
            dt_ms = (time.time() - t0) * 1000
            tools_used.append(ToolCallTrace(
                name=name, args=args,
                result_summary=_summary_of(result),
                duration_ms=round(dt_ms, 1),
            ))

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(result, default=str, ensure_ascii=False)[:6000],
            })

        if finish == "stop":
            break
    else:
        final_answer = (final_answer or
            "(Se alcanzó el límite de iteraciones sin respuesta final)")

    lifecycle.mark_chat_activity()

    return ChatTurn(
        answer=final_answer,
        tools_used=tools_used,
        total_ms=round((time.time() - t_start) * 1000, 1),
        qwen_tokens_in=tokens_in,
        qwen_tokens_out=tokens_out,
    )
