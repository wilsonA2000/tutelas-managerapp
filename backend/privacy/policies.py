"""Políticas de qué tipos de PII redactar por modo (v5.3)."""

from typing import Literal

Mode = Literal["selective", "aggressive"]

# Identificadores numéricos únicos — siempre redactar. Re-identifican por
# cruce con bases externas (Registraduría, EPS, operadores telefónicos).
SELECTIVE_KINDS: frozenset[str] = frozenset({
    "CC",              # cédula adulto
    "NUIP",            # registro civil menor
    "PHONE",           # móvil / fijo
    "EMAIL",
    "ADDRESS_EXACT",   # calle #número
})

# Modo agresivo añade contenido semántico identificable por narrativa
# (nombres propios, diagnósticos específicos, radicados internos).
AGGRESSIVE_KINDS: frozenset[str] = SELECTIVE_KINDS | frozenset({
    "PERSON",               # nombres propios (accionante/menor/abogado)
    "ORG_SENSITIVE",        # IPS/EPS/colegio específico
    "DX_DETAIL",            # CIE-10 detalle (G80.9 → G80 solo)
    "RADICADO_FOREST",
    "FOREST_IMPUGNACION",
    "MINOR_RELATION",       # relaciones familiares con detalle
    "DATE_EXACT",           # fechas exactas sensibles → trimestre
    "CITY_EXACT",           # ciudad → región DANE
    "COURT_EXACT",          # juzgado específico → jerarquía + sede
})


def should_redact(kind: str, mode: Mode) -> bool:
    """Decide si un span debe tokenizarse según el modo activo."""
    if mode == "aggressive":
        return kind in AGGRESSIVE_KINDS
    return kind in SELECTIVE_KINDS
