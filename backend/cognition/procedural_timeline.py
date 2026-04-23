"""Procedural Timeline — Capa 4 del pipeline cognitivo v6.0.

Construye la línea temporal del proceso jurídico ordenando los documentos del
caso por fecha + tipología, etiquetando cada uno con su posición en el ciclo:

    SOLICITUD → AUTO_ADMISORIO → RESPUESTA → FALLO_1ST → IMPUGNACION →
    FALLO_2ND → INCIDENTE_1 → SANCION_1 → INCIDENTE_2 → ...

Casos con solo docs de incidente (sin AUTO_ADMISORIO ni SENTENCIA) son
candidatos a INCIDENTE_HUERFANO — probablemente continuación de una tutela
previa cuyo registro no está en DB.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


# ============================================================
# Posiciones posibles en el ciclo procesal
# ============================================================

CYCLE_POSITIONS = (
    "SOLICITUD",           # escrito de tutela del accionante
    "AUTO_ADMISORIO",      # auto de admisión del juez
    "AUTO_VINCULA",        # auto que vincula terceros
    "RESPUESTA",           # respuesta de la entidad accionada
    "FALLO_1ST",           # sentencia de primera instancia
    "IMPUGNACION",         # escrito de impugnación
    "AUTO_IMPUGNACION",    # auto que concede impugnación
    "FALLO_2ND",           # sentencia de segunda instancia
    "REMITE_CONSULTA",     # remisión a grado de consulta
    "INCIDENTE",           # solicitud/apertura de incidente de desacato
    "AUTO_INCIDENTE",
    "SANCION",             # auto que sanciona desacato
    "CUMPLIMIENTO",        # comunicación de cumplimiento
    "OFICIO",              # oficios generales (notificaciones)
    "ANEXO",               # anexos, pruebas
    "OTRO",
)


# Mapeo determinista de doc_type (ya existente) → posición probable en el ciclo
DOC_TYPE_TO_POSITION = {
    "PDF_AUTO_ADMISORIO": "AUTO_ADMISORIO",
    "PDF_SENTENCIA": "FALLO_1ST",                # se reevalúa con fechas si hay 2 sentencias
    "PDF_IMPUGNACION": "IMPUGNACION",
    "DOCX_IMPUGNACION": "IMPUGNACION",
    "PDF_INCIDENTE": "INCIDENTE",
    "DOCX_DESACATO": "INCIDENTE",
    "DOCX_CUMPLIMIENTO": "CUMPLIMIENTO",
    "DOCX_RESPUESTA": "RESPUESTA",
    "DOCX_CONTESTACION": "RESPUESTA",
    "DOCX_SOLICITUD": "SOLICITUD",
    "DOCX_MEMORIAL": "OFICIO",
    "DOCX_CARTA": "OFICIO",
    "EMAIL_MD": "OFICIO",
    "PDF_OTRO": "OTRO",
    "PDF_GMAIL": "OFICIO",
    "DOCX_OTRO": "OTRO",
}


# ============================================================
# Entidades del timeline
# ============================================================

@dataclass
class TimelineEvent:
    """Un evento procesal: un doc ubicado en una posición del ciclo."""
    doc_filename: str
    doc_type: str
    position: str
    fecha: Optional[str] = None          # DD/MM/YYYY si se conoce
    confidence: float = 0.7
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "doc": self.doc_filename,
            "doc_type": self.doc_type,
            "position": self.position,
            "fecha": self.fecha,
            "confidence": round(self.confidence, 3),
            "signals": self.signals,
        }


@dataclass
class ProcessTimeline:
    case_id: int
    events: list[TimelineEvent] = field(default_factory=list)

    def has_position(self, position: str) -> bool:
        return any(e.position == position for e in self.events)

    def positions(self) -> set[str]:
        return {e.position for e in self.events}

    def count_position(self, position: str) -> int:
        return sum(1 for e in self.events if e.position == position)

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "events": [e.to_dict() for e in self.events],
            "summary": {
                "total_events": len(self.events),
                "positions": sorted(self.positions()),
                "has_auto_admisorio": self.has_position("AUTO_ADMISORIO"),
                "has_sentencia": self.has_position("FALLO_1ST"),
                "has_impugnacion": self.has_position("IMPUGNACION"),
                "has_fallo_2nd": self.has_position("FALLO_2ND"),
                "incidentes": self.count_position("INCIDENTE"),
                "sanciones": self.count_position("SANCION"),
            },
        }


# ============================================================
# Construcción
# ============================================================

_RE_FECHA_NUM = re.compile(r"(\d{1,2})[/\-](\d{1,2})[/\-](20\d{2})")


def _parse_date(text: str) -> Optional[str]:
    m = _RE_FECHA_NUM.search(text or "")
    if not m:
        return None
    return f"{m.group(1).zfill(2)}/{m.group(2).zfill(2)}/{m.group(3)}"


def _refine_position(doc_type: str, filename: str, text: str) -> tuple[str, list[str]]:
    """Refina la posición basándose en palabras clave del doc (además del type)."""
    base = DOC_TYPE_TO_POSITION.get(doc_type, "OTRO")
    signals: list[str] = [f"doc_type={doc_type}"]
    fn_upper = (filename or "").upper()
    text_head = (text or "")[:3000].upper()

    # Sentencia de 2ª instancia
    if base == "FALLO_1ST" and (
        "SEGUNDA INSTANCIA" in text_head
        or "CONFIRMA" in text_head[:1500]
        or "REVOCA" in text_head[:1500]
        or "2DA" in fn_upper
        or "SEGUNDA" in fn_upper
    ):
        return "FALLO_2ND", signals + ["kw=segunda_instancia"]

    # Auto de sanción
    if "SANCION" in fn_upper or "SANCIONA" in text_head[:1500]:
        return "SANCION", signals + ["kw=sancion"]

    # Auto que concede impugnación
    if base == "OTRO" and "CONCEDE" in text_head[:1000] and "IMPUGNACI" in text_head[:2000]:
        return "AUTO_IMPUGNACION", signals + ["kw=concede_impugnacion"]

    # Auto que vincula
    if "VINCULA" in fn_upper or "VINCULAR" in text_head[:1500]:
        return "AUTO_VINCULA", signals + ["kw=vincula"]

    # Remite a grado de consulta
    if "GRADO DE CONSULTA" in text_head[:2000] or "GRADO_CONSULTA" in fn_upper:
        return "REMITE_CONSULTA", signals + ["kw=grado_consulta"]

    # Auto apertura incidente
    if base == "INCIDENTE" and ("APERTURA" in text_head[:2000] or "APERTURA" in fn_upper):
        return "AUTO_INCIDENTE", signals + ["kw=apertura_incidente"]

    return base, signals


def build_timeline(case, case_ir=None) -> ProcessTimeline:
    """Construye el timeline procesal a partir de los documentos del caso."""
    tl = ProcessTimeline(case_id=getattr(case, "id", -1))

    docs = case.documents if not case_ir else case.documents  # usamos docs de DB para doc_type
    for doc in docs:
        filename = doc.filename or ""
        doc_type = doc.doc_type or "OTRO"
        text = doc.extracted_text or ""
        fecha = _parse_date(text) or _parse_date(filename)
        position, signals = _refine_position(doc_type, filename, text)
        tl.events.append(TimelineEvent(
            doc_filename=filename,
            doc_type=doc_type,
            position=position,
            fecha=fecha,
            confidence=0.8 if fecha else 0.6,
            signals=signals,
        ))

    # Orden por fecha (None va al final)
    def _sort_key(e):
        if not e.fecha:
            return (9, "")
        d, m, y = e.fecha.split("/")
        return (0, f"{y}{m}{d}")
    tl.events.sort(key=_sort_key)

    return tl
