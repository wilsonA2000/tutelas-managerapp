"""Utilidades canónicas para radicados judiciales (v5.4.3).

Problema raíz que resuelve:
    El monitor Gmail creaba duplicados cuando RAD_GENERIC capturaba secuencias
    cortas (3-4 dígitos) y las zfill-eaba a 5. Ejemplo: email menciona "2026-1002"
    → rad_corto = "2026-01002", pero el rad23 oficial del caso tiene secuencia
    "10021" → no matchea → caso duplicado.

Invariantes:
    - rad23 canónico: 20 dígitos (5 dept + 2 ent + 2 esp + 2 subesp + 4 año + 5 seq)
    - rad_corto canónico: "AAAA-NNNNN" con secuencia de 5 dígitos (zfill solo si ≥5 crudos)
    - Si rad23 y rad_corto co-existen, el corto DEBE derivar del 23.
"""

from __future__ import annotations

import re

_ONLY_DIGITS = re.compile(r"[^0-9]")
_RAD23_TAIL = re.compile(r"(20\d{2})(\d{5})\d{2}$")
_RAD_CORTO_SHAPE = re.compile(r"^(20\d{2})-(\d{5})$")


def normalize_rad23(raw: str | None) -> str:
    """Devuelve solo los dígitos del rad23 (sin separadores)."""
    if not raw:
        return ""
    return _ONLY_DIGITS.sub("", raw)


def is_valid_rad23(raw: str | None) -> bool:
    """Un rad23 es válido si tiene ≥18 dígitos (algunos sistemas usan 20, otros 22)."""
    return len(normalize_rad23(raw)) >= 18


def derive_rad_corto_from_rad23(rad23: str | None) -> str:
    """Extrae 'AAAA-NNNNN' de los últimos 7 dígitos del rad23 (AAAA + NNNNN + 2 chequeo).

    Ejemplo: '54001410500220261002100' → año 2026, seq 10021 → '2026-10021'.

    v6.0.1: fallback para rad23 truncado a 21 dígitos (falta el '-00' de instancia)
    común en subjects de emails: "RAD 681904089002202600069" → año 2026, seq 00069.

    Retorna '' si el rad23 no tiene shape reconocible.
    """
    digits = normalize_rad23(rad23)
    if len(digits) < 11:
        return ""
    # Shape canónico: ...YYYY+5d+2d al final (23d completos)
    m = _RAD23_TAIL.search(digits)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    # v6.0.1: rad23 truncado (21d sin sufijo de instancia): YYYY+5d al final
    m2 = re.search(r"(20\d{2})(\d{5})$", digits)
    if m2:
        return f"{m2.group(1)}-{m2.group(2)}"
    return ""


def canonical_rad_corto(raw: str | None, min_digits: int = 4) -> str:
    """Normaliza un rad_corto capturado a 'AAAA-NNNNN'.

    Args:
        raw: string tipo '2026-1002', '2026 10021', 'RAD 2026-53', '2026-000115'.
        min_digits: mínimo de dígitos en la secuencia para aceptar. Default 4.

    v6.0.1: si la secuencia tiene 6 dígitos y empieza con 0, strip leading zero
    hasta 5 dígitos (convención colombiana canónica).

    Retorna '' si no se puede normalizar (año inválido o secuencia inválida).
    """
    if not raw:
        return ""
    # Detectar shape FOREST: año pegado directamente a ≥6 dígitos sin separador
    # (ej. "20260066132" es FOREST, NO rad_corto)
    digits_only = re.sub(r"[^0-9]", "", raw)
    if re.match(r"^20\d{2}\d{6,}$", digits_only):
        return ""
    m = re.search(r"(20\d{2})\D+(\d{1,6})", raw)
    if not m:
        return ""
    year = m.group(1)
    seq_raw = m.group(2)
    # v6.0.1: 6 dígitos con leading zero → strip al canónico 5d
    if len(seq_raw) == 6 and seq_raw.startswith("0"):
        seq_raw = seq_raw.lstrip("0") or "0"
    if len(seq_raw) < min_digits or len(seq_raw) > 5:
        return ""
    seq = seq_raw.zfill(5)
    return f"{year}-{seq}"


def consistent(rad23: str | None, rad_corto: str | None) -> bool:
    """True si ambos existen y el rad_corto deriva del rad23.

    Si solo uno existe (el otro es vacío/None), retorna True (no hay conflicto).
    """
    if not rad23 or not rad_corto:
        return True
    derived = derive_rad_corto_from_rad23(rad23)
    if not derived:
        return True  # rad23 malformado, no podemos juzgar
    # Normalizar rad_corto para comparar
    corto_norm = canonical_rad_corto(rad_corto)
    return derived == corto_norm


def reconcile(rad23: str | None, rad_corto: str | None) -> tuple[str, str]:
    """Reconcilia rad23 y rad_corto: si rad23 es válido, descartar rad_corto y re-derivar.

    Previene el bug donde un rad_corto regex mal capturado contamina la DB
    aunque el rad23 del email sea correcto.

    v6.0.1: si rad23 tiene ≥18 dígitos pero la derivación falla (shape no
    canónico, ej. RAD_23_CONTINUOUS captura 19-20d parciales), NO limpiar el
    rad_corto que el extractor halló por otra vía (p.ej. desde el subject).

    Returns:
        (rad23_canonico, rad_corto_canonico). Ambos pueden ser '' si no hay datos.
    """
    rad23_clean = rad23 or ""
    if is_valid_rad23(rad23_clean):
        derived = derive_rad_corto_from_rad23(rad23_clean)
        if derived:
            return rad23_clean, derived
        # rad23 ≥18d pero sin shape canónico: preservar rad_corto del extractor
        return rad23_clean, canonical_rad_corto(rad_corto) if rad_corto else ""
    # rad23 ausente o inválido: usar rad_corto normalizado
    return rad23_clean, canonical_rad_corto(rad_corto) if rad_corto else ""


def juzgado_code(rad23: str | None) -> str:
    """Extrae los primeros 12 dígitos del rad23 (depto+muni+entidad+especialidad+subesp).

    Estructura del rad23 colombiano (23 dígitos):
        [0:2] depto · [2:5] muni · [5:7] entidad · [7:9] espec · [9:12] subesp
        [12:16] año · [16:21] secuencia · [21:23] recurso

    Los primeros 12 dígitos identifican el juzgado único. Con estos se distingue
    Bucaramanga (68001) vs Cúcuta (54001) y juzgados civiles vs promiscuos.
    """
    digits = normalize_rad23(rad23)
    if len(digits) < 12:
        return ""
    return digits[:12]


def same_juzgado(rad23_a: str | None, rad23_b: str | None) -> bool:
    """True si ambos rad23 son del mismo juzgado (primeros 12 dígitos coinciden)."""
    code_a = juzgado_code(rad23_a)
    code_b = juzgado_code(rad23_b)
    if not code_a or not code_b:
        return False
    return code_a == code_b
