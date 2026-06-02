"""Lista oficial de los 87 municipios del Departamento de Santander.

Fuente: DANE / División político-administrativa de Colombia.

Uso: validar que `ciudad` extraída sea un municipio real, no una frase
random capturada por regex.
"""

from __future__ import annotations
import unicodedata


MUNICIPIOS_SANTANDER: set[str] = {
    "AGUADA", "ALBANIA", "ARATOCA", "BARBOSA", "BARICHARA", "BARRANCABERMEJA",
    "BETULIA", "BOLIVAR", "BUCARAMANGA", "CABRERA", "CALIFORNIA", "CAPITANEJO",
    "CARCASI", "CEPITA", "CERRITO", "CHARALA", "CHARTA", "CHIMA", "CHIPATA",
    "CIMITARRA", "CONCEPCION", "CONFINES", "CONTRATACION", "COROMORO", "CURITI",
    "EL CARMEN DE CHUCURI", "EL GUACAMAYO", "EL PEÑON", "EL PEÑÓN", "EL PLAYON",
    "ENCINO", "ENCISO", "FLORIAN", "FLORIDABLANCA", "GALAN", "GAMBITA", "GIRON",
    "GUACA", "GUADALUPE", "GUAPOTA", "GUAVATA", "GUEPSA", "GÜEPSA", "HATO",
    "JESUS MARIA", "JORDAN", "LA BELLEZA", "LANDAZURI", "LA PAZ", "LEBRIJA",
    "LOS SANTOS", "MACARAVITA", "MALAGA", "MATANZA", "MOGOTES", "MOLAGAVITA",
    "OCAMONTE", "OIBA", "ONZAGA", "PALMAR", "PALMAS DEL SOCORRO", "PARAMO",
    "PIEDECUESTA", "PINCHOTE", "PUENTE NACIONAL", "PUERTO PARRA", "PUERTO WILCHES",
    "RIONEGRO", "SABANA DE TORRES", "SAN ANDRES", "SAN BENITO", "SAN GIL",
    "SAN JOAQUIN", "SAN JOSE DE MIRANDA", "SAN MIGUEL", "SAN VICENTE DE CHUCURI",
    "SANTA BARBARA", "SANTA HELENA DEL OPON", "SIMACOTA", "SOCORRO", "SUAITA",
    "SUCRE", "SURATA", "TONA", "VALLE DE SAN JOSE", "VELEZ", "VETAS", "VILLANUEVA",
    "ZAPATOCA",
}


def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").upper().strip()


# Lookup sin acentos → canónico. Evita falsos negativos por ñ/tildes (ej. "EL PEÑÓN",
# "CURITÍ"): el input se compara sin acentos contra el set también sin acentos. 2026-06-01.
_MUNI_STRIPPED: dict[str, str] = {_strip_accents(m): m for m in MUNICIPIOS_SANTANDER}


def is_municipio_santander(name: str) -> bool:
    """True si el string es un municipio válido de Santander (con o sin acentos)."""
    if not name:
        return False
    norm = _strip_accents(name)
    if norm in _MUNI_STRIPPED:
        return True
    # Match con espacios/guiones tolerantes
    norm_alpha = "".join(c for c in norm if c.isalpha() or c == " ").strip()
    return norm_alpha in _MUNI_STRIPPED


def find_municipio_in_text(text: str) -> str | None:
    """Busca un municipio de Santander mencionado en el texto. Devuelve el nombre canónico."""
    if not text:
        return None
    norm_text = _strip_accents(text)
    # Comparar sin acentos (set y texto), preferir nombres compuestos (más largos).
    for muni_stripped in sorted(_MUNI_STRIPPED, key=len, reverse=True):
        if f" {muni_stripped} " in f" {norm_text} ":
            return _MUNI_STRIPPED[muni_stripped]
    return None
