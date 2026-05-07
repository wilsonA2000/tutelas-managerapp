"""Resolver canónico de dependencias SED Santander.

Mapea cualquier variante (Excel shorthand, nombres extraídos de docs, typos)
al código canónico de `backend/ml/data/sed_org.py`.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Optional

from backend.ml.data.sed_org import SED_ORG, get_unit


def _norm(s: str) -> str:
    if not s:
        return ""
    s = str(s).strip().upper()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Aliases de Excel/docs/conversación → código canónico SED_ORG
# Orden importa: matches más específicos primero.
DEPENDENCY_ALIASES: list[tuple[str, str]] = [
    # ===== Tres entes operativos clave del Excel =====
    ("DIRECCION TALENTO HUMANO DOCENTE", "DIRECCION_TALENTO_DOCENTE"),
    ("TALENTO HUMANO DOCENTE", "DIRECCION_TALENTO_DOCENTE"),
    ("DIRECCION DE TALENTO HUMANO", "DIRECCION_TALENTO_DOCENTE"),
    ("TALENTO HUMANO", "DIRECCION_TALENTO_DOCENTE"),
    ("TH", "DIRECCION_TALENTO_DOCENTE"),

    ("DIRECCION ESTRATEGICA", "DIRECCION_ESTRATEGICA"),
    ("ESTRATEGICA", "DIRECCION_ESTRATEGICA"),

    ("DIRECCION ADMINISTRATIVA Y FINANCIERA", "DIRECCION_ADMIN_FINANCIERA"),
    ("ADMINISTRATIVA Y FINANCIERA", "DIRECCION_ADMIN_FINANCIERA"),
    ("ADMIN FINANCIERA", "DIRECCION_ADMIN_FINANCIERA"),
    ("DIRECCION FINANCIERA", "DIRECCION_ADMIN_FINANCIERA"),

    # ===== Grupo Financiera y equipos =====
    ("EQUIPO TESORERIA", "EQUIPO_TESORERIA"),
    ("TESORERIA", "EQUIPO_TESORERIA"),
    ("EQUIPO PRESUPUESTO", "EQUIPO_PRESUPUESTO"),
    ("PRESUPUESTO", "EQUIPO_PRESUPUESTO"),
    ("EQUIPO CONTABILIDAD", "EQUIPO_CONTABILIDAD"),
    ("CONTABILIDAD", "EQUIPO_CONTABILIDAD"),
    ("FONDO DE SERVICIOS EDUCATIVOS", "EQUIPO_FONDOS_SERVICIOS"),
    ("FONDOS DE SERVICIOS", "EQUIPO_FONDOS_SERVICIOS"),
    ("GRUPO FINANCIERA", "FINANCIERA"),
    ("FINANCIERA", "FINANCIERA"),
    ("FIANANCIERA", "FINANCIERA"),  # typo común en Excel

    # ===== Permanencia =====
    ("DIRECCION DE PERMANENCIA ESCOLAR", "DIRECCION_PERMANENCIA"),
    ("PERMANENCIA ESCOLAR", "DIRECCION_PERMANENCIA"),
    ("PERMANENCIA", "DIRECCION_PERMANENCIA"),
    ("PAE", "DIRECCION_PERMANENCIA"),  # PAE va bajo Permanencia
    ("PROGRAMA ALIMENTACION", "DIRECCION_PERMANENCIA"),
    ("TRANSPORTE", "DIRECCION_PERMANENCIA"),
    ("TRANSPORTE ESCOLAR", "DIRECCION_PERMANENCIA"),

    # ===== Apoyo Directo =====
    ("APOYO DIRECTO DESPACHO", "APOYO_DIRECTO"),
    ("DESPACHO", "APOYO_DIRECTO"),
    ("GRUPO INSPECCION Y VIGILANCIA", "INSPECCION_VIGILANCIA"),
    ("INSPECCION Y VIGILANCIA", "INSPECCION_VIGILANCIA"),
    ("INSPECCION", "INSPECCION_VIGILANCIA"),
    ("GRUPO APOYO JURIDICO", "APOYO_JURIDICO"),
    ("APOYO JURIDICO EDUCACION", "APOYO_JURIDICO"),
    ("APOYO JURIDICO", "APOYO_JURIDICO"),
    ("SUPERVISORES Y NUCLEO", "SUPERVISORES_NUCLEO"),
    ("SUPERVISORES DE EDUCACION", "SUPERVISORES_NUCLEO"),
    ("DIRECTORES DE NUCLEO", "SUPERVISORES_NUCLEO"),
    ("PLANEACION EDUCATIVA", "PLANEACION_EDUCATIVA"),

    # ===== Grupos Estratégica =====
    ("CALIDAD EDUCATIVA", "CALIDAD_EDUCATIVA"),
    ("CALIDAD", "CALIDAD_EDUCATIVA"),
    ("INCLUSION", "CALIDAD_EDUCATIVA"),  # política de inclusión va por calidad
    ("COBERTURA EDUCATIVA", "COBERTURA_EDUCATIVA"),
    ("COBERTURA", "COBERTURA_EDUCATIVA"),
    ("SIMAT", "COBERTURA_EDUCATIVA"),

    # ===== Grupos Talento Docente =====
    ("ADMINISTRACION DE PLANTA", "ADMINISTRACION_PLANTA"),
    ("ADMINISTRACION PLANTA", "ADMINISTRACION_PLANTA"),
    ("ADMINISTRACION DE LA PLANTA", "ADMINISTRACION_PLANTA"),
    ("ADM PLANTA", "ADMINISTRACION_PLANTA"),
    ("PLANTA DOCENTE", "ADMINISTRACION_PLANTA"),
    ("DESARROLLO DOCENTE", "DESARROLLO_DOCENTE"),
    ("CARRERA DOCENTE", "CARRERA_DOCENTE"),
    ("PRESTACIONES SOCIALES", "PRESTACIONES_SOCIALES"),
    ("PRESTACIONES", "PRESTACIONES_SOCIALES"),
    ("MAGISTERIO", "PRESTACIONES_SOCIALES"),
    ("NOMINA", "NOMINA"),
    ("HISTORIAS LABORALES", "HISTORIAS_LABORALES"),
    ("HISTORIAS", "HISTORIAS_LABORALES"),

    # ===== Grupos Admin Financiera =====
    ("ATENCION AL CIUDADANO", "ATENCION_CIUDADANO"),
    ("ATENCION CIUDADANO", "ATENCION_CIUDADANO"),
    ("BIENES Y SERVICIOS", "BIENES_SERVICIOS"),
    ("SISTEMAS DE INFORMACION", "SISTEMAS_INFORMACION"),
    ("SISTEMAS", "SISTEMAS_INFORMACION"),

    # ===== Multi-dependencia (Excel: TODAS, dos áreas, etc.) =====
    ("TODAS", "MULTI"),
    ("MULTIPLES", "MULTI"),
    ("VARIAS DEPENDENCIAS", "MULTI"),

    # ===== Casos sin asignar =====
    ("SIN ASIGNAR", "SIN_ASIGNAR"),
    ("PENDIENTE", "SIN_ASIGNAR"),
]


@lru_cache(maxsize=1)
def _alias_index() -> list[tuple[str, str]]:
    return [(_norm(k), v) for k, v in DEPENDENCY_ALIASES]


@lru_cache(maxsize=2048)
def normalize_dependencia(input_str: Optional[str]) -> Optional[str]:
    """Devuelve el código canónico (ej. 'DIRECCION_TALENTO_DOCENTE') o None.

    Reconoce:
      - Excel shorthand: 'TALENTO HUMANO', 'ESTRATEGICA', 'FINANCIERA', 'PAE'
      - Nombres extraídos de docs: 'Dirección de Talento Humano Docente'
      - Combinaciones / typos comunes
      - Tópicos especiales: 'TRANSPORTE' → PERMANENCIA, 'INCLUSION' → CALIDAD
    """
    if not input_str:
        return None
    n = _norm(input_str)
    if not n:
        return None

    # Match exacto código canónico (ya viene normalizado)
    if get_unit(n.replace(" ", "_")):
        return n.replace(" ", "_")

    # Mejor coincidencia por substring (alias más específico primero gana)
    candidates = []
    for alias_norm, code in _alias_index():
        if alias_norm in n or n in alias_norm:
            # Penalizar matches cortos contra inputs largos
            specificity = len(alias_norm)
            candidates.append((specificity, code, alias_norm))

    if candidates:
        # Más específico primero
        candidates.sort(reverse=True)
        return candidates[0][1]

    return None


def normalize_with_metadata(input_str: Optional[str]) -> dict:
    """Como normalize_dependencia pero con metadata."""
    if not input_str:
        return {"code": None, "label": None, "method": "empty", "confidence": 0.0}
    code = normalize_dependencia(input_str)
    if not code:
        return {"code": None, "label": None, "method": "no_match", "confidence": 0.0}
    unit = get_unit(code)
    label = unit.label if unit else code
    n = _norm(input_str)
    # Confidence basada en longitud del match
    method = "alias"
    confidence = 0.85
    for alias_norm, c in _alias_index():
        if alias_norm == n and c == code:
            method = "exact"
            confidence = 1.0
            break
    return {"code": code, "label": label, "method": method, "confidence": confidence}
