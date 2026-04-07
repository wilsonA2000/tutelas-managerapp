"""Extractor de radicados judiciales (23 dígitos y corto)."""

import re
from backend.agent.extractors.base import FieldExtractor, ExtractionResult
from backend.agent.regex_library import (
    RAD_23_CONTINUOUS, RAD_23_WITH_SEPARATORS, RAD_T_FORMAT, RAD_LABEL, RAD_GENERIC,
)


class RadicadoExtractor(FieldExtractor):
    field_name = "radicado_23_digitos"
    prefer_regex = True  # Radicado is structured data

    def extract_regex(self, documents: list[dict], emails: list = None) -> ExtractionResult | None:
        # Priority: auto admisorio > sentencia > other docs
        for doc in sorted(documents, key=lambda d: d.get("priority", 5)):
            text = doc.get("content", "") or doc.get("text", "")
            if not text:
                continue

            # Pattern 1: Continuous 23 digits
            m = RAD_23_CONTINUOUS.pattern.search(text)
            if m:
                rad = m.group(1)
                if len(rad) >= 20:
                    return ExtractionResult(
                        value=rad, confidence=90,
                        source=doc.get("filename", ""),
                        method="regex", reasoning=f"Radicado 23 dígitos continuo en {doc.get('filename', '')}"
                    )

            # Pattern 2: With separators
            m = RAD_23_WITH_SEPARATORS.pattern.search(text)
            if m:
                return ExtractionResult(
                    value=m.group(1), confidence=85,
                    source=doc.get("filename", ""),
                    method="regex", reasoning=f"Radicado con separadores en {doc.get('filename', '')}"
                )

        # Check emails
        for em in (emails or []):
            body = getattr(em, 'body_preview', '') or getattr(em, 'body', '') or ''
            subject = getattr(em, 'subject', '') or ''
            combined = subject + " " + body

            m = RAD_23_CONTINUOUS.pattern.search(combined)
            if m and len(m.group(1)) >= 20:
                return ExtractionResult(
                    value=m.group(1), confidence=80,
                    source=f"email: {subject[:50]}",
                    method="regex", reasoning=f"Radicado 23d en email '{subject[:50]}'"
                )

            m = RAD_23_WITH_SEPARATORS.pattern.search(combined)
            if m:
                return ExtractionResult(
                    value=m.group(1), confidence=75,
                    source=f"email: {subject[:50]}",
                    method="regex", reasoning=f"Radicado con separadores en email"
                )

        return None

    def validate(self, value: str, context: dict = None) -> tuple[bool, str]:
        if not value:
            return False, "Empty"
        clean = re.sub(r'[\s\-\.]', '', value)
        if not clean.startswith('68'):
            return False, f"Radicado debe empezar con 68 (Santander), got: {clean[:5]}"
        if len(clean) < 20:
            return False, f"Radicado muy corto: {len(clean)} dígitos (mínimo 20)"
        return True, "OK"


class RadicadoCortoExtractor(FieldExtractor):
    """Extrae radicado corto YYYY-NNNNN del folder name o documentos."""
    field_name = "radicado_corto"
    prefer_regex = True

    def extract_regex(self, documents: list[dict], emails: list = None) -> ExtractionResult | None:
        for doc in documents:
            text = doc.get("content", "") or doc.get("text", "")
            if not text:
                continue

            # T format
            m = RAD_T_FORMAT.pattern.search(text)
            if m:
                corto = f"{m.group(2)}-{m.group(1).zfill(5)}"
                return ExtractionResult(
                    value=corto, confidence=85,
                    source=doc.get("filename", ""),
                    method="regex", reasoning=f"Formato T en {doc.get('filename', '')}"
                )

            # RAD label
            m = RAD_LABEL.pattern.search(text)
            if m:
                corto = f"{m.group(1)}-{m.group(2).zfill(5)}"
                return ExtractionResult(
                    value=corto, confidence=80,
                    source=doc.get("filename", ""),
                    method="regex", reasoning=f"Etiqueta RAD en {doc.get('filename', '')}"
                )

        return None
