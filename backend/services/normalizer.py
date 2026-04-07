"""Funciones de normalización de datos para métricas confiables."""

import re
from collections import defaultdict


def normalize_abogado(name: str) -> str:
    """Normalizar nombre de abogado agrupando variantes."""
    if not name:
        return ""
    n = name.strip()
    # Quitar sufijos como "CPS", "OPS", números de contrato
    n = re.sub(r'\s+(CPS|OPS|CONTRATO|CC\.?\s*\d+).*$', '', n, flags=re.IGNORECASE)
    # Normalizar mayúsculas/minúsculas a Title Case
    n = n.strip().title()
    # Correcciones conocidas de typos
    TYPOS = {
        "Juan Deigo Cruz Lizcano": "Juan Diego Cruz Lizcano",
        "María Cristina Villamizar Schiller": "Maria Cristina Villamizar Schiller",
    }
    for wrong, correct in TYPOS.items():
        if n.lower() == wrong.lower():
            n = correct
    # Si tiene más de 5 palabras, probablemente incluye cargo — truncar
    words = n.split()
    if len(words) > 5:
        n = " ".join(words[:4])
    return n


def normalize_ciudad(ciudad: str) -> str:
    """Normalizar nombre de ciudad/municipio."""
    if not ciudad:
        return ""
    c = ciudad.strip().title()
    # Quitar departamento
    c = re.sub(r',?\s*Santander.*$', '', c, flags=re.IGNORECASE)
    c = re.sub(r',?\s*Colombia.*$', '', c, flags=re.IGNORECASE)
    c = c.strip().rstrip(',').strip()
    # Normalizar variantes conocidas
    NORM = {
        "Bogota D.C.": "Bogotá D.C.",
        "Bogota": "Bogotá D.C.",
        "Bogotá": "Bogotá D.C.",
        "Barrancabermeja": "Barrancabermeja",
        "Bucaramanga": "Bucaramanga",
        "Floridablanca": "Floridablanca",
        "Giron": "Girón",
        "Gambita": "Gámbita",
    }
    for k, v in NORM.items():
        if c.lower() == k.lower():
            c = v
    return c


def categorize_decision_incidente(decision: str, observaciones: str = "") -> str:
    """Categorizar decisión de incidente de desacato en categorías estándar.
    Usa primero el campo decision_incidente, y si está vacío busca pistas en observaciones."""
    # Primero intentar con la decisión directa
    d = (decision or "").upper()
    if d and d != "PENDIENTE":
        if any(w in d for w in ["SANCIONA", "SANCIÓN", "MULTA", "ARRESTO"]):
            return "SANCIONADO"
        if any(w in d for w in ["CONSULTA", "GRADO JURISDICCIONAL"]):
            return "EN CONSULTA"
        if any(w in d for w in ["NULIDAD", "DEVUELTO", "DEVOLVIÓ"]):
            return "EN TRÁMITE"
        if any(w in d for w in ["APERTURA", "ABRE", "PRUEBAS", "REQUERIMIENTO"]):
            return "EN TRÁMITE"
        if any(w in d for w in ["ARGUMENTA", "RESPONDE", "NO HA VULNERADO"]):
            return "EN TRÁMITE"
        if any(w in d for w in ["CUMPLIMIENTO", "CUMPLIDA", "CUMPLIÓ", "TERMINADO", "TERMINACIÓN", "FINALIZÓ"]):
            return "CUMPLIDO"
        if any(w in d for w in ["ABSTENERSE", "ABSTIENE", "ARCHIVAR", "ARCHIVA", "DENEGAR", "IMPROCEDENTE"]):
            return "ARCHIVADO"
        return "EN TRÁMITE"

    # Si no hay decisión, buscar en observaciones
    obs = (observaciones or "").upper()
    if obs:
        if any(w in obs for w in ["SANCION", "MULTA", "ARRESTO"]):
            return "SANCIONADO"
        if any(w in obs for w in ["CONSULTA", "GRADO JURISDICCIONAL"]):
            return "EN CONSULTA"
        if any(w in obs for w in ["CUMPLIMIENTO", "CUMPLIÓ", "CUMPLIDA", "SE DIO CUMPLIMIENTO"]):
            return "CUMPLIDO"
        if any(w in obs for w in ["APERTURA INCIDENTE", "ABRE INCIDENTE", "REQUERIMIENTO PREVIO"]):
            return "EN TRÁMITE"
        if any(w in obs for w in ["ARCHIV", "ABSTIENE", "NO PROCEDE"]):
            return "ARCHIVADO"
        if "DESACATO" in obs:
            return "EN TRÁMITE"

    return "PENDIENTE"


def get_fallo_definitivo(fallo_1st: str, fallo_2nd: str) -> tuple[str, str]:
    """Determinar fallo definitivo considerando 2da instancia.
    Returns: (fallo_definitivo, explicacion)"""
    f1 = (fallo_1st or "").strip().upper()
    f2 = (fallo_2nd or "").strip().upper()

    if not f1:
        return "SIN FALLO", "No se ha dictado sentencia de primera instancia"

    if not f2:
        # Solo tiene fallo de 1ra instancia
        if "CONCEDE" in f1:
            return "DESFAVORABLE", f"Fallo 1ra instancia: {fallo_1st} (sin impugnación o pendiente 2da inst.)"
        elif "NIEGA" in f1:
            return "FAVORABLE", f"Fallo 1ra instancia: {fallo_1st} (sin impugnación)"
        elif "IMPROCEDENTE" in f1:
            return "IMPROCEDENTE", f"Fallo 1ra instancia: {fallo_1st}"
        elif "DESISTIMIENTO" in f1:
            return "DESISTIMIENTO", f"El accionante desistió de la tutela"
        else:
            return "OTRO", f"Fallo 1ra instancia: {fallo_1st}"

    # Tiene fallo de 2da instancia
    if "REVOCA" in f2:
        if "CONCEDE" in f1:
            return "FAVORABLE", f"2da instancia REVOCÓ fallo desfavorable de 1ra ({fallo_1st})"
        else:
            return "DESFAVORABLE", f"2da instancia REVOCÓ fallo favorable de 1ra ({fallo_1st})"
    elif "CONFIRMA" in f2:
        if "CONCEDE" in f1:
            return "DESFAVORABLE", f"2da instancia CONFIRMÓ fallo desfavorable ({fallo_1st})"
        elif "NIEGA" in f1:
            return "FAVORABLE", f"2da instancia CONFIRMÓ fallo favorable ({fallo_1st})"
        elif "IMPROCEDENTE" in f1:
            return "IMPROCEDENTE", f"2da instancia CONFIRMÓ improcedencia"
        else:
            return "OTRO", f"2da instancia confirmó: {fallo_1st}"
    elif "MODIFICA" in f2:
        return "MODIFICADO", f"2da instancia MODIFICÓ parcialmente fallo de 1ra ({fallo_1st})"
    else:
        return "OTRO", f"2da instancia: {fallo_2nd}"


def group_by_normalized(items: list[tuple[str, int]], normalizer) -> list[tuple[str, int]]:
    """Agrupar items por nombre normalizado, sumando conteos."""
    groups = defaultdict(int)
    for name, count in items:
        norm = normalizer(name)
        if norm:
            groups[norm] += count
    return sorted(groups.items(), key=lambda x: -x[1])
