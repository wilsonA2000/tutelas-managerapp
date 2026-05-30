"""Sistema de memoria y aprendizaje del agente.

Cuando Wilson corrige un campo, la corrección se almacena y se usa como
few-shot example en futuras extracciones del mismo tipo.
"""

from datetime import datetime
from dataclasses import dataclass

from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.orm import Session

from backend.database.models import Base


class Correction(Base):
    """Corrección de un campo por el usuario."""
    __tablename__ = "corrections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, nullable=False, index=True)
    field_name = Column(String, nullable=False, index=True)
    ai_value = Column(Text, nullable=True)  # What AI extracted
    corrected_value = Column(Text, nullable=False)  # What user corrected to
    case_folder = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


def record_correction(db: Session, case_id: int, field_name: str,
                       ai_value: str, corrected_value: str, case_folder: str = ""):
    """Registrar una corrección del usuario."""
    if not corrected_value or corrected_value == ai_value:
        return
    correction = Correction(
        case_id=case_id,
        field_name=field_name,
        ai_value=ai_value or "",
        corrected_value=corrected_value,
        case_folder=case_folder,
    )
    db.add(correction)
    db.commit()


def get_recent_corrections(db: Session, case_id: int = None, field_name: str = None,
                            limit: int = 10) -> list:
    """Obtener correcciones recientes para usar como few-shot examples."""
    from backend.agent.context import CorrectionContext

    q = db.query(Correction).order_by(Correction.created_at.desc())
    if field_name:
        q = q.filter(Correction.field_name == field_name)
    # Exclude corrections from the same case (don't learn from itself)
    if case_id:
        q = q.filter(Correction.case_id != case_id)
    corrections = q.limit(limit).all()

    return [
        CorrectionContext(
            field_name=c.field_name,
            ai_value=c.ai_value or "",
            corrected_value=c.corrected_value,
            case_folder=c.case_folder or "",
        )
        for c in corrections
    ]


def get_correction_stats(db: Session) -> dict:
    """Estadísticas de correcciones por campo."""
    from sqlalchemy import func
    rows = db.query(
        Correction.field_name,
        func.count(Correction.id),
    ).group_by(Correction.field_name).all()

    return {
        "total": sum(r[1] for r in rows),
        "by_field": {r[0]: r[1] for r in rows},
    }


def detect_patterns(db: Session, min_occurrences: int = 3) -> list[dict]:
    """Detectar patrones de corrección recurrentes.

    Si Wilson corrige el mismo tipo de error 3+ veces, generar sugerencia.
    """
    from sqlalchemy import func

    # Group corrections by field_name + ai_value pattern
    corrections = db.query(Correction).order_by(Correction.field_name).all()

    patterns = {}
    for c in corrections:
        key = f"{c.field_name}:{c.ai_value[:30] if c.ai_value else 'empty'}"
        if key not in patterns:
            patterns[key] = {"field": c.field_name, "ai_values": [], "corrected_values": [], "count": 0}
        patterns[key]["ai_values"].append(c.ai_value)
        patterns[key]["corrected_values"].append(c.corrected_value)
        patterns[key]["count"] += 1

    # Return patterns with >= min_occurrences
    return [
        {
            "field": p["field"],
            "ai_value_sample": p["ai_values"][0],
            "corrected_value_sample": p["corrected_values"][0],
            "occurrences": p["count"],
            "suggestion": f"La IA pone '{p['ai_values'][0][:30]}' pero Wilson corrige a '{p['corrected_values'][0][:30]}' ({p['count']} veces)",
        }
        for p in patterns.values()
        if p["count"] >= min_occurrences
    ]
