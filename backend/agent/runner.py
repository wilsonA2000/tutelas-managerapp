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
Trabajas para la Gobernación de Santander gestionando ~273 casos de tutela activos.

Tu trabajo es interpretar las instrucciones del usuario y decidir qué herramientas usar.
Tienes acceso al Cuadro de Tutelas (la misma tabla que los abogados ven en pantalla) via la herramienta consultar_cuadro.
Cuando el usuario pregunte sobre datos de casos, estados, fallos, fechas, etc., usa consultar_cuadro para obtener datos reales.

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
    """Ejecutar el agente con una instrucción en lenguaje natural.

    Flujo simple:
    1. Detectar qué herramientas usar por keywords (local, sin IA)
    2. Ejecutar herramientas y obtener datos reales
    3. Usar IA solo para resumir los datos en lenguaje natural
    """
    import time
    start = time.time()

    execution = AgentExecution(instruction=instruction)

    # Step 1: Detectar herramientas por keywords (LOCAL, sin IA, instantáneo)
    plan = _fallback_plan(instruction)
    execution.plan = plan.get("plan", "")

    if plan.get("answer") and not plan.get("steps"):
        execution.answer = plan["answer"]
        execution.status = "completed"
        execution.total_duration_ms = int((time.time() - start) * 1000)
        return _execution_to_dict(execution)

    for step_data in plan.get("steps", []):
        execution.steps.append(AgentStep(
            tool=step_data.get("tool", ""),
            params=step_data.get("params", {}),
            reason=step_data.get("reason", ""),
        ))

    # Step 2: Ejecutar herramientas y obtener datos reales
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

    # Step 3: Usar IA para resumir los datos en respuesta humana
    execution.status = "completed"
    execution.answer = _summarize_with_ai(execution)
    execution.total_duration_ms = int((time.time() - start) * 1000)

    logger.info(
        f"Agent completed: {len(execution.steps)} steps, "
        f"{execution.total_duration_ms}ms, instruction: '{instruction[:60]}'"
    )

    result = _execution_to_dict(execution)
    return result


def _plan_with_ai(instruction: str) -> dict:
    """Planificar qué herramientas usar via Smart Router (DeepSeek/Haiku)."""
    import os
    tools_desc = get_tools_prompt()
    system = AGENT_SYSTEM_PROMPT.format(tools_description=tools_desc)

    try:
        from backend.agent.smart_router import route
        from backend.extraction.ai_extractor import PROVIDERS

        decision = route("general")
        provider = decision.provider
        model = decision.model
        env_key = PROVIDERS.get(provider, {}).get("env_key", "")
        api_key = os.getenv(env_key, "") if env_key else ""

        if not api_key:
            return _fallback_plan(instruction)

        user_msg = f"Instrucción del usuario: {instruction}"

        if provider == "deepseek":
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.1,
                max_tokens=2000,
                response_format={"type": "json_object"},
            )
            return json.loads(resp.choices[0].message.content)

        elif provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model=model,
                system=system,
                messages=[{"role": "user", "content": user_msg + "\n\nResponde SOLO JSON válido."}],
                temperature=0.1,
                max_tokens=2000,
            )
            text = resp.content[0].text
            # Extract JSON from response
            import re
            json_match = re.search(r'\{[\s\S]*\}', text)
            return json.loads(json_match.group()) if json_match else _fallback_plan(instruction)

        else:
            return _fallback_plan(instruction)

    except Exception as e:
        logger.warning(f"AI planning failed, using fallback: {e}")
        return _fallback_plan(instruction)


def _enrich_params(step: AgentStep, instruction: str):
    """Enrich empty params when AI forgets to set them but the instruction has clear intent."""
    if step.tool != "consultar_cuadro":
        return
    if step.params.get("campo") or step.params.get("filtro"):
        return  # Already has params

    inst = instruction.lower()
    field_keywords = [
        (["concede", "desfavorable"], "SENTIDO_FALLO_1ST", "CONCEDE"),
        (["niega", "favorable"], "SENTIDO_FALLO_1ST", "NIEGA"),
        (["improcedente"], "SENTIDO_FALLO_1ST", "IMPROCEDENTE"),
        (["activo"], "ESTADO", "ACTIVO"),
        (["inactivo"], "ESTADO", "INACTIVO"),
        (["impugn"], "IMPUGNACION", "SI"),
        (["incidente", "desacato"], "INCIDENTE", "SI"),
    ]
    for keywords, campo, valor in field_keywords:
        if any(kw in inst for kw in keywords):
            # Avoid false positives: "inactivo" should not match "activo"
            if campo == "ESTADO" and valor == "ACTIVO" and "inactivo" in inst:
                continue
            step.params["campo"] = campo
            step.params["valor"] = valor
            return

    # Fallback: use free-text filtro from instruction
    for prefix in ["cuadro ", "consultar ", "buscar ", "tutelas de ", "casos de ", "casos con ", "casos en "]:
        if prefix in inst:
            filtro = instruction[inst.index(prefix) + len(prefix):].strip()[:50]
            if filtro:
                step.params["filtro"] = filtro
                return


def _fallback_plan(instruction: str) -> dict:
    """Plan de fallback sin IA: matching por keywords."""
    instruction_lower = instruction.lower()

    steps = []

    # Detección temática (prioridad alta — preguntas sobre categorías de tutelas)
    CATEGORY_KEYWORDS = {
        "infraestructura": "INFRAESTRUCTURA",
        "inclusi": "INCLUSION", "discapacidad": "INCLUSION",
        "tutor sombra": "TUTOR_SOMBRA", "sombra terap": "TUTOR_SOMBRA",
        "interprete": "INTERPRETES", "lengua de señas": "INTERPRETES", "señas": "INTERPRETES",
        "nombramiento": "NOMBRAMIENTOS", "nombrar docente": "NOMBRAMIENTOS",
        "traslado": "TRASLADOS",
        "carrera docente": "CARRERA_DOCENTE", "escalafon": "CARRERA_DOCENTE",
        "cobertura": "COBERTURA", "cupo": "COBERTURA", "matricula": "COBERTURA",
        "calidad educativa": "CALIDAD_EDUCATIVA",
        "prestaciones": "PRESTACIONES", "pension docente": "PRESTACIONES",
        "nomina": "NOMINA", "salario": "NOMINA", "embargo": "NOMINA",
        "debido proceso": "DEBIDO_PROCESO", "disciplinari": "DEBIDO_PROCESO",
        "residencia escolar": "RESIDENCIA_ESCOLAR", "internado": "RESIDENCIA_ESCOLAR",
        "derecho de peticion": "DERECHO_PETICION", "peticion": "DERECHO_PETICION",
    }
    for keyword, category in CATEGORY_KEYWORDS.items():
        if keyword in instruction_lower:
            steps.append({"tool": "contar_por_categoria", "params": {"categoria": category},
                          "reason": f"Contar tutelas de {category}"})
            break

    # Preguntas sobre la Secretaría / organigrama / oficinas
    if any(w in instruction_lower for w in ["secretaria de educacion", "organigrama", "oficina",
                                             "director", "estructura", "quien maneja"]):
        steps.append({"tool": "info_secretaria", "params": {}, "reason": "Info de la Secretaría de Educación"})

    # Pedir distribución de todas las categorías
    if any(w in instruction_lower for w in ["categori", "distribuci", "temas", "clasificaci"]) and not steps:
        steps.append({"tool": "contar_por_categoria", "params": {}, "reason": "Distribución por categoría temática"})

    if any(w in instruction_lower for w in ["estadístic", "estadistic", "resumen", "cuántos", "cuantos", "total"]) and not steps:
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

    if any(w in instruction_lower for w in ["cuadro", "tabla", "listado", "todos los casos", "cuántas tutelas",
                                             "cuantas tutelas", "sin fallo", "sin fecha", "incompleto",
                                             "fallo concede", "fallo niega", "activo", "inactivo"]):
        filtro = ""
        for prefix in ["cuadro ", "tabla ", "listado "]:
            if prefix in instruction_lower:
                filtro = instruction[instruction_lower.index(prefix) + len(prefix):].strip()
                break
        params = {"filtro": filtro[:50]} if filtro else {}
        # Detect field-specific filters
        if "concede" in instruction_lower:
            params = {"campo": "SENTIDO_FALLO_1ST", "valor": "CONCEDE"}
        elif "niega" in instruction_lower:
            params = {"campo": "SENTIDO_FALLO_1ST", "valor": "NIEGA"}
        elif "activo" in instruction_lower and "inactivo" not in instruction_lower:
            params = {"campo": "ESTADO", "valor": "ACTIVO"}
        elif "inactivo" in instruction_lower:
            params = {"campo": "ESTADO", "valor": "INACTIVO"}
        elif "impugn" in instruction_lower:
            params = {"campo": "IMPUGNACION", "valor": "SI"}
        elif "incidente" in instruction_lower or "desacato" in instruction_lower:
            params = {"campo": "INCIDENTE", "valor": "SI"}
        steps.append({"tool": "consultar_cuadro", "params": params, "reason": "Consultar datos del cuadro de tutelas"})

    # Si no detectó nada por keywords, consultar el cuadro con la pregunta como filtro
    if not steps:
        steps.append({"tool": "consultar_cuadro", "params": {"filtro": instruction[:80]}, "reason": "Buscar en el cuadro de tutelas"})

    return {"plan": f"Ejecutar {len(steps)} herramientas para: {instruction[:60]}", "steps": steps}


def _summarize_with_ai(execution: AgentExecution) -> str:
    """Tomar los datos crudos de las herramientas y generar respuesta en lenguaje natural."""
    # Recopilar datos crudos
    raw_data = []
    for step in execution.steps:
        if step.status != "completed" or not step.result:
            continue
        result = step.result.get("result", {})
        raw_data.append({"tool": step.tool, "data": result})

    if not raw_data:
        return "No se obtuvieron datos. Intenta con otra pregunta."

    # Intentar resumir con IA
    try:
        import os
        from backend.agent.smart_router import route

        decision = route("general")
        env_key = {"deepseek": "DEEPSEEK_API_KEY",
                    "anthropic": "ANTHROPIC_API_KEY"}.get(decision.provider, "")
        api_key = os.getenv(env_key, "")

        if not api_key:
            return _format_raw(execution)

        # Truncar datos para no exceder tokens
        data_str = json.dumps(raw_data, ensure_ascii=False, default=str)
        if len(data_str) > 8000:
            data_str = data_str[:8000] + "...(truncado)"

        prompt = (
            f"El usuario preguntó: \"{execution.instruction}\"\n\n"
            f"Datos obtenidos del sistema de tutelas:\n{data_str}\n\n"
            "Responde en español, de forma clara y directa. "
            "Usa numeros concretos de los datos. "
            "Si hay una lista de casos, muestra los primeros 5 con su nombre y datos relevantes. "
            "Formato: texto plano con **negritas** para destacar numeros importantes. "
            "Maximo 200 palabras."
        )

        if decision.provider == "deepseek":
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
            resp = client.chat.completions.create(
                model=decision.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=500,
            )
            return resp.choices[0].message.content

        elif decision.provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model=decision.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=500,
            )
            return resp.content[0].text

    except Exception as e:
        logger.warning(f"AI summary failed, using raw format: {e}")

    return _format_raw(execution)


def _format_raw(execution: AgentExecution) -> str:
    """Formato simple cuando IA no está disponible."""
    parts = []
    for step in execution.steps:
        if step.status != "completed" or not step.result:
            continue
        result = step.result.get("result", {})
        if isinstance(result, dict):
            for k, v in list(result.items())[:10]:
                val = str(v) if not isinstance(v, (dict, list)) else json.dumps(v, ensure_ascii=False)[:150]
                parts.append(f"- **{k}:** {val}")
        elif isinstance(result, list):
            parts.append(f"**{len(result)} resultados encontrados:**")
            for item in result[:5]:
                if isinstance(item, dict):
                    summary = ", ".join(f"{k}={v}" for k, v in list(item.items())[:4])
                    parts.append(f"- {summary}")
    return "\n".join(parts) if parts else "Sin datos disponibles."


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
