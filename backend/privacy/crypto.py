"""Cifrado de valores PII en tabla pii_mappings (v5.3).

Usa Fernet (AES-128-CBC + HMAC-SHA256). La key se toma de settings.PII_MASTER_KEY.
Si está vacía y PII_REDACTION_ENABLED=True, auto-genera una key efímera en memoria
con warning — los mapeos persistidos no podrán rehidratarse en siguiente arranque.
"""

import hashlib
import hmac
import logging
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from backend.core.settings import settings

_logger = logging.getLogger("tutelas.privacy.crypto")

_EPHEMERAL_KEY: bytes | None = None


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    global _EPHEMERAL_KEY
    key = settings.PII_MASTER_KEY.strip()
    if not key:
        if _EPHEMERAL_KEY is None:
            _EPHEMERAL_KEY = Fernet.generate_key()
            _logger.warning(
                "PII_MASTER_KEY vacía. Usando key efímera en memoria — "
                "mapeos no sobrevivirán reinicio. Configura PII_MASTER_KEY en .env."
            )
        return Fernet(_EPHEMERAL_KEY)
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as e:
        raise RuntimeError(f"PII_MASTER_KEY inválida (debe ser Fernet key base64): {e}")


def encrypt(value: str) -> bytes:
    """Cifra un valor string a bytes (para persistir en LargeBinary)."""
    return _get_fernet().encrypt(value.encode("utf-8"))


def decrypt(blob: bytes) -> str:
    """Descifra bytes a string. Lanza RuntimeError si la key cambió."""
    try:
        return _get_fernet().decrypt(blob).decode("utf-8")
    except InvalidToken as e:
        raise RuntimeError("No se puede descifrar (key rotó o datos corruptos)") from e


def value_hash(case_id: int, value: str) -> str:
    """HMAC-SHA256(case_salt, normalized_value) — hex truncado 24 chars.

    Permite lookup O(1) por (case_id, token) sin descifrar. No reversible.
    """
    key = settings.PII_MASTER_KEY.strip().encode() or (_EPHEMERAL_KEY or b"fallback")
    salt = hmac.new(key, str(case_id).encode(), hashlib.sha256).digest()
    h = hmac.new(salt, value.strip().lower().encode("utf-8"), hashlib.sha256).hexdigest()
    return h[:24]


def case_salt(case_id: int) -> bytes:
    """Salt determinístico por caso, usado por tokens.mint_token para unicidad."""
    key = settings.PII_MASTER_KEY.strip().encode() or (_EPHEMERAL_KEY or b"fallback")
    return hmac.new(key, str(case_id).encode(), hashlib.sha256).digest()
