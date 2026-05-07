"""Tools del agente cognitivo — funciones que Qwen puede invocar vía tool calling.

Cada tool tiene:
  - JSON Schema (formato OpenAI tools)
  - función ejecutora segura (validada, acotada, sin side-effects no deseados)

Tools disponibles:
  - search_similar_cases : RAG sobre BGE-M3 (sin tocar GPU LLM)
  - query_cases          : Text-to-SQL validado sobre tabla cases
  - get_case             : detalle de un caso por ID
  - count_by             : agregaciones rápidas precomputadas
"""
from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any

import sqlglot
from sqlglot import exp

logger = logging.getLogger("tutelas.cognition.tools")

# v8.2: ruta resuelta relativa al repo (antes hardcoded a /workspace del pod)
import os
from pathlib import Path
_REPO_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = os.getenv("TUTELAS_DB_PATH", str(_REPO_ROOT / "data" / "tutelas.db"))

# Whitelist seguridad SQL ─────────────────────────────────────────
# v8.2: agregadas tablas auxiliares
ALLOWED_TABLES = {
    "cases", "documents", "emails", "historical_cases",
    "case_actuaciones", "compliance_tracking", "corte_revision",
    "directorio_correos", "audit_log",
}
ALLOWED_CASES_COLS = {
    "id", "radicado_23_digitos", "radicado_forest", "abogado_responsable",
    "accionante", "accionados", "vinculados", "derecho_vulnerado", "juzgado",
    "ciudad", "fecha_ingreso", "asunto", "pretensiones", "oficina_responsable",
    "estado", "sentido_fallo_1st", "fecha_fallo_1st", "impugnacion",
    "quien_impugno", "juzgado_2nd", "sentido_fallo_2nd", "fecha_fallo_2nd",
    "incidente", "fecha_apertura_incidente", "responsable_desacato",
    "decision_incidente",
    # Segundo y tercer incidente
    "incidente_2", "fecha_apertura_incidente_2", "responsable_desacato_2",
    "decision_incidente_2", "incidente_3", "fecha_apertura_incidente_3",
    "responsable_desacato_3", "decision_incidente_3",
    "categoria_tematica", "folder_name", "folder_path", "origen",
    "estado_incidente", "tipo_actuacion", "direccion", "grupo", "equipo",
    # v8.2 canonicals
    "abogado_canonical", "abogado_canonical_confidence",
    "dependencia_canonical", "dependencia_canonical_confidence",
    "fecha_respuesta", "observaciones", "processing_status",
    "entropy_score", "convergence_iterations", "pii_mode",
    "created_at", "updated_at",
}
SQL_HARD_LIMIT = 1000
SQL_TIMEOUT_MS = 5000


# ─── definiciones JSON Schema (formato OpenAI tools) ───────────────

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_similar_cases",
            "description": (
                "Busca tutelas semánticamente parecidas usando embeddings BGE-M3. "
                "Útil cuando el usuario pregunta por casos similares, precedentes "
                "o quiere comparar un caso actual con históricos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string",
                        "description": "Descripción del caso o pregunta libre"},
                    "k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                    "source": {"type": "string",
                        "enum": ["historical", "current", "mixed"], "default": "historical"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_cases",
            "description": (
                "Ejecuta una consulta SQL SELECT acotada sobre las tutelas en BD. "
                "Sólo SELECT. Tablas permitidas: cases, documents, emails, historical_cases. "
                "Útil para preguntas estructuradas (cuántas tutelas, filtros, agrupaciones)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string",
                        "description": "Query SQL SELECT. Ejemplo: SELECT COUNT(*) FROM cases WHERE LOWER(ciudad)='bucaramanga'"},
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_case",
            "description": "Devuelve detalles completos de un caso por su ID.",
            "parameters": {
                "type": "object",
                "properties": {"case_id": {"type": "integer"}},
                "required": ["case_id"],
            },
        },
    },
]


# ─── ejecutores ────────────────────────────────────────────────────

def tool_search_similar_cases(text: str, k: int = 5,
        source: str = "historical") -> dict:
    if source not in {"historical", "current", "mixed"}:
        return {"error": f"source inválido: {source}"}
    src = None if source == "mixed" else source

    # v8.2: intentar BGE-M3/FAISS primero; si no existe o falla, fallback TF-IDF
    bge_neigh = None
    try:
        from backend.ml.embeddings import search_similar
        bge_neigh = search_similar(text, k=min(int(k), 20), source_filter=src)
    except Exception:
        bge_neigh = None

    if bge_neigh:
        return {
            "neighbors": [
                {
                    "case_id": n.case_id, "source": n.source,
                    "score": round(n.score, 3),
                    "tema": n.tema, "dependencia": n.dependencia,
                    "direccion": n.direccion, "tipo": n.tipo, "fallo": n.fallo,
                    "preview": n.text_preview[:300],
                }
                for n in bge_neigh
            ],
        }

    # Fallback TF-IDF (CPU only, sin GPU/sentence-transformers)
    from backend.ml.embeddings.tfidf_index import search_by_text
    hits = search_by_text(text, k=min(int(k), 20), source=src)
    return {
        "neighbors": [
            {
                "case_id": h["case_id"], "source": h["source"],
                "score": round(h["similarity"], 3),
                "folder": h.get("folder"), "abogado": h.get("abogado"),
                "fallo": h.get("sentido_fallo"),
            }
            for h in hits
        ],
        "count": len(hits),
    }


def _validate_sql(sql: str) -> tuple[bool, str]:
    """Devuelve (ok, mensaje_o_sql_normalizado). Rechaza DML/DDL, valida tablas."""
    try:
        parsed = sqlglot.parse_one(sql, dialect="sqlite")
    except Exception as e:
        return False, f"SQL no parsea: {e}"

    if not isinstance(parsed, exp.Select):
        return False, "Sólo SELECT permitido"

    # Ningún DML/DDL anidado
    for node in parsed.walk():
        n = node[0] if isinstance(node, tuple) else node
        if isinstance(n, (exp.Insert, exp.Update, exp.Delete, exp.Drop,
                           exp.Create, exp.Alter, exp.TruncateTable)):
            return False, f"Operación prohibida: {type(n).__name__}"

    # Whitelist de tablas
    for tbl in parsed.find_all(exp.Table):
        if tbl.name not in ALLOWED_TABLES:
            return False, f"Tabla no permitida: {tbl.name}"

    # LIMIT forzado
    has_limit = parsed.find(exp.Limit) is not None
    if not has_limit:
        sql_with_limit = sql.rstrip(" ;\n") + f" LIMIT {SQL_HARD_LIMIT}"
        return True, sql_with_limit

    return True, sql


def tool_query_cases(sql: str) -> dict:
    ok, msg = _validate_sql(sql)
    if not ok:
        return {"error": msg, "sql": sql}
    final_sql = msg
    try:
        # v8.2: timeout 30s + busy_timeout WAL para tolerar concurrencia con uvicorn
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA query_only = ON")
        cur = conn.execute(final_sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = [dict(zip(cols, r)) for r in cur.fetchmany(SQL_HARD_LIMIT)]
        conn.close()
        return {"rows": rows, "row_count": len(rows), "sql": final_sql}
    except Exception as e:
        return {"error": f"Ejecución falló: {e}", "sql": final_sql}


def tool_get_case(case_id: int) -> dict:
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.row_factory = sqlite3.Row
        r = conn.execute(
            "SELECT * FROM cases WHERE id = ? LIMIT 1", (int(case_id),)
        ).fetchone()
        conn.close()
        if not r:
            return {"error": f"Caso {case_id} no existe"}
        return {k: r[k] for k in r.keys()}
    except Exception as e:
        return {"error": str(e)}


# ─── dispatch ──────────────────────────────────────────────────────

TOOL_FUNCS = {
    "search_similar_cases": tool_search_similar_cases,
    "query_cases": tool_query_cases,
    "get_case": tool_get_case,
}


def execute_tool(name: str, args: dict) -> dict:
    fn = TOOL_FUNCS.get(name)
    if not fn:
        return {"error": f"Tool desconocida: {name}"}
    try:
        return fn(**args)
    except TypeError as e:
        return {"error": f"Argumentos inválidos: {e}"}
    except Exception as e:
        logger.exception("Tool %s falló", name)
        return {"error": str(e)}
