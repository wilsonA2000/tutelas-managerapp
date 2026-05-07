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


def is_municipio_santander(name: str) -> bool:
    """True si el string es un municipio válido de Santander (con o sin acentos)."""
    if not name:
        return False
    norm = _strip_accents(name)
    if norm in MUNICIPIOS_SANTANDER:
        return True
    # Match con espacios/guiones tolerantes
    norm_alpha = "".join(c for c in norm if c.isalpha() or c == " ").strip()
    return norm_alpha in MUNICIPIOS_SANTANDER


def find_municipio_in_text(text: str) -> str | None:
    """Busca un municipio de Santander mencionado en el texto. Devuelve el nombre canónico."""
    if not text:
        return None
    norm_text = _strip_accents(text)
    # Ordenar por longitud descendente para preferir nombres compuestos
    for muni in sorted(MUNICIPIOS_SANTANDER, key=len, reverse=True):
        if f" {muni} " in f" {norm_text} ":
            return muni
    return None
