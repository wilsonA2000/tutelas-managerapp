"""Contrato I/O para el LLM compilador.

Implementa el contrato documentado en docs/iuris/SYSTEM_PROMPT_COMPILER.md:

- compute_holes: campos del protocolo de 28 sin llenar tras las capas previas
- gather_evidence: chunks textuales relevantes por hueco (≤ 1500 chars)
- build_compiler_payload: arma el JSON que el LLM espera como user message

Reemplaza el patrón legacy de mandar texto plano completo al LLM (que ignora
las 6 capas deterministas upstream y obliga al modelo a re-extraer 28 campos).
"""
from __future__ import annotations

import re
from typing import Any


# Campos del protocolo (lowercase, atributos del modelo Case).
PROTOCOL_FIELDS: list[str] = [
    "accionante", "accionados", "vinculados",
    "radicado_23_digitos", "radicado_forest", "abogado_responsable",
    "derecho_vulnerado", "juzgado", "ciudad",
    "fecha_ingreso", "asunto", "pretensiones",
    "oficina_responsable", "estado", "fecha_respuesta",
    "sentido_fallo_1st", "fecha_fallo_1st",
    "impugnacion", "quien_impugno", "forest_impugnacion",
    "juzgado_2nd", "sentido_fallo_2nd", "fecha_fallo_2nd",
    "incidente", "fecha_apertura_incidente",
    "responsable_desacato", "decision_incidente",
    "observaciones",
]


# Filtros por tipo de documento — para huecos donde solo ciertos doc_type
# son fuente válida (evita contaminación de otros docs).
DOC_TYPE_FILTERS: dict[str, set[str]] = {
    "abogado_responsable": {
        "DOCX_RESPUESTA", "DOCX_DESACATO", "DOCX_IMPUGNACION",
        "DOCX_CUMPLIMIENTO",
    },
    "responsable_desacato": {
        "DOCX_RESPUESTA", "DOCX_DESACATO", "DOCX_CUMPLIMIENTO",
    },
    "fecha_respuesta": {
        "DOCX_RESPUESTA", "DOCX_DESACATO",
    },
}


# Marcadores de evidencia tomados directamente de SYSTEM_PROMPT_COMPILER.md
# (líneas 70-180 del corpus auditado SED 2026-05-03). El gather extrae
# chunks de ±200/+500 chars alrededor de cada match.
EVIDENCE_PATTERNS: dict[str, list[str]] = {
    "forest_impugnacion": [
        # Format específico SED: 11 dígitos en contexto del email de Atención
        # Ciudadano. Evitar matchear el radicado_23_digitos (21 dígitos consecutivos).
        r"Recibido\s+y\s+enviado\s+a\s+TUTELAS.{0,120}\d{11}\b",
        r"radicado\s+N[ºo°.]?\s*\d{11}\b(?!\d)",
        r"con\s+(?:el\s+)?n[úu]mero\s+de\s+radicado\s+\d{11}\b(?!\d)",
    ],
    "responsable_desacato": [
        r"PROYECT[ÓO]:\s*[^\n]{3,80}",
        r"Proyecto:\s*[^\n]{3,80}",
        r"APROB[ÓO]:\s*[^\n]{3,80}",
        r"REQUERIR[ÁA]\s+a\s+la\s+(?:Dra?|Sr[a]?)\.?\s+[^\n]{3,60}",
    ],
    "abogado_responsable": [
        # Mismos marcadores; doc_type filter limita a DOCX_RESPUESTA y similares.
        r"PROYECT[ÓO]:\s*[^\n]{3,80}",
        r"Proyecto:\s*[^\n]{3,80}",
        r"APROB[ÓO]:\s*[^\n]{3,80}\s*L[ÍI]DER",
        r"Abogad[oa]\s+(?:Esp[\.\-]?\s*)?(?:Contratista|Planta)?\s*[A-ZÁÉÍÓÚÑ][^\n]{3,60}",
    ],
    "fecha_respuesta": [
        r"Bucaramanga[,\s]+\d{1,2}\s+de\s+\w+\s+de\s+\d{4}",
        r"Fecha:\s*\d{1,2}/\d{1,2}/\d{4}",
        r"\b\d{1,2}/\d{1,2}/\d{4}",
    ],
    "decision_incidente": [
        r"declarar\s+terminado\s+el\s+incidente",
        r"sancionar\s+con\s+\d+\s+d[íi]as\s+de\s+arresto",
        r"abstenerse\s+de\s+continuar",
        r"archivar\s+por\s+carencia",
        r"instar\s+a\s+la\s+Gobernaci[óo]n",
        r"requerimiento\s+previo\s+(?:de\s+)?incidente",
    ],
    "fecha_apertura_incidente": [
        r"INCIDENTE\s+DE\s+DESACATO\s+DE\s+TUTELA",
        r"Desde\s+personeria@",
        r"Fecha\s+\w+\s+\d{1,2}/\d{1,2}/\d{4}",
    ],
    "sentido_fallo_1st": [
        r"\bRESUELVE\b.{0,500}",
        r"\bFALLA\b.{0,500}",
        r"(TUTELAR|CONCEDER|AMPARAR|PROTEGER|NEGAR|DENEGAR|IMPROCEDENTE)\b",
    ],
    "sentido_fallo_2nd": [
        r"(CONFIRMA|REVOCA|MODIFICA)\s+(?:la\s+)?(?:sentencia|fallo|decisi[óo]n)",
        r"Tribunal\s+Superior",
    ],
    "fecha_fallo_1st": [
        r"\bBucaramanga[,\s]+\d{1,2}\s+de\s+\w+\s+de\s+\d{4}",
        r"\bRESUELVE\b.{0,200}\d{1,2}/\d{1,2}/\d{4}",
        r"\b\d{1,2}\s+de\s+\w+\s+de\s+\d{4}",
    ],
    "fecha_fallo_2nd": [
        r"Tribunal.{0,200}\d{1,2}\s+de\s+\w+\s+de\s+\d{4}",
        r"Sala.{0,200}\d{1,2}/\d{1,2}/\d{4}",
    ],
    "juzgado_2nd": [
        r"JUZGADO\s+\w+\s+PENAL\s+DEL\s+CIRCUITO[^\n]{0,80}",
        r"TRIBUNAL\s+SUPERIOR\s+(?:DE\s+|DISTRITO\s+JUDICIAL\s+)\w[^\n]{0,80}",
        r"SALA\s+(?:CIVIL|PENAL|FAMILIA|LABORAL)[^\n]{0,80}",
    ],
    "quien_impugno": [
        r"impugna(?:ci[óo]n)?\s+(?:presentad[ao]|interpuesto)\s+por\s+[^\n]{3,80}",
        r"^Accionante:\s*[^\n]{3,80}",
        r"impugnaci[óo]n\s+del?\s+(accionante|accionado|ministerio\s+p[úu]blico)",
        r"recurso\s+de\s+impugnaci[óo]n",
    ],
    "categoria_tematica": [
        r"SIMAT",
        r"docente.{0,50}reintegr",
        r"aula\s+inclusiva",
        r"transporte\s+escolar",
        r"cupo\s+escolar",
        r"alimentaci[óo]n\s+escolar",
        r"PAE\b",
        r"infraestructura\s+(?:educativa|escolar)",
    ],
    "asunto": [
        r"PRETENSIONES?[:\s]+",
        r"objeto\s+de\s+la\s+(?:tutela|acci[óo]n)",
        r"solicit[ao]\s+(?:que|al\s+juez)",
    ],
    "pretensiones": [
        r"PRETENSIONES?[:\s]+",
        r"AMPARO[:\s]+",
        r"ORDENAR\s+a",
        r"PRIMERO[:\s]+TUTELAR",
    ],
    "derecho_vulnerado": [
        r"derechos?\s+fundamentales?\s+(?:a\s+|de\s+)?(?:la\s+|los\s+)?(?:salud|educaci[óo]n|vida|petici[óo]n|debido\s+proceso|igualdad|dignidad)",
        r"vulneraci[óo]n\s+de\s+(?:los?\s+)?derechos?",
        r"protecci[óo]n\s+(?:de\s+)?derechos?",
    ],
    "accionados": [
        r"ACCIONAD[OA]S?[:\s]+[^\n]{3,150}",
        r"contra\s+(?:la\s+)?(?:Gobernaci[óo]n|Secretar[íi]a|Ministerio)",
    ],
    "accionante": [
        r"ACCIONANTE[:\s]+[^\n]{3,100}",
        r"(?:identificad[ao]|portador[a]?)\s+con\s+(?:c[ée]dula|c\.\s*c\.)",
        r"PERSONERO\s+MUNICIPAL\s+DE\s+\w+",
    ],
    "fecha_ingreso": [
        r"AUTO\s+ADMISORIO[^\n]{0,100}\d{1,2}/\d{1,2}/\d{4}",
        r"avocando\s+conocimiento[^\n]{0,100}\d{1,2}",
    ],
    "ciudad": [
        r"municipio\s+de\s+\w+",
        r"Personero[a]?\s+(?:Municipal\s+)?de\s+\w+",
    ],
}


def _value_is_filled(v: Any) -> bool:
    """Considera vacío: None, '', whitespace, 'null', 'none', 'n/a', 'no aplica'."""
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip().lower() not in ("", "null", "none", "n/a", "no aplica", "n.a.")
    if hasattr(v, "value"):
        inner = getattr(v, "value", None)
        return _value_is_filled(inner)
    return bool(v)


def compute_holes(known_fields: dict[str, Any]) -> list[str]:
    """Devuelve campos del protocolo que aún no están llenos."""
    return [f for f in PROTOCOL_FIELDS if not _value_is_filled(known_fields.get(f))]


def gather_evidence(
    documents: list[dict],
    holes: list[str],
    max_chars: int = 1500,
    chunks_per_hole: int = 2,
) -> str:
    """Para cada hueco, busca patrones en los docs y extrae chunks de contexto.

    Args:
        documents: lista de {filename, text|content, doc_type?}
        holes: campos a llenar
        max_chars: tope total del bloque de evidencia (≤1500 según .md)
        chunks_per_hole: cuántos chunks máximo por hueco

    Returns:
        Bloque de texto con chunks etiquetados [hole | filename] separados por ---.
        Cadena vacía si no hay matches.
    """
    chunks: list[tuple[str, str, str]] = []
    seen_keys: set[str] = set()

    for hole in holes:
        patterns = EVIDENCE_PATTERNS.get(hole, [])
        if not patterns:
            continue
        allowed_types = DOC_TYPE_FILTERS.get(hole)  # None = todos
        per_hole_count = 0
        for doc in documents:
            if per_hole_count >= chunks_per_hole:
                break
            # Filtro por doc_type cuando aplica (anti-contaminación)
            if allowed_types is not None:
                if doc.get("doc_type") not in allowed_types:
                    continue
            text = (doc.get("text") or doc.get("content") or "")
            if not text:
                continue
            filename = doc.get("filename", "?")
            for pat in patterns:
                if per_hole_count >= chunks_per_hole:
                    break
                try:
                    for m in re.finditer(pat, text, re.I | re.M):
                        start = max(0, m.start() - 200)
                        end = min(len(text), m.end() + 500)
                        snippet = text[start:end].strip()
                        # Dedup por primeros 60 chars del snippet
                        key = snippet[:60].lower()
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        chunks.append((hole, filename, snippet))
                        per_hole_count += 1
                        if per_hole_count >= chunks_per_hole:
                            break
                except re.error:
                    continue

    # Ensamblar respetando max_chars
    formatted: list[str] = []
    total = 0
    for hole, fname, snippet in chunks:
        block = f"[{hole} | {fname}]\n{snippet}"
        if total + len(block) + 5 > max_chars:
            # truncar el último para llenar al máximo
            remaining = max_chars - total - 5
            if remaining > 100:
                formatted.append(block[:remaining] + "...")
            break
        formatted.append(block)
        total += len(block) + 5

    return "\n---\n".join(formatted)


def serialize_known_fields(known_fields: dict[str, Any]) -> dict[str, Any]:
    """Convierte known_fields (que pueden ser ExtractionResult o str) a JSON-friendly."""
    out: dict[str, Any] = {}
    for k, v in known_fields.items():
        if hasattr(v, "value"):
            entry: dict[str, Any] = {"value": getattr(v, "value", None)}
            conf = getattr(v, "confidence", None)
            if conf is not None:
                entry["confidence"] = conf
            src = getattr(v, "source", "")
            if src:
                entry["source"] = src
            out[k] = entry
        elif v is None or v == "":
            continue
        else:
            out[k] = {"value": str(v)}
    return out


def build_compiler_payload(
    known_fields: dict[str, Any],
    documents: list[dict],
    folder_name: str = "",
    radicado_oficial: str = "",
    metadata_extra: dict[str, Any] | None = None,
    evidence_max_chars: int = 1500,
) -> dict[str, Any]:
    """Construye el payload JSON del contrato compilador (SYSTEM_PROMPT_COMPILER.md)."""
    holes = compute_holes(known_fields)

    metadata: dict[str, Any] = {
        "folder_name": folder_name,
        "radicado_oficial": radicado_oficial or _extract_value(known_fields.get("radicado_23_digitos")),
        "tiene_incidente": _extract_value(known_fields.get("incidente")) == "SI",
        "tiene_fallo_1st": _value_is_filled(known_fields.get("sentido_fallo_1st")),
        "tiene_fallo_2nd": _value_is_filled(known_fields.get("sentido_fallo_2nd")),
        "doc_count": len(documents),
    }
    if metadata_extra:
        metadata.update(metadata_extra)

    return {
        "campos_extraidos": serialize_known_fields(known_fields),
        "campos_huecos": holes,
        "evidencia_textual": gather_evidence(documents, holes, max_chars=evidence_max_chars),
        "metadata": metadata,
    }


def _extract_value(v: Any) -> str:
    """Extrae .value de ExtractionResult o devuelve str directo."""
    if v is None:
        return ""
    if hasattr(v, "value"):
        return str(getattr(v, "value", "") or "")
    return str(v)


# ============================================================
# Post-validators determinísticos (reglas del .md SED corpus)
# ============================================================

def infer_quien_impugno(known_fields: dict[str, Any]) -> str | None:
    """Inferencia procesal de `quien_impugno` (líneas 101-107 del .md).

    Reglas (corpus SED auditado):
    - fallo_1st = NIEGA o IMPROCEDENTE → ACCIONANTE
    - fallo_1st = CONCEDE → ACCIONADO

    Returns: valor inferido (str) o None si no aplica.
    """
    impug = _extract_value(known_fields.get("impugnacion")).upper().strip()
    if impug != "SI":
        return None  # Solo si hay impugnación
    existing = _extract_value(known_fields.get("quien_impugno")).strip()
    if existing:
        return None  # No sobreescribir
    fallo = _extract_value(known_fields.get("sentido_fallo_1st")).upper()
    if not fallo:
        return None
    if "CONCEDE" in fallo or "AMPARA" in fallo or "TUTELAR" in fallo:
        return "ACCIONADO"
    if "NIEGA" in fallo or "IMPROCEDENTE" in fallo or "DENEGAR" in fallo:
        return "ACCIONANTE"
    return None


def apply_post_validators(
    fields: dict[str, Any], known_fields: dict[str, Any]
) -> dict[str, Any]:
    """Aplica reglas determinísticas post-LLM. Mutates `fields` y retorna inferencias nuevas.

    Args:
        fields: campos resultantes (incluyendo los del LLM)
        known_fields: pre-existentes que el LLM recibió

    Returns:
        dict de campos inferidos (subset, solo nuevos).
    """
    inferred: dict[str, str] = {}
    # Combinar known + fields recién extraídos para razonar
    merged = {**known_fields, **fields}

    # quien_impugno
    qi = infer_quien_impugno(merged)
    if qi and not _extract_value(fields.get("quien_impugno")):
        inferred["quien_impugno"] = qi

    return inferred
