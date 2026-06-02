"""Etapa 3 — Resolución de catálogos canónicos. Sin IA.

Toma el `abogado_responsable` extraído por regex y lo mapea a uno de los 17
abogados oficiales en `backend/data/abogados_canonicos.json` (con aliases y
fuzzy match). Idem para `oficina_responsable` → `dependencia_canonical` con
`backend/data/dependencias_resolver.py`.

Si no hay match en catálogo, deja `abogado_canonical=None` y confianza 0.
NO inventa valores. NO llama LLM.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Optional

from backend.v9.types import ExtractedFields

logger = logging.getLogger("tutelas.v9.catalog")


_CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "abogados_canonicos.json"


def _norm(s: str) -> str:
    if not s:
        return ""
    s = str(s).strip().upper()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


@lru_cache(maxsize=1)
def _load_abogados() -> list[dict]:
    if not _CATALOG_PATH.exists():
        logger.warning("catálogo abogados no encontrado en %s", _CATALOG_PATH)
        return []
    with _CATALOG_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def resolve_abogado(raw_name: Optional[str]) -> tuple[Optional[str], float]:
    """Mapea un nombre extraído al abogado canónico. Devuelve (canonico, confianza).

    Estrategia:
      1. Match exacto contra `canonical` o `aliases` (confianza 1.0).
      2. Match contra `short` (confianza 0.95).
      3. Substring contra cualquier alias (confianza 0.85).
      4. Fuzzy SequenceMatcher >= 0.88 (confianza = ratio).
      5. None si nada supera el umbral.
    """
    if not raw_name:
        return None, 0.0
    n = _norm(raw_name)
    if not n:
        return None, 0.0

    catalog = _load_abogados()
    if not catalog:
        return None, 0.0

    # 1. Exacto canonical / alias
    for entry in catalog:
        if _norm(entry["canonical"]) == n:
            return entry["canonical"], 1.0
        for alias in entry.get("aliases", []):
            if _norm(alias) == n:
                return entry["canonical"], 1.0

    # 2. Match contra short
    for entry in catalog:
        if _norm(entry.get("short", "")) == n:
            return entry["canonical"], 0.95

    # 3. Substring (input contiene alias o viceversa)
    candidates: list[tuple[float, str]] = []
    for entry in catalog:
        for token in [entry["canonical"], entry.get("short", ""), *entry.get("aliases", [])]:
            tn = _norm(token)
            if not tn:
                continue
            if tn in n or n in tn:
                # Especificidad por longitud del match
                spec = len(tn) / max(len(n), 1)
                candidates.append((min(0.85, 0.6 + spec * 0.25), entry["canonical"]))

    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1], candidates[0][0]

    # 4. Fuzzy
    best = (0.0, None)
    for entry in catalog:
        for token in [entry["canonical"], *entry.get("aliases", [])]:
            r = _ratio(n, _norm(token))
            if r > best[0]:
                best = (r, entry["canonical"])
    if best[0] >= 0.88:
        return best[1], best[0]

    return None, 0.0


def resolve_dependencia(raw_dep: Optional[str]) -> tuple[Optional[str], float]:
    """Wrap a `dependencias_resolver.normalize_with_metadata`."""
    if not raw_dep:
        return None, 0.0
    try:
        from backend.data.dependencias_resolver import normalize_with_metadata
    except ImportError as e:
        logger.warning("dependencias_resolver no importable: %s", e)
        return None, 0.0
    md = normalize_with_metadata(raw_dep)
    return md.get("code"), float(md.get("confidence") or 0.0)


def derive_sed_hierarchy(dependencia_code: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Dado un código canónico de SED_ORG, devuelve (direccion L1, grupo L2, equipo L3).

    Ejemplos:
        "EQUIPO_TESORERIA"          → ("DIRECCION_ADMIN_FINANCIERA", "FINANCIERA", "EQUIPO_TESORERIA")
        "NOMINA"                    → ("DIRECCION_TALENTO_DOCENTE", "NOMINA", None)
        "DIRECCION_TALENTO_DOCENTE" → ("DIRECCION_TALENTO_DOCENTE", None, None)
        "MULTI" / "SIN_ASIGNAR"     → (code, None, None)
        None                        → (None, None, None)
    """
    if not dependencia_code:
        return None, None, None
    try:
        from backend.ml.data.sed_org import get_unit
    except ImportError as e:
        logger.warning("sed_org no importable: %s", e)
        return None, None, None

    unit = get_unit(dependencia_code)
    if not unit:
        return None, None, None

    # Walk up the parent chain
    if unit.level == 1:
        return unit.code, None, None
    if unit.level == 2:
        parent = get_unit(unit.parent) if unit.parent else None
        return (parent.code if parent else None), unit.code, None
    if unit.level == 3:
        l2 = get_unit(unit.parent) if unit.parent else None
        l1 = get_unit(l2.parent) if (l2 and l2.parent) else None
        return (l1.code if l1 else None), (l2.code if l2 else None), unit.code

    return None, None, None


# ── 1B: Normalizador canónico de juzgado ─────────────────────────────────────
_NUM_TO_WORDS: dict[str, str] = {
    "01": "PRIMERO",      "1":  "PRIMERO",
    "02": "SEGUNDO",      "2":  "SEGUNDO",
    "03": "TERCERO",      "3":  "TERCERO",
    "04": "CUARTO",       "4":  "CUARTO",
    "05": "QUINTO",       "5":  "QUINTO",
    "06": "SEXTO",        "6":  "SEXTO",
    "07": "SÉPTIMO",      "7":  "SÉPTIMO",
    "08": "OCTAVO",       "8":  "OCTAVO",
    "09": "NOVENO",       "9":  "NOVENO",
    "10": "DÉCIMO",
    "11": "UNDÉCIMO",
    "12": "DUODÉCIMO",
    "13": "DECIMOTERCERO",
    "14": "DECIMOCUARTO",
    "15": "DECIMOQUINTO",
    "16": "DECIMOSEXTO",
    "17": "DECIMOSÉPTIMO",
    "18": "DECIMOOCTAVO",
    "19": "DECIMONOVENO",
    "20": "VIGÉSIMO",
    "21": "VIGÉSIMO PRIMERO", "22": "VIGÉSIMO SEGUNDO", "23": "VIGÉSIMO TERCERO",
    "24": "VIGÉSIMO CUARTO", "25": "VIGÉSIMO QUINTO", "26": "VIGÉSIMO SEXTO",
    "27": "VIGÉSIMO SÉPTIMO", "28": "VIGÉSIMO OCTAVO", "29": "VIGÉSIMO NOVENO",
    "30": "TRIGÉSIMO", "31": "TRIGÉSIMO PRIMERO", "32": "TRIGÉSIMO SEGUNDO",
    "33": "TRIGÉSIMO TERCERO", "34": "TRIGÉSIMO CUARTO", "35": "TRIGÉSIMO QUINTO",
    "36": "TRIGÉSIMO SEXTO", "37": "TRIGÉSIMO SÉPTIMO", "38": "TRIGÉSIMO OCTAVO",
    "39": "TRIGÉSIMO NOVENO", "40": "CUADRAGÉSIMO",
}

_RE_DEPT_PAREN = re.compile(
    r"\s*\(\s*(?:SANTANDER|COLOMBIA|DEPTO\.?|DEPARTAMENTO)\s*\)\s*", re.IGNORECASE
)
_RE_JUZGADO_NUM = re.compile(r"(?<=\bJUZGADO\s)(\d{1,2})(?=\s)", re.IGNORECASE)


def normalize_juzgado(raw: str) -> str:
    """Estandariza el nombre del juzgado a forma canónica.

    Transformaciones:
    - Elimina paréntesis de departamento: "(SANTANDER)" → ""
    - Convierte número a escrito después de JUZGADO: "JUZGADO 17 CIVIL" →
      "JUZGADO DECIMOSÉPTIMO CIVIL"
    - Colapsa espacios, mayúsculas, máx 120 chars
    """
    if not raw:
        return raw
    s = raw.strip().upper()
    # Eliminar paréntesis con nombre de departamento
    s = _RE_DEPT_PAREN.sub(" ", s)
    # Convertir número cardinal después de JUZGADO
    def _replace_num(m: re.Match) -> str:
        return _NUM_TO_WORDS.get(m.group(1).lstrip("0") or "0",
                                  _NUM_TO_WORDS.get(m.group(1), m.group(1)))
    s = _RE_JUZGADO_NUM.sub(_replace_num, s)
    # Normalizar espacios
    s = re.sub(r"\s+", " ", s).strip()
    return s[:120]


def run(fields: ExtractedFields) -> ExtractedFields:
    """Resuelve canónicos en `fields`. No toca los valores Excel — solo
    completa los campos derivados (`abogado_canonical`, `dependencia_canonical`).

    Side effect: si `abogado_canonical` matchea con confianza >= 0.95 y el
    campo `abogado_responsable` venía vacío, lo llena. (Caso: el regex no
    encontró firmante pero el Excel ya tiene la asignación.)
    """
    raw_lawyer = fields.values.get("abogado_responsable", "")
    canonical, conf = resolve_abogado(raw_lawyer)
    if canonical:
        fields.abogado_canonical = canonical
        fields.abogado_canonical_confidence = conf

    # Derivado: abogado_incidente_N = abogado_responsable cuando incidente_N=SI.
    # Convención interna SED (feedback Wilson 2026-05-18): el mismo abogado lleva
    # el incidente, no hay reasignación. responsable_desacato (jurídico) sigue
    # siendo el funcionario sancionable; abogado_incidente_N es la columna
    # operativa con quién opera la defensa.
    if raw_lawyer:
        from backend.v9.types import FieldSource
        for inc_key, ab_inc_key in (
            ("incidente", "abogado_incidente"),
            ("incidente_2", "abogado_incidente_2"),
            ("incidente_3", "abogado_incidente_3"),
        ):
            if fields.values.get(inc_key) == "SI" and not fields.values.get(ab_inc_key):
                fields.values[ab_inc_key] = raw_lawyer
                fields.sources[ab_inc_key] = FieldSource.CATALOG

    raw_oficina = fields.values.get("oficina_responsable", "")
    dep_code, dep_conf = resolve_dependencia(raw_oficina)
    if dep_code:
        fields.dependencia_canonical = dep_code
        fields.dependencia_canonical_confidence = dep_conf
        # Derivar jerarquía SED (L1/L2/L3) — solo lookup en sed_org, sin IA
        l1, l2, l3 = derive_sed_hierarchy(dep_code)
        fields.direccion = l1
        fields.grupo = l2
        fields.equipo = l3

    return fields
