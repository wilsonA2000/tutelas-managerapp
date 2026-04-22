"""Acuñación de tokens estables dentro del caso (v5.3).

Un token:
- Es **estable**: mismo valor normalizado dentro del mismo case_id → mismo token.
- Es **único entre casos**: mismo valor en case 1 y case 2 → tokens diferentes.
- Preserva **metadata estructural** (rol, orden, rango edad, región) sin contenido.
"""

from __future__ import annotations

import json
import re
import logging
from dataclasses import dataclass, field
from typing import Any

from backend.privacy.crypto import case_salt, value_hash

_logger = logging.getLogger("tutelas.privacy.tokens")


# ============================================================
# Helpers de metadata (extraen contexto para preservar sin PII)
# ============================================================

_DANE_REGIONS = {
    "bucaramanga": "REG_ORIENTE", "floridablanca": "REG_ORIENTE", "piedecuesta": "REG_ORIENTE",
    "giron": "REG_ORIENTE", "girón": "REG_ORIENTE", "barrancabermeja": "REG_MAGDALENA_MEDIO",
    "san gil": "REG_GUANENTA", "socorro": "REG_COMUNERA", "málaga": "REG_GARCIA_ROVIRA",
    "malaga": "REG_GARCIA_ROVIRA", "velez": "REG_VELEZ", "vélez": "REG_VELEZ",
}


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _dane_region(city: str) -> str:
    c = _normalize(city)
    for name, region in _DANE_REGIONS.items():
        if name in c:
            return region
    return "REG_OTRO"


def _last_n_digits(value: str, n: int = 4) -> str:
    digits = re.sub(r"\D", "", value)
    return digits[-n:] if len(digits) >= n else digits


def _age_range(age: int | None) -> str:
    if age is None:
        return "EDAD_DESCONOCIDA"
    if age <= 5:
        return "EDAD_0_5"
    if age <= 10:
        return "EDAD_6_10"
    if age <= 14:
        return "EDAD_11_14"
    if age <= 17:
        return "EDAD_15_17"
    return "EDAD_ADULTO"


def _cie10_family(dx: str) -> str:
    """G80.9 → G80; F20.1 → F20; C50 → C50."""
    m = re.search(r"([A-TV-Z]\d{2})", dx.upper())
    return m.group(1) if m else "DX_UNK"


# ============================================================
# Token catalog — estado por caso
# ============================================================

@dataclass
class TokenCatalog:
    """Estado vivo de tokens acuñados para un caso concreto.

    Se instancia por cada redacción (no singleton). No persiste solo —
    el redactor se encarga de persistir via `PiiMapping` tras acuñar.
    """
    case_id: int
    _counters: dict[str, int] = field(default_factory=dict)
    _by_hash: dict[str, str] = field(default_factory=dict)      # value_hash → token
    _mapping: dict[str, dict[str, Any]] = field(default_factory=dict)  # token → {value, kind, meta}

    def mint(self, kind: str, value: str, metadata: dict | None = None) -> str:
        """Acuña (o recupera si ya existe) el token para (kind, value) en este caso."""
        norm = _normalize(value)
        vh = value_hash(self.case_id, f"{kind}:{norm}")
        if vh in self._by_hash:
            return self._by_hash[vh]

        n = self._counters.get(kind, 0) + 1
        self._counters[kind] = n
        token = self._format_token(kind, n, value, metadata or {})

        self._by_hash[vh] = token
        self._mapping[token] = {
            "value": value,
            "kind": kind,
            "value_hash": vh,
            "meta": metadata or {},
        }
        return token

    def _format_token(self, kind: str, n: int, value: str, meta: dict) -> str:
        """Formato del token según kind. Preserva metadata estructural."""
        if kind == "CC":
            return f"[CC_####{_last_n_digits(value)}]"
        if kind == "NUIP":
            return f"[NUIP_MENOR_{n}]"
        if kind == "PHONE":
            is_mobile = bool(re.match(r"\s*3[0-5]\d", value))
            tag = "MOVIL" if is_mobile else "FIJO"
            return f"[TEL_{tag}]"
        if kind == "EMAIL":
            dom = value.split("@", 1)[-1].lower() if "@" in value else ""
            cat = "GOV" if dom.endswith(".gov.co") else ("EDU" if ".edu" in dom else "PERS")
            return f"[EMAIL_{cat}]"
        if kind == "ADDRESS_EXACT":
            city = meta.get("city", "")
            return f"[DIR_URBANA_{_dane_region(city).split('_', 1)[-1] if city else 'OTRO'}]"
        if kind == "PERSON":
            role = meta.get("role", "PERSONA")  # ACCIONANTE / ACCIONADO / ABOGADO / MENOR / PERSONA
            return f"[{role}_{n}]"
        if kind == "MINOR_RELATION":
            age = meta.get("age")
            parent_ref = meta.get("parent_token", "ACC_?")
            return f"[MENOR_{n}_{_age_range(age)}_HIJO_{parent_ref}]"
        if kind == "ORG_SENSITIVE":
            sector = meta.get("sector", "GEN")
            return f"[ORG_{sector}_{n}]"
        if kind == "DX_DETAIL":
            return f"[DX_{_cie10_family(value)}]"
        if kind == "RADICADO_FOREST":
            return f"[FOREST_INT_{n}]"
        if kind == "FOREST_IMPUGNACION":
            return f"[FOREST_IMPUG_{n}]"
        if kind == "COURT_EXACT":
            city = meta.get("city", "")
            level = meta.get("level", "MPAL")  # MPAL / CIRCUITO / TRIB / CSJ
            return f"[JUZGADO_{n}_{level}_{_dane_region(city).split('_', 1)[-1]}]"
        if kind == "CITY_EXACT":
            return f"[CIUDAD_{_dane_region(value)}]"
        if kind == "DATE_EXACT":
            # Parseo mínimo DD/MM/YYYY → trimestre
            m = re.search(r"(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{4})", value)
            if m:
                month = int(m.group(2))
                year = m.group(3)
                q = (month - 1) // 3 + 1
                return f"[FECHA_{year}_Q{q}]"
            return f"[FECHA_{n}]"
        # Default
        return f"[{kind}_{n}]"

    def mapping(self) -> dict[str, dict[str, Any]]:
        """Retorna token → {value, kind, value_hash, meta} para persistir."""
        return self._mapping
