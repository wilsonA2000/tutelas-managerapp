"""Tipos del pipeline v9.

ExtractedFields es el contrato de salida: las 28 columnas del cuadro Excel.
Todos los módulos del pipeline producen y consumen este dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class FieldSource(str, Enum):
    """De dónde vino cada campo. Va a `field_sources_json` para auditoría."""

    EMPTY = "empty"
    REGEX = "regex"
    CATALOG = "catalog"
    EXCEL = "excel"
    LLM = "llm"
    MANUAL = "manual"


# Las 39 columnas del cuadro Excel (frontend/src/pages/Cuadro.tsx:23-61).
# Esta es la fuente única de verdad de qué campos extrae v9.
# NOTA: `completitud` es derivado (no se extrae) — se calcula en runtime.
EXCEL_FIELDS: tuple[str, ...] = (
    # Identificación
    "radicado_23_digitos",
    "radicado_forest",
    "tipo_actuacion",            # TUTELA / INCIDENTE
    # Partes
    "accionante",
    "accionados",
    "vinculados",
    # Materia
    "derecho_vulnerado",
    "categoria_tematica",
    # Juzgado y geografía
    "juzgado",
    "ciudad",
    # Fechas y narrativa
    "fecha_ingreso",
    "asunto",
    "pretensiones",
    # Asignación interna
    "oficina_responsable",
    "abogado_responsable",
    "estado",                    # ACTIVO / INACTIVO
    "fecha_respuesta",
    # Fallo 1ra instancia
    "sentido_fallo_1st",
    "fecha_fallo_1st",
    # Impugnación
    "impugnacion",               # SI / NO
    "quien_impugno",
    "forest_impugnacion",
    "juzgado_2nd",
    "sentido_fallo_2nd",
    "fecha_fallo_2nd",
    # Incidente / desacato (1ro, 2do, 3ro — un caso puede tener varios)
    "incidente",                 # SI / NO
    "fecha_apertura_incidente",
    "responsable_desacato",      # funcionario público sancionable (jurídico)
    "abogado_incidente",         # abogado SED del incidente (= abogado_responsable)
    "decision_incidente",
    "incidente_2",
    "fecha_apertura_incidente_2",
    "responsable_desacato_2",
    "abogado_incidente_2",
    "decision_incidente_2",
    "incidente_3",
    "fecha_apertura_incidente_3",
    "responsable_desacato_3",
    "abogado_incidente_3",
    "decision_incidente_3",
    # Observaciones (texto libre — usualmente edición manual o llenado por Excel)
    "observaciones",
)


@dataclass
class ExtractedFields:
    """Resultado de la extracción. 28 campos del cuadro + tracking de fuente.

    `values[campo]` contiene el valor extraído (o "" si no se encontró).
    `sources[campo]` contiene de qué etapa vino (regex/catalog/excel/llm).
    """

    values: dict[str, str] = field(default_factory=lambda: {f: "" for f in EXCEL_FIELDS})
    sources: dict[str, FieldSource] = field(default_factory=lambda: {f: FieldSource.EMPTY for f in EXCEL_FIELDS})

    # Campos derivados (no del Excel pero útiles internamente)
    abogado_canonical: Optional[str] = None
    abogado_canonical_confidence: float = 0.0
    dependencia_canonical: Optional[str] = None
    dependencia_canonical_confidence: float = 0.0
    # Jerarquía SED L1/L2/L3 derivada de dependencia_canonical (sed_org.py)
    direccion: Optional[str] = None    # L1: APOYO_DIRECTO / DIRECCION_TALENTO_DOCENTE / ...
    grupo: Optional[str] = None        # L2: NOMINA / FINANCIERA / CALIDAD_EDUCATIVA / ...
    equipo: Optional[str] = None       # L3: EQUIPO_TESORERIA / EQUIPO_PRESUPUESTO / ...

    def set(self, field_name: str, value: str, source: FieldSource) -> bool:
        """Escribe `field_name` solo si está vacío. Retorna True si escribió.

        Esta es la única forma de que un módulo escriba un campo. Garantiza
        que la primera etapa con un valor válido gana — sin sobrescrituras.
        """
        if field_name not in self.values:
            raise KeyError(f"Campo desconocido: {field_name}. Permitidos: {EXCEL_FIELDS}")
        if not value or not str(value).strip():
            return False
        if self.values[field_name]:
            return False  # ya escrito por etapa anterior; no pisar
        self.values[field_name] = str(value).strip()
        self.sources[field_name] = source
        return True

    def is_empty(self, field_name: str) -> bool:
        return not self.values.get(field_name)

    def missing_fields(self) -> list[str]:
        """Campos del Excel que siguen vacíos. Input para `llm_gap_fill`."""
        return [f for f in EXCEL_FIELDS if not self.values[f]]

    def completitud(self) -> float:
        """% de campos con valor (0-100)."""
        filled = sum(1 for v in self.values.values() if v)
        return round(100 * filled / len(EXCEL_FIELDS), 1)

    def to_dict(self) -> dict:
        return {**self.values, "completitud": self.completitud()}

    def sources_json(self) -> dict[str, str]:
        return {k: v.value for k, v in self.sources.items()}


@dataclass
class ExtractionResult:
    """Salida final del pipeline para 1 caso."""

    case_id: int
    folder_name: str
    fields: ExtractedFields
    docs_processed: int = 0
    docs_failed: int = 0
    timing_ms: dict[str, int] = field(default_factory=dict)  # etapa → ms
    warnings: list[str] = field(default_factory=list)
    llm_calls: int = 0  # cuántas veces se invocó LLM (objetivo: 0 o 1)

    def total_ms(self) -> int:
        return sum(self.timing_ms.values())

    def summary(self) -> str:
        f = self.fields
        return (
            f"Case {self.case_id} ({self.folder_name}): "
            f"{f.completitud()}% completitud, "
            f"{self.docs_processed} docs, {self.llm_calls} LLM calls, "
            f"{self.total_ms()}ms total"
        )
