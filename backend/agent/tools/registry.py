"""Tool Registry: sistema de registro dinámico de herramientas del agente jurídico.

Inspirado en Claude Code / Claw-Code: cada herramienta se registra con
nombre, descripción, parámetros y función ejecutora. El agente puede
listar herramientas disponibles e invocarlas por nombre.

Uso:
    from backend.agent.tools.registry import register_tool, get_tool, list_tools

    @register_tool(
        name="buscar_caso",
        description="Busca un caso por radicado o accionante",
        params={"query": "str - texto a buscar"}
    )
    def buscar_caso(db, query: str) -> dict:
        ...
"""

import logging
from dataclasses import dataclass, field
from typing import Callable, Any

logger = logging.getLogger("tutelas.tools")

# Global registry
_TOOLS: dict[str, "ToolDefinition"] = {}


@dataclass
class ToolParam:
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None


@dataclass
class ToolDefinition:
    name: str
    description: str
    category: str  # search, extraction, analysis, generation, management
    params: list[ToolParam]
    handler: Callable
    requires_db: bool = True
    requires_case_id: bool = False

    def to_prompt_schema(self) -> str:
        """Generar descripción para incluir en prompt de IA."""
        params_desc = ", ".join(
            f"{p.name}: {p.type}" + (f" (default: {p.default})" if p.default else "")
            for p in self.params
        )
        return f"- **{self.name}**({params_desc}): {self.description}"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "params": [
                {"name": p.name, "type": p.type, "description": p.description,
                 "required": p.required, "default": p.default}
                for p in self.params
            ],
        }


def register_tool(name: str, description: str, category: str = "general",
                   params: dict[str, str] | None = None,
                   requires_db: bool = True, requires_case_id: bool = False):
    """Decorador para registrar una herramienta del agente."""
    def decorator(func: Callable) -> Callable:
        tool_params = []
        if params:
            for pname, pdesc in params.items():
                parts = pdesc.split(" - ", 1)
                ptype = parts[0].strip() if len(parts) > 1 else "str"
                desc = parts[1].strip() if len(parts) > 1 else pdesc
                tool_params.append(ToolParam(name=pname, type=ptype, description=desc))

        tool = ToolDefinition(
            name=name, description=description, category=category,
            params=tool_params, handler=func,
            requires_db=requires_db, requires_case_id=requires_case_id,
        )
        _TOOLS[name] = tool
        logger.debug(f"Tool registered: {name}")
        return func
    return decorator


def get_tool(name: str) -> ToolDefinition | None:
    return _TOOLS.get(name)


def list_tools(category: str | None = None) -> list[ToolDefinition]:
    tools = list(_TOOLS.values())
    if category:
        tools = [t for t in tools if t.category == category]
    return sorted(tools, key=lambda t: (t.category, t.name))


def get_tools_prompt() -> str:
    """Generar descripción de todas las herramientas para incluir en prompt de IA."""
    categories = {}
    for tool in _TOOLS.values():
        if tool.category not in categories:
            categories[tool.category] = []
        categories[tool.category].append(tool)

    lines = ["## Herramientas disponibles del Agente Jurídico\n"]
    for cat, tools in sorted(categories.items()):
        lines.append(f"### {cat.upper()}")
        for t in tools:
            lines.append(t.to_prompt_schema())
        lines.append("")
    return "\n".join(lines)


def execute_tool(name: str, db=None, **kwargs) -> dict:
    """Ejecutar una herramienta por nombre."""
    tool = _TOOLS.get(name)
    if not tool:
        return {"error": f"Herramienta '{name}' no encontrada", "available": list(_TOOLS.keys())}

    try:
        if tool.requires_db:
            result = tool.handler(db, **kwargs)
        else:
            result = tool.handler(**kwargs)

        return {"tool": name, "result": result, "status": "ok"}
    except Exception as e:
        logger.error(f"Tool {name} failed: {e}", exc_info=True)
        return {"tool": name, "error": str(e), "status": "error"}
