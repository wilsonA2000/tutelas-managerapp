"""Capa de anonimización PII (v5.3).

Flujo:
    1. `detectors` localizan spans PII (Presidio ES + regex propios + blacklist del caso).
    2. `policies` filtran qué kinds redactar según modo (selective | aggressive).
    3. `tokens` acuñan placeholders estables dentro del caso (HMAC + contador).
    4. `redactor` reemplaza spans → tokens en el payload que sale a IA externa.
    5. `zero_pii_gate` valida que no quede PII literal tras redactar; si queda, bloquea.
    6. `rehydrator` mapea tokens → valores reales tras la respuesta IA, para
       persistir y mostrar al operador (que está autorizado a ver datos crudos).
"""

from backend.privacy.redactor import redact_payload, RedactionContext, RedactedPayload
from backend.privacy.rehydrator import rehydrate_text, rehydrate_fields
from backend.privacy.zero_pii_gate import assert_clean, Violation

__all__ = [
    "redact_payload",
    "RedactionContext",
    "RedactedPayload",
    "rehydrate_text",
    "rehydrate_fields",
    "assert_clean",
    "Violation",
]
