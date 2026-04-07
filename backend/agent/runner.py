"""Agent Runner: recibe instrucciones en lenguaje natural y ejecuta herramientas.

Similar a Claude Code: el usuario da una instrucción, el agente planifica
qué herramientas usar, las ejecuta secuencialmente, y reporta resultados.
"""

import json
import logging
from datetime import datetime
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from backend.agent.tools.registry import list_tools, execute_tool, get_tools_prompt

logger = logging.getLogger("tutelas.runner")

AGENT_SYSTEM_PROMPT = """Eres un agente jurídico IA especializado en acciones de tutela colombianas.
Trabajas para la Gobernación de Santander gestionando ~264 casos de tutela.

Tu trabajo es interpretar las instrucciones del usuario y decidir qué herramientas usar.

{tools_description}

## Instrucciones
1. Analiza la solicitud del usuario
2. Decide qué herramientas necesitas ejecutar (puedes usar varias)
3. Responde con un plan JSON:

```json
{{
  "plan": "Descripción breve del plan",
  "steps": [
    {{"tool": "nombre_herramienta", "params": {{"param1": "valor1"}}, "reason": "por qué"}},
    ...
  ]
}}
```

Si la solicitud es una pregunta que puedes responder directamente sin herramientas:
```json
{{
  "plan": "Respuesta directa",
  "steps": [],
  "answer": "Tu respuesta aquí"
}}
```

REGLAS:
- Usa SOLO herramientas que existen en la lista
- Siempre incluye "reason" explicando por qué usas esa herramienta
- Si necesitas el resultado de un paso para el siguiente, indícalo
- Responde siempre en español
- Si no sabes algo, di que no sabes en vez de inventar
"""


@dataclass
class AgentStep:
    tool: str
    params: dict
    reason: str
    result: dict | None = None
    status: str = "pending"  # pending, running, completed, error
    duration_ms: int = 0


@dataclass
class AgentExecution:
    instruction: str
    plan: str = ""
    steps: list[AgentStep] = field(default_factory=list)
    answer: str = ""
    total_duration_ms: int = 0
    status: str = "planning"  # planning, executing, completed, error


def run_agent(db: Session, instruction: str) -> dict:
    """Ejecutar el agente con una instrucción en lenguaje natural."""
    import time
    start = time.time()

    execution = AgentExecution(instruction=instruction)

    # Step 0: Check cache first (saves tokens)
    from backend.agent.token_manager import get_cached_response, cache_response, check_budget
    cached = get_cached_response(instruction)
    if cached:
        cached["from_cache"] = True
        cached["total_duration_ms"] = int((time.time() - start) * 1000)
        return cached

    # Step 0.5: Check budget
    allowed, reason = check_budget(db)
    if not allowed:
        execution.status = "error"
        execution.answer = f"Presupuesto excedido: {reason}. Usando herramientas locales sin IA."
        # Still try fallback plan (no AI)

    # Step 1: Plan - ask AI what tools to use
    try:
        plan = _plan_with_ai(instruction)
        execution.plan = plan.get("plan", "")
        execution.answer = plan.get("answer", "")

        if execution.answer and not plan.get("steps"):
            # Direct answer, no tools needed
            execution.status = "completed"
            execution.total_duration_ms = int((time.time() - start) * 1000)
            return _execution_to_dict(execution)

        # Build steps
        for step_data in plan.get("steps", []):
            execution.steps.append(AgentStep(
                tool=step_data.get("tool", ""),
                params=step_data.get("params", {}),
                reason=step_data.get("reason", ""),
            ))

    except Exception as e:
        logger.error(f"Agent planning failed: {e}")
        execution.status = "error"
        execution.answer = f"Error al planificar: {str(e)}"
        return _execution_to_dict(execution)

    # Step 2: Execute each tool
    execution.status = "executing"
    for step in execution.steps:
        step.status = "running"
        step_start = time.time()
        try:
            result = execute_tool(step.tool, db=db, **step.params)
            step.result = result
            step.status = "completed" if result.get("status") == "ok" else "error"
        except Exception as e:
            step.result = {"error": str(e)}
            step.status = "error"
        step.duration_ms = int((time.time() - step_start) * 1000)

    # Step 3: Summarize results
    execution.status = "completed"
    if not execution.answer:
        execution.answer = _summarize_results(execution)
    execution.total_duration_ms = int((time.time() - start) * 1000)

    logger.info(
        f"Agent completed: {len(execution.steps)} steps, "
        f"{execution.total_duration_ms}ms, instruction: '{instruction[:60]}'"
    )

    result = _execution_to_dict(execution)

    # Cache the response for future identical queries
    cache_response(instruction, result)

    return result


def _plan_with_ai(instruction: str) -> dict:
    """Usar Gemini para planificar qué herramientas usar."""
    import os
    tools_desc = get_tools_prompt()
    system = AGENT_SYSTEM_PROMPT.format(tools_description=tools_desc)

    try:
        from google import genai
        api_key = os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            return _fallback_plan(instruction)

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"Instrucción del usuario: {instruction}",
            config=genai.types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                temperature=0.1,
                max_output_tokens=2000,
            ),
        )
        return json.loads(response.text)

    except Exception as e:
        logger.warning(f"AI planning failed, using fallback: {e}")
        return _fallback_plan(instruction)


def _fallback_plan(instruction: str) -> dict:
    """Plan de fallback sin IA: matching por keywords."""
    instruction_lower = instruction.lower()

    steps = []

    if any(w in instruction_lower for w in ["estadístic", "estadistic", "resumen", "cuántos", "cuantos", "total"]):
        steps.append({"tool": "estadisticas_generales", "params": {}, "reason": "Obtener estadísticas generales"})

    if any(w in instruction_lower for w in ["alerta", "problema", "anomal", "escanear", "escan"]):
        steps.append({"tool": "escanear_alertas", "params": {}, "reason": "Ejecutar escaneo de alertas"})
        steps.append({"tool": "listar_alertas", "params": {"severity": "CRITICAL"}, "reason": "Ver alertas críticas"})

    if any(w in instruction_lower for w in ["plazo", "venc", "deadline", "urgente"]):
        steps.append({"tool": "listar_alertas", "params": {"severity": "CRITICAL"}, "reason": "Ver plazos urgentes"})

    if any(w in instruction_lower for w in ["buscar", "encontrar", "caso", "radicado"]):
        # Extract search query
        for prefix in ["buscar ", "encontrar ", "busca ", "encuentra "]:
            if prefix in instruction_lower:
                query = instruction[instruction_lower.index(prefix) + len(prefix):].strip()
                steps.append({"tool": "buscar_caso", "params": {"query": query[:50]}, "reason": f"Buscar '{query[:50]}'"})
                break

    if any(w in instruction_lower for w in ["abogado", "rendimiento", "desempeño"]):
        for name in ["Cruz", "Rodriguez", "Meza", "Barroso", "Bohorquez", "Luna", "Colmenares", "Florez", "Camacho", "Garcia"]:
            if name.lower() in instruction_lower:
                steps.append({"tool": "analizar_abogado", "params": {"nombre": name}, "reason": f"Analizar rendimiento de {name}"})
                break

    if any(w in instruction_lower for w in ["predecir", "predicción", "probabilidad", "resultado probable"]):
        params = {}
        # Simple keyword extraction
        for w in instruction.split():
            if len(w) > 3 and w[0].isupper():
                params["ciudad"] = w
                break
        steps.append({"tool": "predecir_resultado", "params": params, "reason": "Ejecutar predicción"})

    if any(w in instruction_lower for w in ["municipio", "ciudad"]):
        steps.append({"tool": "casos_por_municipio", "params": {}, "reason": "Listar casos por municipio"})

    if not steps:
        return {"plan": "No pude determinar qué herramientas usar", "steps": [],
                "answer": f"No encontré herramientas adecuadas para: '{instruction}'. Intenta ser más específico o pregunta por: estadísticas, alertas, búsqueda de casos, plazos, predicciones, rendimiento de abogados."}

    return {"plan": f"Ejecutar {len(steps)} herramientas para: {instruction[:60]}", "steps": steps}


def _summarize_results(execution: AgentExecution) -> str:
    """Resumir resultados de la ejecución."""
    parts = [f"**Plan:** {execution.plan}\n"]
    for i, step in enumerate(execution.steps, 1):
        status_icon = "OK" if step.status == "completed" else "ERROR"
        parts.append(f"**Paso {i} [{status_icon}]:** {step.tool} ({step.reason})")
        if step.result:
            result_data = step.result.get("result", step.result.get("error", ""))
            if isinstance(result_data, dict):
                for k, v in list(result_data.items())[:8]:
                    parts.append(f"  - {k}: {v}")
            elif isinstance(result_data, list):
                parts.append(f"  - {len(result_data)} resultados")
                for item in result_data[:3]:
                    if isinstance(item, dict):
                        summary = ", ".join(f"{k}={v}" for k, v in list(item.items())[:4])
                        parts.append(f"    - {summary}")
        parts.append(f"  ({step.duration_ms}ms)")
    return "\n".join(parts)


def _execution_to_dict(execution: AgentExecution) -> dict:
    return {
        "instruction": execution.instruction,
        "plan": execution.plan,
        "answer": execution.answer,
        "steps": [
            {
                "tool": s.tool,
                "params": s.params,
                "reason": s.reason,
                "status": s.status,
                "duration_ms": s.duration_ms,
                "result": s.result,
            }
            for s in execution.steps
        ],
        "status": execution.status,
        "total_duration_ms": execution.total_duration_ms,
    }
