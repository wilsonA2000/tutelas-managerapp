"""Tipos de datos del pipeline DeepSeek experimental."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DocClassification:
    doc_id: int
    filename: str
    tipo: str                    # uno de los 18 tipos canónicos
    instancia: str               # 1RA | 2DA | N/A
    confianza: str               # alta | media | baja
    señales: list[str]
    razon: str
    elapsed_ms: int = 0
    error: Optional[str] = None


@dataclass
class FieldValue:
    valor: str
    fuente_doc: str              # tipo de doc donde se encontró
    confianza: str               # alta | media | baja
    nota: str = ""               # edge case o aclaración


@dataclass
class FieldExtractionResult:
    case_id: int
    folder_name: str
    campos: dict[str, FieldValue]     # campo → FieldValue
    docs_usados: list[str]            # tipos de docs que se enviaron
    elapsed_ms: int = 0
    llm_calls: int = 0
    error: Optional[str] = None

    def to_flat_dict(self) -> dict[str, str]:
        """Devuelve {campo: valor} para comparar con DB."""
        return {k: v.valor for k, v in self.campos.items()}

    def completitud(self) -> float:
        filled = sum(1 for v in self.campos.values() if v.valor)
        return round(100 * filled / max(len(self.campos), 1), 1)


@dataclass
class CaseCoherenceResult:
    case_id: int
    carpeta_limpia: bool
    docs_propios: list[int]           # doc_ids que pertenecen
    docs_foraneos: list[int]          # doc_ids que NO pertenecen
    conflacion_detectada: bool
    alertas: list[str]
    razon: str
    elapsed_ms: int = 0


@dataclass
class EmailClassification:
    email_id: int
    caso_id_propuesto: Optional[int]
    confianza_match: str              # alta | media | baja | ninguna
    radicado_encontrado: str
    accionante_encontrado: str
    juzgado_encontrado: str
    tipo_docs_adjuntos: list[str]
    es_nuevo_caso: bool
    alerta_conflacion: bool
    razon: str
    elapsed_ms: int = 0


@dataclass
class PipelineResult:
    case_id: int
    folder_name: str
    # Resultados de cada fase
    doc_classifications: list[DocClassification] = field(default_factory=list)
    coherence: Optional[CaseCoherenceResult] = None
    extraction: Optional[FieldExtractionResult] = None
    # Comparación con v9
    diff_vs_v9: list[dict] = field(default_factory=list)   # [{campo, v9, deepseek, semaforo}]
    elapsed_ms_total: int = 0
    error: Optional[str] = None

    def summary(self) -> str:
        if self.extraction:
            comp = self.extraction.completitud()
            n_diff = len(self.diff_vs_v9)
            return f"Case {self.case_id}: {comp}% completitud, {n_diff} difs vs v9"
        return f"Case {self.case_id}: sin extracción"
