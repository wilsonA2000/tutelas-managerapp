"""API del Agente Jurídico IA: instrucciones en lenguaje natural + herramientas."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database.database import get_db

router = APIRouter(prefix="/api/agent", tags=["agent"])


class AgentRequest(BaseModel):
    instruction: str


@router.post("/run")
def api_run_agent(body: AgentRequest, db: Session = Depends(get_db)):
    """Ejecutar el agente con instrucción en lenguaje natural."""
    # Import tools to register them
    import backend.agent.tools.legal_tools  # noqa: F401
    from backend.agent.runner import run_agent
    return run_agent(db, body.instruction)


@router.get("/tools")
def api_list_tools():
    """Listar todas las herramientas disponibles del agente."""
    import backend.agent.tools.legal_tools  # noqa: F401
    from backend.agent.tools.registry import list_tools
    tools = list_tools()
    return {
        "count": len(tools),
        "tools": [t.to_dict() for t in tools],
    }


@router.get("/routes")
def api_routes():
    """Muestra cómo el Smart Router asigna cada tipo de tarea al mejor proveedor disponible."""
    from backend.agent.smart_router import get_available_routes, get_configured_providers, TASK_TYPES
    routes = get_available_routes()
    return {
        "task_types": TASK_TYPES,
        "routes": {
            task: {
                "provider": r.provider,
                "model": r.model,
                "reason": r.reason,
                "cost_input": r.cost_per_1m_input,
                "cost_output": r.cost_per_1m_output,
                "context_window": r.context_window,
                "fallback": f"{r.fallback_provider}/{r.fallback_model}" if r.fallback_provider else None,
            }
            for task, r in routes.items()
        },
        "providers": get_configured_providers(),
    }


@router.post("/tool/{tool_name}")
def api_execute_tool(tool_name: str, params: dict | None = None, db: Session = Depends(get_db)):
    """Ejecutar una herramienta específica por nombre."""
    import backend.agent.tools.legal_tools  # noqa: F401
    from backend.agent.tools.registry import execute_tool
    return execute_tool(tool_name, db=db, **(params or {}))


