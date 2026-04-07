"""Cadena de razonamiento legal: almacena evidencia y explicación por cada decisión IA."""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, Float
from backend.database.models import Base


class ReasoningLog(Base):
    """Log de razonamiento almacenado en DB."""
    __tablename__ = "reasoning_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, nullable=False, index=True)
    field_name = Column(String, nullable=False)
    value = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    method = Column(String, nullable=True)  # regex, ai, cross_validated, manual
    source = Column(String, nullable=True)  # filename or source description
    reasoning = Column(Text, nullable=True)  # explanation in Spanish
    evidence_json = Column(Text, nullable=True)  # JSON array of evidence snippets
    created_at = Column(DateTime, default=datetime.utcnow)


@dataclass
class Evidence:
    """Una pieza de evidencia para una decisión."""
    source: str
    text_snippet: str
    relevance: float  # 0-1


@dataclass
class ReasoningChain:
    """Cadena de razonamiento para una extracción de campo."""
    field_name: str
    value: str
    confidence: int  # 0-100
    method: str
    evidence: list[Evidence] = field(default_factory=list)
    reasoning: str = ""

    def to_spanish(self) -> str:
        """Generar explicación legible en español."""
        parts = [f"Campo: {self.field_name}"]
        parts.append(f"Valor: {self.value}")
        parts.append(f"Confianza: {self.confidence}%")
        parts.append(f"Método: {self.method}")
        if self.evidence:
            parts.append("Evidencia:")
            for ev in self.evidence[:5]:
                parts.append(f"  - [{ev.source}] \"{ev.text_snippet[:100]}\"")
        if self.reasoning:
            parts.append(f"Razonamiento: {self.reasoning}")
        return "\n".join(parts)

    def to_db_log(self, case_id: int) -> ReasoningLog:
        """Convertir a modelo de DB."""
        import json
        evidence_json = json.dumps([
            {"source": e.source, "snippet": e.text_snippet[:200], "relevance": e.relevance}
            for e in self.evidence[:10]
        ], ensure_ascii=False)

        return ReasoningLog(
            case_id=case_id,
            field_name=self.field_name,
            value=self.value,
            confidence=self.confidence,
            method=self.method,
            source=self.evidence[0].source if self.evidence else "",
            reasoning=self.reasoning,
            evidence_json=evidence_json,
        )


def save_reasoning(db, case_id: int, chains: list[ReasoningChain]):
    """Guardar cadenas de razonamiento en DB (reemplaza las anteriores del caso)."""
    # Delete old reasoning for this case
    db.query(ReasoningLog).filter(ReasoningLog.case_id == case_id).delete()
    for chain in chains:
        db.add(chain.to_db_log(case_id))
    db.commit()


def get_reasoning(db, case_id: int) -> list[dict]:
    """Obtener razonamiento almacenado para un caso."""
    import json
    logs = db.query(ReasoningLog).filter(
        ReasoningLog.case_id == case_id
    ).order_by(ReasoningLog.field_name).all()

    return [
        {
            "field_name": log.field_name,
            "value": log.value,
            "confidence": log.confidence,
            "method": log.method,
            "source": log.source,
            "reasoning": log.reasoning,
            "evidence": json.loads(log.evidence_json) if log.evidence_json else [],
            "created_at": log.created_at.isoformat() if log.created_at else "",
        }
        for log in logs
    ]
