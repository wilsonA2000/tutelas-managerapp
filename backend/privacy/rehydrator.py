"""Rehidratación: token → valor real (v5.3).

Corre tras recibir la respuesta de IA, antes de persistir/mostrar al operador.
Consulta la tabla `pii_mappings` por (case_id, token) y descifra el valor.
"""

from __future__ import annotations

import logging
import re

from backend.privacy.crypto import decrypt

_logger = logging.getLogger("tutelas.privacy.rehydrator")

# Match cualquier [TOKEN_...] con letras, dígitos, underscores.
_TOKEN_PATTERN = re.compile(r"\[[A-Z][A-Z0-9_#]*\]")


def _lookup_token(db, case_id: int, token: str) -> str | None:
    """Busca un token en pii_mappings. Retorna valor descifrado o None."""
    from backend.database.models import PiiMapping
    pm = db.query(PiiMapping).filter_by(case_id=case_id, token=token).first()
    if not pm:
        return None
    try:
        return decrypt(pm.value_encrypted)
    except RuntimeError as e:
        _logger.warning("No pude descifrar token %s del caso %s: %s", token, case_id, e)
        return None


def rehydrate_text(db, case_id: int, text: str) -> str:
    """Reemplaza todos los tokens `[...]` en un texto por sus valores originales.

    Tokens no encontrados en pii_mappings se dejan intactos (podrían ser
    contenido legítimo entre corchetes o tokens de otro caso).
    """
    if not text or "[" not in text:
        return text

    def _sub(match):
        tok = match.group(0)
        value = _lookup_token(db, case_id, tok)
        return value if value is not None else tok

    return _TOKEN_PATTERN.sub(_sub, text)


def rehydrate_fields(db, case_id: int, fields: dict) -> dict:
    """Rehidrata valores string dentro de un dict de campos extraídos.

    Preserva la estructura (fields puede ser dict anidado con {value, confidence, source}).
    """
    if not fields:
        return fields

    def _walk(node):
        if isinstance(node, dict):
            return {k: _walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(x) for x in node]
        if isinstance(node, str):
            return rehydrate_text(db, case_id, node)
        return node

    return _walk(fields)
