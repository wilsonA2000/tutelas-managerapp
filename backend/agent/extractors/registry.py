"""Registry de extractores: mapea campos a sus extractores."""

from backend.agent.extractors.base import FieldExtractor, ExtractionResult
from backend.agent.extractors.radicado import RadicadoExtractor, RadicadoCortoExtractor
from backend.agent.extractors.campos import (
    FechaExtractor, JuzgadoExtractor, CiudadExtractor,
    ImpugnacionExtractor, IncidenteExtractor,
    SentidoFalloExtractor, AccionanteExtractor,
)
from backend.agent.forest_extractor import extract_forest_from_sources, ForestResult


# Extractor instances
_EXTRACTORS: dict[str, FieldExtractor] = {
    "radicado_23_digitos": RadicadoExtractor(),
    "radicado_corto": RadicadoCortoExtractor(),
    # --- Extractores IR (Fase 2) ---
    "accionante": AccionanteExtractor(),
    "juzgado": JuzgadoExtractor(),
    "ciudad": CiudadExtractor(),
    "fecha_ingreso": FechaExtractor("fecha_ingreso", ["PDF_AUTO_ADMISORIO"]),
    "fecha_fallo_1st": FechaExtractor("fecha_fallo_1st", ["PDF_SENTENCIA"]),
    "fecha_fallo_2nd": FechaExtractor("fecha_fallo_2nd", ["PDF_IMPUGNACION"]),
    "fecha_respuesta": FechaExtractor("fecha_respuesta", ["DOCX_RESPUESTA", "DOCX_CONTESTACION"]),
    "impugnacion": ImpugnacionExtractor(),
    "incidente": IncidenteExtractor(),
    "sentido_fallo_1st": SentidoFalloExtractor("sentido_fallo_1st", ["PDF_SENTENCIA"]),
    "sentido_fallo_2nd": SentidoFalloExtractor("sentido_fallo_2nd", ["PDF_IMPUGNACION"]),
}

# Fields where AI is preferred over regex
AI_PREFERRED_FIELDS = {
    "accionante", "accionados", "vinculados", "derecho_vulnerado",
    "juzgado", "ciudad", "asunto", "pretensiones", "observaciones",
    "sentido_fallo_1st", "sentido_fallo_2nd", "decision_incidente",
    "oficina_responsable", "abogado_responsable",
}

# Fields where regex is preferred over AI
REGEX_PREFERRED_FIELDS = {
    "radicado_23_digitos", "radicado_forest", "forest_impugnacion",
    "fecha_ingreso", "fecha_fallo_1st", "fecha_fallo_2nd",
    "fecha_respuesta", "fecha_apertura_incidente",
    "impugnacion", "incidente",
}


def pre_extract_all(doc_texts: list[dict], case_emails: list = None) -> dict[str, ExtractionResult]:
    """Ejecutar todos los extractores regex antes de llamar a IA.

    Returns: dict field_name -> ExtractionResult para campos que se pudieron extraer.
    """
    results = {}

    # Run registered extractors
    for field_name, extractor in _EXTRACTORS.items():
        try:
            result = extractor.extract_regex(doc_texts, case_emails)
            if result:
                is_valid, reason = extractor.validate(result.value)
                if is_valid:
                    results[field_name] = result
        except Exception:
            pass

    # FOREST extractor (special: uses its own module)
    forest = extract_forest_from_sources(doc_texts, case_emails)
    if forest:
        results["radicado_forest"] = ExtractionResult(
            value=forest.value,
            confidence=forest.confidence if isinstance(forest.confidence, int) else 90,
            source=forest.source,
            method="regex",
            reasoning=f"FOREST extraído de {forest.source} con confianza {forest.confidence}",
        )

    return results


def resolve_field(field_name: str, regex_result: ExtractionResult | None,
                   ai_result: ExtractionResult | None) -> ExtractionResult | None:
    """Resolver cuál valor usar para un campo: regex vs IA."""
    if not regex_result and not ai_result:
        return None
    if not regex_result:
        return ai_result
    if not ai_result:
        return regex_result

    # Same value = confirmed
    r_clean = regex_result.value.strip().upper()
    a_clean = ai_result.value.strip().upper()
    if r_clean == a_clean or r_clean in a_clean or a_clean in r_clean:
        return ExtractionResult(
            value=regex_result.value,
            confidence=min(100, max(regex_result.confidence, ai_result.confidence) + 15),
            source=f"{regex_result.source} + {ai_result.source}",
            method="cross_validated",
            reasoning=f"Regex y IA coinciden: '{regex_result.value}'",
        )

    # Conflict: use field preference
    if field_name in REGEX_PREFERRED_FIELDS:
        return ExtractionResult(
            value=regex_result.value,
            confidence=regex_result.confidence,
            source=regex_result.source,
            method="regex_preferred",
            reasoning=f"Campo '{field_name}': preferencia regex. Regex='{regex_result.value}', IA='{ai_result.value}'",
        )
    else:
        return ExtractionResult(
            value=ai_result.value,
            confidence=ai_result.confidence,
            source=ai_result.source,
            method="ai_preferred",
            reasoning=f"Campo '{field_name}': preferencia IA. IA='{ai_result.value}', Regex='{regex_result.value}'",
        )
