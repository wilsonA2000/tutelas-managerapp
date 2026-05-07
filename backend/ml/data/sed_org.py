"""Organigrama oficial de la Secretaría de Educación de Santander.

Fuente: Decretos Departamentales No. 544 de 2021 y No. 048 de 2022.

Estructura jerárquica de 3 niveles:
  L1 — Despacho / Dirección (5 entidades)
  L2 — Grupos (17 entidades)
  L3 — Equipos (4, solo bajo Grupo Financiera)

Para training del clasificador `dependencia_normalized` se predice L2.
Para granularidad fina (cuadro 2026 ampliado) se puede agregar L3.
"""

from __future__ import annotations
from dataclasses import dataclass


# ============================================================
# Estructura jerárquica
# ============================================================

@dataclass(frozen=True)
class OrgUnit:
    code: str           # canónico estable (snake_case)
    label: str          # human-readable
    parent: str | None  # code del padre (None = top level)
    level: int          # 1, 2 o 3


SED_ORG: list[OrgUnit] = [
    # NIVEL 1 — Despacho + 4 Direcciones
    OrgUnit("APOYO_DIRECTO", "Apoyo Directo Despacho", None, 1),
    OrgUnit("DIRECCION_PERMANENCIA", "Dirección de Permanencia Escolar", None, 1),
    OrgUnit("DIRECCION_ESTRATEGICA", "Dirección Estratégica", None, 1),
    OrgUnit("DIRECCION_TALENTO_DOCENTE", "Dirección de Talento Humano Docente", None, 1),
    OrgUnit("DIRECCION_ADMIN_FINANCIERA", "Dirección Administrativa y Financiera", None, 1),

    # NIVEL 2 — Grupos bajo Apoyo Directo
    OrgUnit("INSPECCION_VIGILANCIA", "Grupo Inspección y Vigilancia", "APOYO_DIRECTO", 2),
    OrgUnit("APOYO_JURIDICO", "Grupo Apoyo Jurídico Educación", "APOYO_DIRECTO", 2),
    OrgUnit("SUPERVISORES_NUCLEO", "Supervisores de Educación y Directores de Núcleo", "APOYO_DIRECTO", 2),
    OrgUnit("PLANEACION_EDUCATIVA", "Grupo Planeación Educativa", "APOYO_DIRECTO", 2),

    # NIVEL 2 — Grupos bajo Dirección Estratégica
    OrgUnit("CALIDAD_EDUCATIVA", "Grupo Calidad Educativa", "DIRECCION_ESTRATEGICA", 2),
    OrgUnit("COBERTURA_EDUCATIVA", "Grupo Cobertura Educativa", "DIRECCION_ESTRATEGICA", 2),

    # NIVEL 2 — Grupos bajo Talento Humano Docente
    OrgUnit("ADMINISTRACION_PLANTA", "Grupo Administración Planta", "DIRECCION_TALENTO_DOCENTE", 2),
    OrgUnit("DESARROLLO_DOCENTE", "Grupo Desarrollo Docente", "DIRECCION_TALENTO_DOCENTE", 2),
    OrgUnit("CARRERA_DOCENTE", "Grupo Carrera Docente", "DIRECCION_TALENTO_DOCENTE", 2),
    OrgUnit("PRESTACIONES_SOCIALES", "Grupo Prestaciones Sociales del Magisterio", "DIRECCION_TALENTO_DOCENTE", 2),
    OrgUnit("NOMINA", "Grupo Nómina", "DIRECCION_TALENTO_DOCENTE", 2),
    OrgUnit("HISTORIAS_LABORALES", "Grupo Historias Laborales", "DIRECCION_TALENTO_DOCENTE", 2),

    # NIVEL 2 — Grupos bajo Dirección Administrativa y Financiera
    OrgUnit("ATENCION_CIUDADANO", "Grupo Atención al Ciudadano", "DIRECCION_ADMIN_FINANCIERA", 2),
    OrgUnit("BIENES_SERVICIOS", "Grupo Bienes y Servicios", "DIRECCION_ADMIN_FINANCIERA", 2),
    OrgUnit("SISTEMAS_INFORMACION", "Grupo Sistemas de Información", "DIRECCION_ADMIN_FINANCIERA", 2),
    OrgUnit("FINANCIERA", "Grupo Financiera", "DIRECCION_ADMIN_FINANCIERA", 2),

    # NIVEL 3 — Equipos bajo Grupo Financiera
    OrgUnit("EQUIPO_PRESUPUESTO", "Equipo Presupuesto", "FINANCIERA", 3),
    OrgUnit("EQUIPO_TESORERIA", "Equipo Tesorería", "FINANCIERA", 3),
    OrgUnit("EQUIPO_CONTABILIDAD", "Equipo Contabilidad", "FINANCIERA", 3),
    OrgUnit("EQUIPO_FONDOS_SERVICIOS", "Equipo Fondo de Servicios Educativos", "FINANCIERA", 3),

    # CATEGORÍAS ESPECIALES
    OrgUnit("MULTI", "Múltiples dependencias", None, 1),
    OrgUnit("SIN_ASIGNAR", "Sin asignar / no especificado", None, 1),
]


_BY_CODE: dict[str, OrgUnit] = {u.code: u for u in SED_ORG}


def get_unit(code: str) -> OrgUnit | None:
    return _BY_CODE.get(code)


def get_l1(code: str) -> str:
    """Devuelve el código L1 ancestro del código dado.

    Ejemplo:
      get_l1("NOMINA") -> "DIRECCION_TALENTO_DOCENTE"
      get_l1("EQUIPO_TESORERIA") -> "DIRECCION_ADMIN_FINANCIERA"
      get_l1("DIRECCION_ESTRATEGICA") -> "DIRECCION_ESTRATEGICA"
    """
    u = get_unit(code)
    if not u:
        return code
    while u.parent:
        u = _BY_CODE.get(u.parent)
        if not u:
            return code
    return u.code


def all_l2_codes() -> list[str]:
    return [u.code for u in SED_ORG if u.level == 2]


def all_l1_codes() -> list[str]:
    return [u.code for u in SED_ORG if u.level == 1]
