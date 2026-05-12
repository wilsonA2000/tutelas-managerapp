"""Timeline builder — reconstruye cronología de eventos del caso.

Analiza TODOS los documentos y emails del caso, extrae eventos datables
("El 15/03/2026 se radicó...", "Mediante oficio del X se respondió..."),
los ordena cronológicamente y los devuelve como timeline estructurado.

Usado por narrative_builder para enriquecer OBSERVACIONES con cronología
real en lugar de texto genérico.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime


_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


@dataclass
class TimelineEvent:
    date: datetime
    date_str: str       # "15/03/2026"
    event: str          # descripción corta
    source: str = ""    # nombre del documento
    confidence: float = 0.5


# Patrones de evento: regex + función que extrae descripción
EVENT_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Radicación / interposición
    (re.compile(
        r"\b(?:el|mediante|en\s+fecha)\s+(\d{1,2}\s+de\s+[a-zñáéíóú]+\s+de\s+\d{4}|\d{1,2}[/\-]\d{1,2}[/\-]\d{4})"
        r"[^.]{0,150}(?:radic[oó]|interpus|present[oó]|formul[oó])[^.]{0,100}",
        re.IGNORECASE),
     "radicación/presentación"),
    # Fallos / decisiones
    (re.compile(
        r"(?:profer[ií]d[oa]|dictad[oa]|pronunciad[oa]|emitid[oa])\s+(?:el\s+)?"
        r"(\d{1,2}\s+de\s+[a-zñáéíóú]+\s+de\s+\d{4}|\d{1,2}[/\-]\d{1,2}[/\-]\d{4})"
        r"[^.]{0,150}",
        re.IGNORECASE),
     "fallo/decisión"),
    # Respuestas / oficios
    (re.compile(
        r"(?:respuesta|oficio|comunicaci[oó]n)\s+(?:de\s+fecha\s+|del?\s+)"
        r"(\d{1,2}\s+de\s+[a-zñáéíóú]+\s+de\s+\d{4}|\d{1,2}[/\-]\d{1,2}[/\-]\d{4})",
        re.IGNORECASE),
     "respuesta/oficio"),
    # Admisión de tutela
    (re.compile(
        r"\bADM[ÍI]TASE[^.]{0,100}(\d{1,2}\s+de\s+[a-zñáéíóú]+\s+de\s+\d{4}|\d{1,2}[/\-]\d{1,2}[/\-]\d{4})",
        re.IGNORECASE),
     "admisión"),
    # Impugnación
    (re.compile(
        r"impugn(?:a|ó|aci[oó]n)[^.]{0,100}(\d{1,2}\s+de\s+[a-zñáéíóú]+\s+de\s+\d{4}|\d{1,2}[/\-]\d{1,2}[/\-]\d{4})",
        re.IGNORECASE),
     "impugnación"),
    # Apertura desacato
    (re.compile(
        r"(?:incidente|apertura|abr[ií]ase)\s+(?:de\s+)?desacato[^.]{0,100}"
        r"(\d{1,2}\s+de\s+[a-zñáéíóú]+\s+de\s+\d{4}|\d{1,2}[/\-]\d{1,2}[/\-]\d{4})",
        re.IGNORECASE),
     "apertura desacato"),
]


def _parse_date(raw: str) -> datetime | None:
    raw = re.sub(r"\s+", " ", raw.strip())
    # Verbal
    m = re.match(r"(\d{1,2})\s+de\s+([a-zñáéíóú]+)\s+de\s+(\d{4})", raw, re.IGNORECASE)
    if m:
        d = int(m.group(1))
        mo = _MONTHS.get(m.group(2).lower())
        y = int(m.group(3))
        if mo:
            try:
                return datetime(y, mo, d)
            except ValueError:
                return None
    # Numérico DD/MM/YYYY
    m = re.match(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", raw)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def extract_timeline(documents: list[dict], max_events: int = 8) -> list[TimelineEvent]:
    """Extrae cronología del caso desde múltiples documentos.

    Args:
        documents: [{"filename": ..., "text": ..., "doc_type": ...}]
        max_events: máximo de eventos a retornar (orden ascendente por fecha).

    Returns:
        Lista de TimelineEvent ordenada cronológicamente.
    """
    seen: set[tuple[str, str]] = set()  # dedup por (date_str, event_type)
    events: list[TimelineEvent] = []

    for doc in documents:
        text = doc.get("text") or ""
        filename = doc.get("filename") or ""
        if not text:
            continue

        for pat, event_type in EVENT_PATTERNS:
            for m in pat.finditer(text):
                date_raw = m.group(1)
                dt = _parse_date(date_raw)
                if not dt:
                    continue
                # Descarta fechas muy viejas (ruido) o futuras >1 año
                if dt.year < 2000 or dt.year > 2030:
                    continue
                date_str = dt.strftime("%d/%m/%Y")
                key = (date_str, event_type)
                if key in seen:
                    continue
                seen.add(key)
                # Contexto breve del evento (30 chars alrededor del match)
                ctx_start = max(0, m.start() - 20)
                ctx_end = min(len(text), m.end() + 40)
                snippet = re.sub(r"\s+", " ", text[ctx_start:ctx_end]).strip()
                events.append(TimelineEvent(
                    date=dt, date_str=date_str,
                    event=f"{event_type}: {snippet[:120]}",
                    source=filename, confidence=0.7,
                ))

    events.sort(key=lambda e: e.date)
    return events[:max_events]


def build_timeline_summary(events: list[TimelineEvent], max_lines: int = 5) -> str:
    """Convierte lista de eventos en texto narrativo: 'El X/Y/Z sucedió A'."""
    if not events:
        return ""
    lines = []
    for e in events[:max_lines]:
        lines.append(f"{e.date_str}: {e.event.split(':', 1)[-1].strip()[:100]}")
    return " | ".join(lines)
