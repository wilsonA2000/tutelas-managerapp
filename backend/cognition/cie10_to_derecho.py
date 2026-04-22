"""Mapeo CIE-10 → derechos fundamentales implícitos y keywords → taxonomía.

Codifica lo que un abogado sabe por experiencia: si el accionante menciona
"parálisis cerebral", los derechos vulnerados incluyen SALUD, VIDA DIGNA,
INTERÉS SUPERIOR DEL MENOR. Si menciona "docente trasladada", incluye
TRABAJO, EDUCACIÓN, DEBIDO PROCESO.
"""

from __future__ import annotations

import re


# Familias CIE-10 → derechos fundamentales implicados
# (Se trata de inferencia jurídica común, no de asesoramiento médico).
CIE10_FAMILY_DERECHOS: dict[str, list[str]] = {
    # Neurológicas / Discapacidad
    "G80": ["SALUD", "VIDA DIGNA", "INTERES SUPERIOR DEL MENOR", "DIGNIDAD HUMANA"],  # Parálisis cerebral
    "G40": ["SALUD", "VIDA DIGNA", "DIGNIDAD HUMANA"],  # Epilepsia
    "G91": ["SALUD", "VIDA DIGNA"],  # Hidrocefalia
    "F84": ["SALUD", "EDUCACION", "ACCESIBILIDAD", "INTERES SUPERIOR DEL MENOR"],  # TEA/autismo
    "F70": ["SALUD", "EDUCACION", "DIGNIDAD HUMANA"],  # Discapacidad intelectual
    "F71": ["SALUD", "EDUCACION", "DIGNIDAD HUMANA"],
    # Salud mental
    "F20": ["SALUD", "SALUD MENTAL", "DIGNIDAD HUMANA"],  # Esquizofrenia
    "F32": ["SALUD", "SALUD MENTAL", "VIDA DIGNA"],  # Depresión
    "F33": ["SALUD", "SALUD MENTAL", "VIDA DIGNA"],
    # Cardiovasculares graves
    "I50": ["SALUD", "VIDA DIGNA", "SEGURIDAD SOCIAL"],
    "I25": ["SALUD", "VIDA DIGNA"],
    # Oncológicas
    "C50": ["SALUD", "VIDA DIGNA", "SEGURIDAD SOCIAL"],  # Cáncer mama
    "C34": ["SALUD", "VIDA DIGNA", "SEGURIDAD SOCIAL"],  # Cáncer pulmón
    "C": ["SALUD", "VIDA DIGNA", "SEGURIDAD SOCIAL"],  # Cualquier C (oncología)
    # Endocrinas
    "E10": ["SALUD", "VIDA DIGNA"],  # Diabetes tipo 1
    "E11": ["SALUD", "VIDA DIGNA"],  # Diabetes tipo 2
    # Renales
    "N18": ["SALUD", "VIDA DIGNA", "SEGURIDAD SOCIAL"],  # Insuficiencia renal
    # Maternidad
    "O": ["SALUD", "VIDA DIGNA", "SEGURIDAD SOCIAL", "DIGNIDAD HUMANA"],
}


# Keywords temáticos (sin CIE-10 explícito) → derechos
KEYWORD_DERECHOS: list[tuple[re.Pattern, list[str]]] = [
    # Educación
    (re.compile(r"\bdocente\b|\btraslado\s+docente\b|nombramiento\s+(?:del?\s+)?docente", re.IGNORECASE),
     ["EDUCACION", "TRABAJO", "DEBIDO PROCESO"]),
    (re.compile(r"\b(?:colegio|escuela|instituci[oó]n\s+educativa|sede\s+educativa|matr[íi]cula)\b", re.IGNORECASE),
     ["EDUCACION", "ACCESIBILIDAD", "ACCESO"]),
    (re.compile(r"\bpermanencia\s+escolar\b|continuidad\s+educativa", re.IGNORECASE),
     ["EDUCACION", "PERMANENCIA", "ACCESO"]),
    (re.compile(r"\bpae\b|programa\s+de\s+alimentaci[oó]n\s+escolar|alimentaci[oó]n\s+escolar", re.IGNORECASE),
     ["EDUCACION", "ALIMENTACION", "MINIMO VITAL"]),
    (re.compile(r"\btransporte\s+escolar\b", re.IGNORECASE),
     ["EDUCACION", "ACCESIBILIDAD", "ACCESO"]),
    # Discapacidad
    (re.compile(r"\bdiscapacidad\b|silla\s+de\s+ruedas|movilidad\s+reducida", re.IGNORECASE),
     ["SALUD", "VIDA DIGNA", "ACCESIBILIDAD", "DIGNIDAD HUMANA"]),
    (re.compile(r"\bdocente\s+de\s+apoyo\b|educaci[oó]n\s+inclusiva", re.IGNORECASE),
     ["EDUCACION", "INTERES SUPERIOR DEL MENOR", "ACCESIBILIDAD", "DIGNIDAD HUMANA"]),
    # Salud
    (re.compile(r"\beps\b|medicamento|tratamiento\s+m[eé]dico|cirug[íi]a", re.IGNORECASE),
     ["SALUD", "VIDA DIGNA", "SEGURIDAD SOCIAL"]),
    (re.compile(r"\bespecialista\b|\bconsulta\s+especializada\b", re.IGNORECASE),
     ["SALUD", "SEGURIDAD SOCIAL"]),
    # Vivienda / Mínimo vital
    (re.compile(r"vivienda\s+digna|subsidio\s+de\s+vivienda", re.IGNORECASE),
     ["VIVIENDA DIGNA", "DIGNIDAD HUMANA", "MINIMO VITAL"]),
    (re.compile(r"\bm[ií]nimo\s+vital\b|servicios\s+p[uú]blicos", re.IGNORECASE),
     ["MINIMO VITAL", "DIGNIDAD HUMANA"]),
    # Laboral
    (re.compile(r"\breintegro\b|despid[oa]\s+(?:sin\s+justa\s+causa|injusto)", re.IGNORECASE),
     ["TRABAJO", "ESTABILIDAD LABORAL REFORZADA", "DEBIDO PROCESO"]),
    (re.compile(r"\bpensi[oó]n\b|seguridad\s+social", re.IGNORECASE),
     ["SEGURIDAD SOCIAL", "MINIMO VITAL"]),
    # Procesal
    (re.compile(r"\bderecho\s+de\s+petici[oó]n\b|respuesta\s+a\s+petici[oó]n", re.IGNORECASE),
     ["PETICION", "DEBIDO PROCESO"]),
    (re.compile(r"\bdebido\s+proceso\b", re.IGNORECASE),
     ["DEBIDO PROCESO"]),
    (re.compile(r"\bigualdad\b", re.IGNORECASE),
     ["IGUALDAD", "DIGNIDAD HUMANA"]),
    # Unidad familiar (10.2% del corpus según catálogo)
    (re.compile(r"\bunidad\s+familiar\b|reunificaci[oó]n\s+familiar", re.IGNORECASE),
     ["UNIDAD FAMILIAR", "DIGNIDAD HUMANA", "INTERES SUPERIOR DEL MENOR"]),
    # Vida (frecuencia 7.4%)
    (re.compile(r"\bderecho\s+a\s+la\s+vida\b", re.IGNORECASE),
     ["VIDA", "VIDA DIGNA", "DIGNIDAD HUMANA"]),
    # Integridad personal
    (re.compile(r"\bintegridad\s+personal\b|integridad\s+f[íi]sica", re.IGNORECASE),
     ["INTEGRIDAD PERSONAL", "VIDA DIGNA", "DIGNIDAD HUMANA"]),
    # Menores
    (re.compile(r"\b(?:menor|ni[ñn][oa]|adolescente)\b", re.IGNORECASE),
     ["INTERES SUPERIOR DEL MENOR"]),
    # Violencia género / salud mental
    (re.compile(r"\bviolencia\b|\bmaltrato\b|\bagresi[oó]n\b", re.IGNORECASE),
     ["VIDA DIGNA", "DIGNIDAD HUMANA", "INTEGRIDAD PERSONAL"]),
]


CIE10_REGEX = re.compile(r"\b([A-TV-Z])(\d{2})(?:\.\d{1,2})?\b")


def _extract_cie10_codes(text: str) -> set[str]:
    codes = set()
    for m in CIE10_REGEX.finditer(text):
        code = m.group(1) + m.group(2)
        codes.add(code)
    return codes


_TILDE_NORM = {
    "EDUCACIÓN": "EDUCACION",
    "PETICIÓN": "PETICION",
    "MÍNIMO VITAL": "MINIMO VITAL",
    "VIVIENDA DIGNA": "VIVIENDA DIGNA",
    "SEGURIDAD SOCIAL": "SEGURIDAD SOCIAL",
    "DIGNIDAD HUMANA": "DIGNIDAD HUMANA",
}


def _normalize_derecho(d: str) -> str:
    """Normaliza formato estándar sin tildes redundantes (catálogo v5.3.2)."""
    d = d.strip().upper()
    return _TILDE_NORM.get(d, d)


def infer_derechos_from_dx(text: str) -> list[str]:
    """Infiere derechos fundamentales vulnerados desde diagnósticos y keywords.

    Retorna lista ordenada y deduplicada (el primero es el más común).
    """
    derechos: list[str] = []
    seen: set[str] = set()

    def _add(lst):
        for d in lst:
            d_norm = _normalize_derecho(d)
            if d_norm not in seen:
                seen.add(d_norm)
                derechos.append(d_norm)

    # 1. Códigos CIE-10 explícitos → familias
    text_upper = text.upper()
    for code in _extract_cie10_codes(text_upper):
        if code in CIE10_FAMILY_DERECHOS:
            _add(CIE10_FAMILY_DERECHOS[code])
        # Intentar familia parcial: "C50" → "C"
        elif code[0] in CIE10_FAMILY_DERECHOS:
            _add(CIE10_FAMILY_DERECHOS[code[0]])

    # 2. Keywords semánticos
    for pat, ds in KEYWORD_DERECHOS:
        if pat.search(text):
            _add(ds)

    return derechos
