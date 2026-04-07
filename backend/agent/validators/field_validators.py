"""Validadores por campo y cross-field para datos extraídos."""

import re
from datetime import datetime


# Known valid values
VALID_FALLOS_1ST = {"CONCEDE", "NIEGA", "IMPROCEDENTE", "CONCEDE PARCIALMENTE", ""}
VALID_FALLOS_2ND = {"CONFIRMA", "REVOCA", "MODIFICA", ""}
VALID_SI_NO = {"SI", "NO", ""}
VALID_ESTADOS = {"ACTIVO", "INACTIVO", ""}

from backend.agent.forest_extractor import FOREST_BLACKLIST

KNOWN_LAWYERS = [
    "JUAN DIEGO CRUZ LIZCANO", "DIEGO OTILIO RODRIGUEZ NUÑEZ",
    "LUIS EDUARDO MEZA JURADO", "ANGELICA BARROSO SARMIENTO",
    "JHON ALEXANDER BOHORQUEZ CAMARGO", "OTILIA LUNA LOPEZ",
    "VICTOR COLMENARES", "CHRISTIAN FLOREZ GUERRERO",
    "FERNANDO CAMACHO PICO", "DANNA VALENTINA GARCIA",
    "MARIA CRISTINA VILLAMIZAR SCHILLER", "JORGE JAVIER SEPULVEDA JAIMES",
    "ROLANDO RODRIGUEZ MANTILLA", "ANDRES HONORIO MARIN",
    "KARINA ARAUJO MAESTRE", "PILAR INES AGUIRRE PEÑA",
    "MARTHA LUQUE",
]


def validate_field(field_name: str, value: str, all_fields: dict = None) -> tuple[bool, str]:
    """Validar un campo individual. Returns (is_valid, reason)."""
    if not value or not value.strip():
        return True, "Empty (allowed)"

    value = value.strip()
    all_fields = all_fields or {}

    # FOREST validation
    if field_name in ("RADICADO_FOREST", "FOREST_IMPUGNACION"):
        return _validate_forest(value)

    # Fallo validation
    if field_name == "SENTIDO_FALLO_1ST":
        return _validate_enum(value, VALID_FALLOS_1ST, "Fallo 1ra instancia")
    if field_name == "SENTIDO_FALLO_2ND":
        return _validate_enum(value, VALID_FALLOS_2ND, "Fallo 2da instancia")

    # SI/NO fields
    if field_name in ("IMPUGNACION", "INCIDENTE", "INCIDENTE_2", "INCIDENTE_3"):
        return _validate_enum(value, VALID_SI_NO, field_name)

    # Estado
    if field_name == "ESTADO":
        return _validate_enum(value, VALID_ESTADOS, "Estado")

    # Date fields
    if "FECHA" in field_name:
        return _validate_date(value)

    # Abogado
    if field_name == "ABOGADO_RESPONSABLE":
        return _validate_abogado(value)

    return True, "OK"


def validate_cross_fields(fields: dict) -> list[str]:
    """Validación cruzada entre campos. Returns lista de warnings."""
    warnings = []

    # Temporal: fecha_ingreso < fecha_fallo_1st < fecha_fallo_2nd
    dates = {}
    for key in ["FECHA_INGRESO", "FECHA_FALLO_1ST", "FECHA_FALLO_2ND", "FECHA_RESPUESTA"]:
        val = fields.get(key, "")
        if val:
            parsed = _parse_date(val)
            if parsed:
                dates[key] = parsed

    if "FECHA_INGRESO" in dates and "FECHA_FALLO_1ST" in dates:
        if dates["FECHA_INGRESO"] > dates["FECHA_FALLO_1ST"]:
            warnings.append(f"FECHA_INGRESO ({fields['FECHA_INGRESO']}) es posterior a FECHA_FALLO_1ST ({fields['FECHA_FALLO_1ST']})")

    if "FECHA_FALLO_1ST" in dates and "FECHA_FALLO_2ND" in dates:
        if dates["FECHA_FALLO_1ST"] > dates["FECHA_FALLO_2ND"]:
            warnings.append(f"FECHA_FALLO_1ST es posterior a FECHA_FALLO_2ND")

    # Consistency: si hay fallo pero no impugnacion, debería ser NO
    if fields.get("SENTIDO_FALLO_1ST") and not fields.get("IMPUGNACION"):
        warnings.append("Tiene SENTIDO_FALLO_1ST pero IMPUGNACION está vacío (debería ser SI o NO)")

    # Si hay fallo 2da pero no impugnación
    if fields.get("SENTIDO_FALLO_2ND") and fields.get("IMPUGNACION") != "SI":
        warnings.append("Tiene fallo 2da instancia pero IMPUGNACION no es SI")

    # Si hay incidente pero no hay decisión
    if fields.get("INCIDENTE") == "SI" and not fields.get("FECHA_APERTURA_INCIDENTE"):
        warnings.append("INCIDENTE=SI pero sin FECHA_APERTURA_INCIDENTE")

    return warnings


def _validate_forest(value: str) -> tuple[bool, str]:
    clean = re.sub(r'\D', '', value)
    if clean in FOREST_BLACKLIST:
        return False, f"FOREST {clean} está en blacklist (alucinado por IA)"
    if clean.startswith('68'):
        return False, f"FOREST {clean} parece un radicado judicial (empieza con 68)"
    if len(clean) < 7:
        return False, f"FOREST muy corto: {len(clean)} dígitos"
    return True, "OK"


def _validate_enum(value: str, valid_set: set, field_label: str) -> tuple[bool, str]:
    if value.upper() not in valid_set:
        return False, f"{field_label}: '{value}' no es válido. Opciones: {', '.join(valid_set - {''})}"
    return True, "OK"


def _validate_date(value: str) -> tuple[bool, str]:
    parsed = _parse_date(value)
    if not parsed:
        return False, f"Fecha '{value}' no tiene formato DD/MM/YYYY"
    if parsed.year < 2020 or parsed.year > 2030:
        return False, f"Año {parsed.year} fuera de rango (2020-2030)"
    return True, "OK"


def _parse_date(value: str) -> datetime | None:
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def _validate_abogado(value: str) -> tuple[bool, str]:
    upper = value.upper().strip()
    for lawyer in KNOWN_LAWYERS:
        if lawyer in upper or upper in lawyer:
            return True, f"Abogado conocido: {lawyer}"
    # Not in known list - warning but not invalid
    return True, f"Abogado '{value}' no está en lista conocida (puede ser correcto)"
