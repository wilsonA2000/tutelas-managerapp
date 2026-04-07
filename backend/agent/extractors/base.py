"""Base class para extractores de campos individuales."""

from dataclasses import dataclass


@dataclass
class ExtractionResult:
    """Resultado de extracción de un campo."""
    value: str
    confidence: int  # 0-100
    source: str  # nombre del archivo/fuente
    method: str  # regex, ai, db, cross_validation
    reasoning: str  # explicación en español


class FieldExtractor:
    """Base class para extractores de campos individuales."""

    field_name: str = ""
    # Priority: cuál fuente se prefiere si hay conflicto
    # regex > ai para datos estructurados (FOREST, RADICADO)
    # ai > regex para datos semánticos (FALLO, ASUNTO)
    prefer_regex: bool = True

    def extract_regex(self, documents: list[dict], emails: list = None) -> ExtractionResult | None:
        """Extraer usando regex desde múltiples fuentes."""
        raise NotImplementedError

    def validate(self, value: str, context: dict = None) -> tuple[bool, str]:
        """Validar un valor extraído. Returns (is_valid, reason)."""
        return bool(value and value.strip()), "Empty value" if not value else "OK"

    def resolve_conflict(self, regex_result: ExtractionResult | None,
                          ai_result: ExtractionResult | None) -> ExtractionResult | None:
        """Resolver conflicto entre resultado regex y resultado IA."""
        if not regex_result and not ai_result:
            return None
        if not regex_result:
            return ai_result
        if not ai_result:
            return regex_result

        # Same value = boost confidence
        if regex_result.value.strip() == ai_result.value.strip():
            return ExtractionResult(
                value=regex_result.value,
                confidence=min(100, max(regex_result.confidence, ai_result.confidence) + 15),
                source=f"{regex_result.source} + {ai_result.source}",
                method="cross_validated",
                reasoning=f"Regex y IA coinciden: '{regex_result.value}'",
            )

        # Conflict: use preference
        if self.prefer_regex:
            winner = regex_result
            loser = ai_result
            winner.reasoning = f"Preferencia regex sobre IA. Regex: '{regex_result.value}', IA: '{ai_result.value}'"
        else:
            winner = ai_result
            loser = regex_result
            winner.reasoning = f"Preferencia IA sobre regex. IA: '{ai_result.value}', Regex: '{regex_result.value}'"

        return winner
